from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import asyncpg
from pydantic import BaseModel, Field, model_validator

from agentictriage.models import PipelineResult, RetrievedChunk, TenantPolicy, Ticket
from agentictriage.pipeline import TriagePipeline


class JobPayload(BaseModel):
    ticket: Ticket
    correlation_id: str
    policy: TenantPolicy
    knowledge_base: list[RetrievedChunk]


class JobSubmission(BaseModel):
    id: str
    status: str


class ReviewAction(StrEnum):
    APPROVE_RESPONSE = "approve_response"
    KEEP_ESCALATED = "keep_escalated"


class JobRecord(BaseModel):
    id: str
    ticket_id: str
    subject: str
    status: str
    attempts: int
    review_state: str
    escalation_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class JobReview(BaseModel):
    action: ReviewAction
    operator_response: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def require_approved_response(self) -> JobReview:
        if self.action is ReviewAction.APPROVE_RESPONSE and not (
            self.operator_response and self.operator_response.strip()
        ):
            raise ValueError("approve_response requires operator_response")
        return self


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: str
    payload: JobPayload


class PostgresJobQueue:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def enqueue(
        self, tenant_id: str, idempotency_key: str, payload: JobPayload
    ) -> JobSubmission:
        async with self._pool.acquire() as connection, connection.transaction():
            await _tenant(connection, tenant_id)
            row = await connection.fetchrow(
                """
                insert into triage_jobs (tenant_id, idempotency_key, payload)
                values ($1, $2, $3::jsonb)
                on conflict (tenant_id, idempotency_key)
                do update set idempotency_key = excluded.idempotency_key
                returning id::text, status
                """,
                tenant_id,
                idempotency_key,
                payload.model_dump_json(),
            )
        return JobSubmission.model_validate(dict(row))

    async def claim(self) -> ClaimedJob | None:
        row = await self._pool.fetchrow("select * from claim_triage_job()")
        if not row:
            return None
        payload: Any = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return ClaimedJob(id=row["id"], payload=JobPayload.model_validate(payload))

    async def finish(self, job_id: str, tenant_id: str, result: PipelineResult) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            await _tenant(connection, tenant_id)
            await connection.execute(
                """
                update triage_jobs set status='complete', result=$2::jsonb,
                  review_state=$3, updated_at=now()
                where id=$1::uuid
                """,
                job_id,
                result.model_dump_json(),
                "open" if result.decision.action == "escalate" else "not_required",
            )

    async def fail(self, job_id: str, tenant_id: str, error: str) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            await _tenant(connection, tenant_id)
            await connection.execute(
                """
                update triage_jobs set status='failed', error=$2, updated_at=now()
                where id=$1::uuid
                """,
                job_id,
                error[:1000],
            )

    async def list_escalations(self, tenant_id: str, limit: int = 50) -> list[JobRecord]:
        async with self._pool.acquire() as connection, connection.transaction():
            await _tenant(connection, tenant_id)
            rows = await connection.fetch(
                """
                select id::text, payload->'ticket'->>'id' as ticket_id,
                  payload->'ticket'->>'subject' as subject, status, attempts, review_state,
                  result->'decision'->>'escalation_reason' as escalation_reason,
                  created_at, updated_at
                from triage_jobs
                where tenant_id=$1 and review_state='open'
                order by created_at limit $2
                """,
                tenant_id,
                limit,
            )
        return [JobRecord.model_validate(dict(row)) for row in rows]

    async def review(self, job_id: str, tenant_id: str, review: JobReview, reviewer: str) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            await _tenant(connection, tenant_id)
            result: str = await connection.execute(
                """
                update triage_jobs set review_state=$3, operator_response=$4,
                  reviewed_by=$5, reviewed_at=now(), updated_at=now()
                where id=$1::uuid and tenant_id=$2 and review_state='open'
                """,
                job_id,
                tenant_id,
                "approved" if review.action is ReviewAction.APPROVE_RESPONSE else "kept_escalated",
                review.operator_response,
                reviewer,
            )
        return result == "UPDATE 1"


async def _tenant(connection: asyncpg.Connection, tenant_id: str) -> None:
    await connection.execute("select set_config('app.tenant_id', $1, true)", tenant_id)


async def run_worker(queue: PostgresJobQueue, pipeline: TriagePipeline) -> None:
    while True:
        job = await queue.claim()
        if job is None:
            await asyncio.sleep(0.5)
            continue
        try:
            value = job.payload
            result = await pipeline.process(
                value.ticket,
                correlation_id=value.correlation_id,
                policy=value.policy,
                knowledge_base=value.knowledge_base,
            )
            await queue.finish(job.id, value.ticket.tenant_id, result)
        except Exception as exc:
            await queue.fail(job.id, job.payload.ticket.tenant_id, type(exc).__name__)
