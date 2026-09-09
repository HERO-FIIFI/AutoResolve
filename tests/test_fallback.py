import asyncio
from dataclasses import dataclass

import pytest

from agentictriage.fallback import CircuitBreaker, CircuitState, FallbackRouter, ProvidersExhausted
from agentictriage.models import Citation, Decision, RetrievedChunk, TenantPolicy, Ticket
from agentictriage.providers import ProviderError


@dataclass
class FakeProvider:
    name: str
    outcomes: list[Decision | Exception]
    region: str = "eu"
    calls: int = 0

    async def decide(self, ticket: Ticket, chunks: list[RetrievedChunk]) -> Decision:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def fixtures() -> tuple[Ticket, list[RetrievedChunk], TenantPolicy, Decision]:
    ticket = Ticket(id="t", tenant_id="a", subject="reset", body="password reset")
    chunks = [
        RetrievedChunk(
            id="c", tenant_id="a", kb_version="1", content="Reset the password.", score=1
        )
    ]
    policy = TenantPolicy(
        tenant_id="a",
        allowed_providers=frozenset({"primary", "secondary"}),
        allowed_regions=frozenset({"eu"}),
    )
    decision = Decision(
        action="respond",
        confidence_score=0.9,
        suggested_reply="Reset it.",
        cited_sources=[Citation(chunk_id="c", quote="Reset the password.")],
    )
    return ticket, chunks, policy, decision


def test_falls_back_after_primary_failure() -> None:
    ticket, chunks, policy, decision = fixtures()
    primary = FakeProvider("primary", [ProviderError("down")])
    secondary = FakeProvider("secondary", [decision])
    router = FallbackRouter([primary, secondary], retries_per_provider=0)
    result = asyncio.run(router.decide(ticket, chunks, policy))
    assert result.provider == "secondary"


def test_exhaustion_is_explicit() -> None:
    ticket, chunks, policy, _ = fixtures()
    router = FallbackRouter(
        [
            FakeProvider("primary", [ProviderError("down")]),
            FakeProvider("secondary", [ProviderError("down")]),
        ],
        retries_per_provider=0,
    )
    with pytest.raises(ProvidersExhausted):
        asyncio.run(router.decide(ticket, chunks, policy))


def test_circuit_transitions_to_half_open_and_recovers() -> None:
    now = [10.0]
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=5, clock=lambda: now[0])
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    assert not breaker.permit_request()
    now[0] = 15.0
    assert breaker.state is CircuitState.HALF_OPEN
    assert breaker.permit_request()
    assert not breaker.permit_request()
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED
