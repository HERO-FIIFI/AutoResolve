from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import asyncpg
from pydantic import BaseModel

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
                update triage_jobs set status='complete', result=$2::jsonb, updated_at=now()
                where id=$1::uuid
                """,
                job_id,
                result.model_dump_json(),
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
