import asyncio

from agentictriage.models import Action, Decision, PipelineResult, TenantPolicy
from agentictriage.storage import MemoryStateStore, _result


def test_postgres_json_text_is_deserialized() -> None:
    expected = PipelineResult(
        ticket_id="ticket-1",
        tenant_id="tenant-1",
        correlation_id="correlation-1",
        decision=Decision(
            action=Action.ESCALATE,
            confidence_score=0,
            escalation_reason="provider unavailable",
        ),
    )
    assert _result(expected.model_dump_json()) == expected


def test_memory_policy_updates_are_versioned() -> None:
    store = MemoryStateStore()
    first = asyncio.run(store.get_policy("tenant-1"))
    second = asyncio.run(store.put_policy(TenantPolicy(tenant_id="tenant-1")))
    assert first is not None
    assert second.version == first.version + 1
