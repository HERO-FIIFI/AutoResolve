from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Action(StrEnum):
    RESPOND = "respond"
    ESCALATE = "escalate"


class Ticket(BaseModel):
    id: NonEmpty
    tenant_id: NonEmpty
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000)]
    region: NonEmpty = "unspecified"
    regulated: bool = False


class Citation(BaseModel):
    chunk_id: NonEmpty
    quote: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]


class Decision(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    action: Action
    confidence_score: float = Field(ge=0.0, le=1.0)
    suggested_reply: str | None = Field(default=None, max_length=10_000)
    escalation_reason: str | None = Field(default=None, max_length=2_000)
    cited_sources: list[Citation] = Field(default_factory=list, max_length=25)

    @model_validator(mode="after")
    def validate_action_fields(self) -> Decision:
        if self.action is Action.RESPOND:
            if not self.suggested_reply or not self.suggested_reply.strip():
                raise ValueError("respond decisions require suggested_reply")
            if not self.cited_sources:
                raise ValueError("respond decisions require at least one citation")
            if self.escalation_reason:
                raise ValueError("respond decisions cannot include escalation_reason")
        else:
            if not self.escalation_reason or not self.escalation_reason.strip():
                raise ValueError("escalate decisions require escalation_reason")
            if self.suggested_reply:
                raise ValueError("escalate decisions cannot include suggested_reply")
        return self


class RetrievedChunk(BaseModel):
    id: NonEmpty
    tenant_id: NonEmpty
    kb_version: NonEmpty
    content: NonEmpty
    score: float = Field(ge=0.0)


class TenantPolicy(BaseModel):
    tenant_id: NonEmpty
    confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    allowed_providers: frozenset[str] = frozenset()
    allowed_regions: frozenset[str] = frozenset()


class TenantPolicyRecord(TenantPolicy):
    version: int = Field(ge=1)
    updated_at: datetime


class AuditRecord(BaseModel):
    sequence_id: int = Field(ge=1)
    ticket_id: NonEmpty
    correlation_id: NonEmpty
    event_type: NonEmpty
    occurred_at: datetime
    attributes: dict[str, object] = Field(default_factory=dict)


class PipelineResult(BaseModel):
    ticket_id: NonEmpty
    tenant_id: NonEmpty
    correlation_id: NonEmpty
    decision: Decision
    provider: str | None = None
    verification_errors: list[str] = Field(default_factory=list)
