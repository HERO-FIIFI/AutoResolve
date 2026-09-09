from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_type: str
    tenant_id: str
    ticket_id: str
    correlation_id: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    attributes: dict[str, Any] = field(default_factory=dict)


class AuditSink(Protocol):
    async def append(self, event: AuditEvent) -> None: ...


@dataclass(slots=True)
class InMemoryAuditSink:
    """Test/local sink only; production must use an access-controlled append-only backend."""

    events: list[AuditEvent] = field(default_factory=list)

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)
