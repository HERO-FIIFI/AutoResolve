from __future__ import annotations

import json
from typing import Protocol

import asyncpg

from agentictriage.audit import AuditEvent, AuditSink
from agentictriage.models import AuditRecord, PipelineResult, TenantPolicy, TenantPolicyRecord


class StateStore(AuditSink, Protocol):
    async def get_policy(self, tenant_id: str) -> TenantPolicyRecord | None: ...

    async def put_policy(self, policy: TenantPolicy) -> TenantPolicyRecord: ...

    async def list_audit(self, tenant_id: str, limit: int = 20) -> list[AuditRecord]: ...

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
        self.policies: dict[str, TenantPolicyRecord] = {}

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    async def get_policy(self, tenant_id: str) -> TenantPolicyRecord | None:
        return self.policies.get(tenant_id) or await self.put_policy(
            TenantPolicy(tenant_id=tenant_id)
        )

    async def put_policy(self, policy: TenantPolicy) -> TenantPolicyRecord:
        from datetime import UTC, datetime

        previous = self.policies.get(policy.tenant_id)
        record = TenantPolicyRecord(
            **policy.model_dump(),
            version=(previous.version + 1 if previous else 1),
            updated_at=datetime.now(UTC),
        )
        self.policies[policy.tenant_id] = record
        return record

    async def list_audit(self, tenant_id: str, limit: int = 20) -> list[AuditRecord]:
        own = (event for event in reversed(self.events) if event.tenant_id == tenant_id)
        return [
            AuditRecord(
                sequence_id=index,
                ticket_id=event.ticket_id,
                correlation_id=event.correlation_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                attributes=event.attributes,
            )
            for index, event in enumerate(list(own)[:limit], start=1)
        ]

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

    async def get_policy(self, tenant_id: str) -> TenantPolicyRecord | None:
        async with self._require_pool().acquire() as connection, connection.transaction():
            await _tenant(connection, tenant_id)
            row = await connection.fetchrow(
                """
                select tenant_id, confidence_threshold, allowed_providers, allowed_regions,
                       version, updated_at
                from tenant_policies where tenant_id = $1
                """,
                tenant_id,
            )
        return TenantPolicyRecord.model_validate(dict(row)) if row else None

    async def put_policy(self, policy: TenantPolicy) -> TenantPolicyRecord:
        async with self._require_pool().acquire() as connection, connection.transaction():
            await _tenant(connection, policy.tenant_id)
            row = await connection.fetchrow(
                """
                insert into tenant_policies
                  (tenant_id, confidence_threshold, allowed_providers, allowed_regions)
                values ($1, $2, $3, $4)
                on conflict (tenant_id) do update set
                  confidence_threshold = excluded.confidence_threshold,
                  allowed_providers = excluded.allowed_providers,
                  allowed_regions = excluded.allowed_regions,
                  version = tenant_policies.version + 1,
                  updated_at = now()
                returning tenant_id, confidence_threshold, allowed_providers, allowed_regions,
                          version, updated_at
                """,
                policy.tenant_id,
                policy.confidence_threshold,
                list(policy.allowed_providers),
                list(policy.allowed_regions),
            )
        return TenantPolicyRecord.model_validate(dict(row))

    async def list_audit(self, tenant_id: str, limit: int = 20) -> list[AuditRecord]:
        async with self._require_pool().acquire() as connection, connection.transaction():
            await _tenant(connection, tenant_id)
            rows = await connection.fetch(
                """
                select sequence_id, ticket_id, correlation_id, event_type, occurred_at, attributes
                from audit_events where tenant_id = $1
                order by sequence_id desc limit $2
                """,
                tenant_id,
                limit,
            )
        records: list[AuditRecord] = []
        for row in rows:
            value = dict(row)
            if isinstance(value["attributes"], str):
                value["attributes"] = json.loads(value["attributes"])
            records.append(AuditRecord.model_validate(value))
        return records

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


async def _tenant(connection: asyncpg.Connection, tenant_id: str) -> None:
    await connection.execute("select set_config('app.tenant_id', $1, true)", tenant_id)
