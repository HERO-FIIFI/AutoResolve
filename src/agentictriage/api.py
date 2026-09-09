from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agentictriage.config import Settings
from agentictriage.fallback import FallbackRouter
from agentictriage.jobs import JobPayload, JobSubmission, PostgresJobQueue
from agentictriage.models import PipelineResult, RetrievedChunk, TenantPolicy, Ticket
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
        "X-Tenant-ID",
    ],
)


class TriageRequest(BaseModel):
    ticket: Ticket
    knowledge_base: list[RetrievedChunk] = Field(default_factory=list, max_length=100)
    confidence_threshold: float = Field(default=0.8, ge=0, le=1)
    allowed_providers: set[str] = Field(default_factory=set)
    allowed_regions: set[str] = Field(default_factory=set)


class Identity(BaseModel):
    tenant_id: str
    roles: frozenset[str]


def identity(
    x_tenant_id: Annotated[str, Header()],
    x_roles: Annotated[str, Header()],
) -> Identity:
    roles = frozenset(part.strip() for part in x_roles.split(",") if part.strip())
    if "triage:write" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing role")
    return Identity(tenant_id=x_tenant_id, roles=roles)


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
    if request.ticket.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    store: StateStore = raw_request.app.state.store
    if previous := await store.get_idempotent_result(principal.tenant_id, idempotency_key):
        return previous
    policy = TenantPolicy(
        tenant_id=principal.tenant_id,
        confidence_threshold=request.confidence_threshold,
        allowed_providers=frozenset(request.allowed_providers),
        allowed_regions=frozenset(request.allowed_regions),
    )
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
        policy=TenantPolicy(
            tenant_id=principal.tenant_id,
            confidence_threshold=request.confidence_threshold,
            allowed_providers=frozenset(request.allowed_providers),
            allowed_regions=frozenset(request.allowed_regions),
        ),
        knowledge_base=request.knowledge_base,
    )
    return await queue.enqueue(principal.tenant_id, idempotency_key, payload)
