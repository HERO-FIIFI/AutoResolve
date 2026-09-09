from __future__ import annotations

from dataclasses import dataclass

from agentictriage.models import Action, Decision, RetrievedChunk


@dataclass(frozen=True, slots=True)
class VerificationResult:
    accepted: bool
    errors: tuple[str, ...] = ()


def verify_decision(
    decision: Decision,
    chunks: list[RetrievedChunk],
    *,
    confidence_threshold: float,
) -> VerificationResult:
    if decision.action is Action.ESCALATE:
        return VerificationResult(accepted=True)
    errors: list[str] = []
    if decision.confidence_score < confidence_threshold:
        errors.append("confidence below tenant threshold")
    by_id = {chunk.id: chunk for chunk in chunks}
    for citation in decision.cited_sources:
        chunk = by_id.get(citation.chunk_id)
        if chunk is None:
            errors.append(f"unknown citation: {citation.chunk_id}")
        elif citation.quote not in chunk.content:
            errors.append(f"citation quote not found: {citation.chunk_id}")
    return VerificationResult(accepted=not errors, errors=tuple(errors))
