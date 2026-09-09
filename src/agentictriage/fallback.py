from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from agentictriage.models import Decision, RetrievedChunk, TenantPolicy, Ticket
from agentictriage.providers import ModelProvider, ProviderError


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    clock: Callable[[], float] = time.monotonic
    consecutive_failures: int = 0
    opened_at: float | None = None
    _half_open_probe_active: bool = False

    @property
    def state(self) -> CircuitState:
        if self.opened_at is None:
            return CircuitState.CLOSED
        if self.clock() - self.opened_at >= self.recovery_seconds:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def permit_request(self) -> bool:
        state = self.state
        if state is CircuitState.CLOSED:
            return True
        if state is CircuitState.OPEN or self._half_open_probe_active:
            return False
        self._half_open_probe_active = True
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None
        self._half_open_probe_active = False

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self._half_open_probe_active = False
        if self.consecutive_failures >= self.failure_threshold:
            self.opened_at = self.clock()


class ProvidersExhausted(ProviderError):
    def __init__(self, failures: list[str]) -> None:
        super().__init__("all allowed model providers failed")
        self.failures = failures


@dataclass(frozen=True, slots=True)
class RoutedDecision:
    decision: Decision
    provider: str


@dataclass(slots=True)
class FallbackRouter:
    providers: Sequence[ModelProvider]
    retries_per_provider: int = 1
    initial_backoff_seconds: float = 0.05
    breakers: dict[str, CircuitBreaker] = field(default_factory=dict)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    async def decide(
        self,
        ticket: Ticket,
        chunks: list[RetrievedChunk],
        policy: TenantPolicy,
    ) -> RoutedDecision:
        failures: list[str] = []
        for provider in self.providers:
            if provider.name not in policy.allowed_providers:
                continue
            if policy.allowed_regions and provider.region not in policy.allowed_regions:
                failures.append(f"{provider.name}: region denied")
                continue
            breaker = self.breakers.setdefault(provider.name, CircuitBreaker())
            if not breaker.permit_request():
                failures.append(f"{provider.name}: circuit open")
                continue
            last_error = "unknown provider failure"
            for attempt in range(self.retries_per_provider + 1):
                try:
                    decision = await provider.decide(ticket, chunks)
                    breaker.record_success()
                    return RoutedDecision(decision=decision, provider=provider.name)
                except ProviderError as exc:
                    last_error = str(exc)
                    if attempt < self.retries_per_provider:
                        await self.sleep(self.initial_backoff_seconds * (2**attempt))
            breaker.record_failure()
            failures.append(f"{provider.name}: failed after retries: {last_error}")
        if not failures:
            failures.append("no provider allowed by tenant policy")
        raise ProvidersExhausted(failures)
