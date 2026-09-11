from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from agentictriage.audit import AuditEvent
from agentictriage.auth import issue_token, verify_token
from agentictriage.config import Settings
from agentictriage.fallback import FallbackRouter
from agentictriage.ingest import RowError, SheetFormatError, parse_tickets
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
from agentictriage.providers import OpenAICompatibleProvider, ProviderError
from agentictriage.storage import MemoryStateStore, PostgresStateStore, StateStore

_settings = Settings.from_environment()

# ponytail: a flat cap, read before parsing. Swap for streaming-to-disk if
# anyone needs to ingest sheets bigger than this.
MAX_UPLOAD_BYTES = 10 * 1_048_576


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
    providers = _settings.providers()
    application.state.providers = providers
    application.state.pipeline = TriagePipeline(FallbackRouter(providers), store)
    yield
    if postgres:
        await postgres.close()


app = FastAPI(title="AutoResolve", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=[
        "Content-Type",
        "Authorization",
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


class BatchIngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: int
    rejected: list[RowError]
    jobs: list[JobSubmission]


class PolicyUpdate(BaseModel):
    confidence_threshold: float = Field(ge=0, le=1)
    allowed_providers: set[str] = Field(max_length=20)
    allowed_regions: set[str] = Field(max_length=20)


class Identity(BaseModel):
    tenant_id: str
    roles: frozenset[str]
    subject: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class SessionResponse(BaseModel):
    token: str
    tenant_id: str
    subject: str
    roles: list[str]


class ProviderStatus(BaseModel):
    name: str
    configured_model: str
    reachable: bool
    model_available: bool
    models: list[str]


def identity(
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_roles: Annotated[str | None, Header()] = None,
    x_subject: Annotated[str, Header()] = "local-user",
) -> Identity:
    if _settings.auth_secret:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sign in required")
        try:
            claims = verify_token(_settings.auth_secret, authorization.removeprefix("Bearer "))
            return Identity(
                tenant_id=str(claims["tenant"]),
                roles=frozenset(str(role) for role in claims["roles"]),
                subject=str(claims["sub"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="session expired"
            ) from exc
    if not x_tenant_id or not x_roles:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="identity required")
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
async def health(raw_request: Request) -> dict[str, str]:
    store: StateStore = raw_request.app.state.store
    try:
        await store.health()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"status": "ok"}


@app.post("/v1/session", response_model=SessionResponse)
async def create_session(credentials: LoginRequest) -> SessionResponse:
    if not _settings.auth_secret or not _settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="authentication unavailable"
        )
    if not (
        secrets.compare_digest(credentials.username, _settings.admin_username)
        and secrets.compare_digest(credentials.password, _settings.admin_password)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    roles = ["admin"]
    return SessionResponse(
        token=issue_token(
            _settings.auth_secret,
            subject=credentials.username,
            tenant_id=_settings.admin_tenant_id,
            roles=roles,
        ),
        tenant_id=_settings.admin_tenant_id,
        subject=credentials.username,
        roles=roles,
    )


async def _provider_status(provider: OpenAICompatibleProvider) -> ProviderStatus:
    try:
        models = await provider.available_models()
    except ProviderError:
        models = []
    return ProviderStatus(
        name=provider.name,
        configured_model=provider.model,
        reachable=bool(models),
        model_available=provider.model in models,
        models=models,
    )


@app.get("/v1/providers", response_model=list[ProviderStatus])
async def list_providers(
    raw_request: Request, principal: Annotated[Identity, Depends(identity)]
) -> list[ProviderStatus]:
    require_role(principal, "policy:read")
    providers: list[OpenAICompatibleProvider] = raw_request.app.state.providers
    return list(await asyncio.gather(*(_provider_status(provider) for provider in providers)))


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


@app.post(
    "/v1/triage/batch",
    response_model=BatchIngestResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_batch(
    raw_request: Request,
    principal: Annotated[Identity, Depends(identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
    x_correlation_id: Annotated[
        str, Header(alias="X-Correlation-ID", min_length=8, max_length=200)
    ],
    file: Annotated[UploadFile, File()],
) -> BatchIngestResult:
    """Enqueue one triage job per row of an uploaded CSV or .xlsx sheet."""
    require_role(principal, "triage:write")
    queue: PostgresJobQueue | None = getattr(raw_request.app.state, "jobs", None)
    if queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="durable queue unavailable",
        )

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds {MAX_UPLOAD_BYTES // 1_048_576} MiB",
        )
    try:
        sheet = parse_tickets(data, file.filename or "", tenant_id=principal.tenant_id)
    except SheetFormatError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    policy = await policy_for(raw_request.app.state.store, principal)
    jobs: list[JobSubmission] = []
    for ticket in sheet.tickets:
        payload = JobPayload(
            ticket=ticket,
            correlation_id=x_correlation_id,
            policy=policy,
            knowledge_base=[],
        )
        # Scoping the key by ticket id makes re-uploading the same sheet a no-op.
        jobs.append(
            await queue.enqueue(principal.tenant_id, f"{idempotency_key}:{ticket.id}", payload)
        )
    return BatchIngestResult(accepted=len(jobs), rejected=sheet.errors, jobs=jobs)


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
