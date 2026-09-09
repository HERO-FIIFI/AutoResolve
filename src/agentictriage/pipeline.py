from __future__ import annotations

from collections.abc import Sequence

from agentictriage.audit import AuditEvent, AuditSink
from agentictriage.fallback import FallbackRouter, ProvidersExhausted
from agentictriage.ingestion import inspect_and_redact
from agentictriage.models import (
    Action,
    Decision,
    PipelineResult,
    RetrievedChunk,
    TenantPolicy,
    Ticket,
)
from agentictriage.retrieval import rank_chunks
from agentictriage.verification import verify_decision


def escalation(reason: str) -> Decision:
    return Decision(action=Action.ESCALATE, confidence_score=0.0, escalation_reason=reason)


class TriagePipeline:
    def __init__(self, router: FallbackRouter, audit: AuditSink) -> None:
        self._router = router
        self._audit = audit

    async def process(
        self,
        ticket: Ticket,
        *,
        correlation_id: str,
        policy: TenantPolicy,
        knowledge_base: Sequence[RetrievedChunk],
    ) -> PipelineResult:
        if policy.tenant_id != ticket.tenant_id:
            raise ValueError("tenant policy does not belong to ticket tenant")
        guard = inspect_and_redact(ticket)
        await self._event(
            "ingestion.completed",
            ticket,
            correlation_id,
            {"injection_detected": guard.injection_detected, "redactions": guard.redactions},
        )
        if guard.injection_detected:
            return await self._finish(
                ticket, correlation_id, escalation("prompt-injection risk detected")
            )
        chunks = rank_chunks(
            f"{guard.ticket.subject} {guard.ticket.body}",
            knowledge_base,
            tenant_id=ticket.tenant_id,
        )
        await self._event(
            "retrieval.completed",
            ticket,
            correlation_id,
            {"chunk_ids": [chunk.id for chunk in chunks]},
        )
        if not chunks:
            return await self._finish(ticket, correlation_id, escalation("no supporting evidence"))
        try:
            routed = await self._router.decide(guard.ticket, chunks, policy)
        except ProvidersExhausted as exc:
            return await self._finish(
                ticket,
                correlation_id,
                escalation("all allowed model providers unavailable"),
                errors=exc.failures,
            )
        verified = verify_decision(
            routed.decision,
            chunks,
            confidence_threshold=policy.confidence_threshold,
        )
        if not verified.accepted:
            return await self._finish(
                ticket,
                correlation_id,
                escalation("decision failed independent verification"),
                provider=routed.provider,
                errors=list(verified.errors),
            )
        return await self._finish(
            ticket,
            correlation_id,
            routed.decision,
            provider=routed.provider,
        )

    async def _finish(
        self,
        ticket: Ticket,
        correlation_id: str,
        decision: Decision,
        *,
        provider: str | None = None,
        errors: list[str] | None = None,
    ) -> PipelineResult:
        result = PipelineResult(
            ticket_id=ticket.id,
            tenant_id=ticket.tenant_id,
            correlation_id=correlation_id,
            decision=decision,
            provider=provider,
            verification_errors=errors or [],
        )
        await self._event(
            "pipeline.completed",
            ticket,
            correlation_id,
            {"action": decision.action, "provider": provider, "errors": errors or []},
        )
        return result

    async def _event(
        self,
        event_type: str,
        ticket: Ticket,
        correlation_id: str,
        attributes: dict[str, object],
    ) -> None:
        await self._audit.append(
            AuditEvent(
                event_type=event_type,
                tenant_id=ticket.tenant_id,
                ticket_id=ticket.id,
                correlation_id=correlation_id,
                attributes=attributes,
            )
        )
