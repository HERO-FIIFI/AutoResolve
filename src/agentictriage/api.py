from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from agentictriage.audit import AuditEvent
from agentictriage.config import Settings
from agentictriage.fallback import FallbackRouter
from agentictriage.jobs import JobPayload, JobRecord, JobReview, JobSubmission, PostgresJobQueue
from agentictriage.models import (
    AuditRecord,
    PipelineResult,
    RetrievedChunk,
    TenantPolicy,
    TenantPolicyRecord,
    Ticket,
)
from agentictriage.pipeline import TriagePipeline
from agentictriage.storage import MemoryStateStore, PostgresStateStore, StateStore

_settings = Settings.from_environment()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    store: StateStore
    postgres: PostgresStateStore | None = None
    if _settings.database_url:
        postgres = PostgresStateStore(_settings.database_url)
        await postgres.open()
        store = postgres
        application.state.jobs = PostgresJobQueue(postgres.pool)
    else:
        store = MemoryStateStore()
    application.state.store = store
    application.state.pipeline = TriagePipeline(FallbackRouter(_settings.providers()), store)
    yield
    if postgres:
        await postgres.close()


app = FastAPI(title="AgenticTriage-AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=[
        "Content-Type",
        "Idempotency-Key",
        "X-Correlation-ID",
        "X-Roles",
        "X-Subject",
        "X-Tenant-ID",
    ],
)


class TriageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: Ticket
    knowledge_base: list[RetrievedChunk] = Field(default_factory=list, max_length=100)


class PolicyUpdate(BaseModel):
    confidence_threshold: float = Field(ge=0, le=1)
    allowed_providers: set[str] = Field(max_length=20)
    allowed_regions: set[str] = Field(max_length=20)


class Identity(BaseModel):
    tenant_id: str
    roles: frozenset[str]
    subject: str


def identity(
    x_tenant_id: Annotated[str, Header()],
    x_roles: Annotated[str, Header()],
    x_subject: Annotated[str, Header()] = "local-user",
) -> Identity:
    roles = frozenset(part.strip() for part in x_roles.split(",") if part.strip())
    return Identity(tenant_id=x_tenant_id, roles=roles, subject=x_subject)


def require_role(principal: Identity, role: str) -> None:
    if role not in principal.roles and "admin" not in principal.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing role")


async def policy_for(store: StateStore, principal: Identity) -> TenantPolicyRecord:
    policy = await store.get_policy(principal.tenant_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="tenant policy unavailable"
        )
    return policy


@app.get("/healthz", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/triage", response_model=PipelineResult)
async def triage(
    raw_request: Request,
    request: TriageRequest,
    principal: Annotated[Identity, Depends(identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
    x_correlation_id: Annotated[
        str, Header(alias="X-Correlation-ID", min_length=8, max_length=200)
    ],
) -> PipelineResult:
    require_role(principal, "triage:write")
    if request.ticket.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    store: StateStore = raw_request.app.state.store
    if previous := await store.get_idempotent_result(principal.tenant_id, idempotency_key):
        return previous
    policy = await policy_for(store, principal)
    pipeline: TriagePipeline = raw_request.app.state.pipeline
    result = await pipeline.process(
        request.ticket,
        correlation_id=x_correlation_id,
        policy=policy,
        knowledge_base=request.knowledge_base,
    )
    return await store.put_idempotent_result(principal.tenant_id, idempotency_key, result)


@app.post("/v1/triage/jobs", response_model=JobSubmission, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_triage(
    raw_request: Request,
    request: TriageRequest,
    principal: Annotated[Identity, Depends(identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
    x_correlation_id: Annotated[
        str, Header(alias="X-Correlation-ID", min_length=8, max_length=200)
    ],
) -> JobSubmission:
    require_role(principal, "triage:write")
    if request.ticket.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    queue: PostgresJobQueue | None = getattr(raw_request.app.state, "jobs", None)
    if queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="durable queue unavailable",
        )
    payload = JobPayload(
        ticket=request.ticket,
        correlation_id=x_correlation_id,
        policy=await policy_for(raw_request.app.state.store, principal),
        knowledge_base=request.knowledge_base,
    )
    return await queue.enqueue(principal.tenant_id, idempotency_key, payload)


@app.get("/v1/policy", response_model=TenantPolicyRecord)
async def get_policy(
    raw_request: Request, principal: Annotated[Identity, Depends(identity)]
) -> TenantPolicyRecord:
    require_role(principal, "policy:read")
    return await policy_for(raw_request.app.state.store, principal)


@app.put("/v1/policy", response_model=TenantPolicyRecord)
async def update_policy(
    raw_request: Request,
    update: PolicyUpdate,
    principal: Annotated[Identity, Depends(identity)],
) -> TenantPolicyRecord:
    require_role(principal, "policy:write")
    store: StateStore = raw_request.app.state.store
    policy = await store.put_policy(
        TenantPolicy(tenant_id=principal.tenant_id, **update.model_dump())
    )
    await store.append(
        AuditEvent(
            event_type="policy.updated",
            tenant_id=principal.tenant_id,
            ticket_id="policy",
            correlation_id=str(uuid4()),
            attributes={"version": policy.version, "updated_by": principal.subject},
        )
    )
    return policy


@app.get("/v1/audit", response_model=list[AuditRecord])
async def list_audit(
    raw_request: Request,
    principal: Annotated[Identity, Depends(identity)],
    limit: int = 20,
) -> list[AuditRecord]:
    require_role(principal, "audit:read")
    store: StateStore = raw_request.app.state.store
    return await store.list_audit(principal.tenant_id, min(max(limit, 1), 100))


@app.get("/v1/triage/jobs", response_model=list[JobRecord])
async def list_escalations(
    raw_request: Request, principal: Annotated[Identity, Depends(identity)]
) -> list[JobRecord]:
    require_role(principal, "triage:read")
    queue: PostgresJobQueue | None = getattr(raw_request.app.state, "jobs", None)
    if queue is None:
        return []
    return await queue.list_escalations(principal.tenant_id)


@app.post("/v1/triage/jobs/{job_id}/review", status_code=status.HTTP_204_NO_CONTENT)
async def review_escalation(
    job_id: UUID,
    review: JobReview,
    raw_request: Request,
    principal: Annotated[Identity, Depends(identity)],
) -> None:
    require_role(principal, "triage:write")
    queue: PostgresJobQueue | None = getattr(raw_request.app.state, "jobs", None)
    if queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="queue unavailable"
        )
    if not await queue.review(str(job_id), principal.tenant_id, review, principal.subject):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="open escalation not found"
        )
    store: StateStore = raw_request.app.state.store
    await store.append(
        AuditEvent(
            event_type="escalation.reviewed",
            tenant_id=principal.tenant_id,
            ticket_id=str(job_id),
            correlation_id=str(uuid4()),
            attributes={"action": review.action, "reviewed_by": principal.subject},
        )
    )
