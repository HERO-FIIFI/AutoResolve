from __future__ import annotations

import json
from typing import Protocol

import asyncpg

from agentictriage.audit import AuditEvent, AuditSink
from agentictriage.models import PipelineResult


class StateStore(AuditSink, Protocol):
    async def get_idempotent_result(
        self, tenant_id: str, idempotency_key: str
    ) -> PipelineResult | None: ...

    async def put_idempotent_result(
        self, tenant_id: str, idempotency_key: str, result: PipelineResult
    ) -> PipelineResult: ...


class MemoryStateStore:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []
        self.results: dict[tuple[str, str], PipelineResult] = {}

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    async def get_idempotent_result(
        self, tenant_id: str, idempotency_key: str
    ) -> PipelineResult | None:
        return self.results.get((tenant_id, idempotency_key))

    async def put_idempotent_result(
        self, tenant_id: str, idempotency_key: str, result: PipelineResult
    ) -> PipelineResult:
        return self.results.setdefault((tenant_id, idempotency_key), result)


class PostgresStateStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def open(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=10)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgreSQL store has not been opened")
        return self._pool

    @property
    def pool(self) -> asyncpg.Pool:
        return self._require_pool()

    async def append(self, event: AuditEvent) -> None:
        async with self._require_pool().acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "select set_config('app.tenant_id', $1, true)", event.tenant_id
                )
                await connection.execute(
                    """
                    insert into audit_events
                      (tenant_id, ticket_id, correlation_id, event_type, occurred_at, attributes)
                    values ($1, $2, $3, $4, $5, $6::jsonb)
                    """,
                    event.tenant_id,
                    event.ticket_id,
                    event.correlation_id,
                    event.event_type,
                    event.occurred_at,
                    json.dumps(event.attributes, default=str),
                )

    async def get_idempotent_result(
        self, tenant_id: str, idempotency_key: str
    ) -> PipelineResult | None:
        async with self._require_pool().acquire() as connection:
            async with connection.transaction():
                await connection.execute("select set_config('app.tenant_id', $1, true)", tenant_id)
                value = await connection.fetchval(
                    """
                    select result from idempotency_records
                    where tenant_id = $1 and idempotency_key = $2
                    """,
                    tenant_id,
                    idempotency_key,
                )
        return _result(value) if value else None

    async def put_idempotent_result(
        self, tenant_id: str, idempotency_key: str, result: PipelineResult
    ) -> PipelineResult:
        serialized = result.model_dump_json()
        async with self._require_pool().acquire() as connection:
            async with connection.transaction():
                await connection.execute("select set_config('app.tenant_id', $1, true)", tenant_id)
                value = await connection.fetchval(
                    """
                    insert into idempotency_records (tenant_id, idempotency_key, result)
                    values ($1, $2, $3::jsonb)
                    on conflict (tenant_id, idempotency_key)
                    do update set idempotency_key = excluded.idempotency_key
                    returning result
                    """,
                    tenant_id,
                    idempotency_key,
                    serialized,
                )
        return _result(value)


def _result(value: object) -> PipelineResult:
    if isinstance(value, str):
        return PipelineResult.model_validate_json(value)
    return PipelineResult.model_validate(value)
