from agentictriage.models import Action, Decision, PipelineResult
from agentictriage.storage import _result


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
