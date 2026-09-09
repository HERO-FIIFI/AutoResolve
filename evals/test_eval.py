import json
from pathlib import Path

from agentictriage.ingestion import inspect_and_redact
from agentictriage.models import Action, Ticket
from agentictriage.pipeline import escalation


def test_adversarial_fixture_gate() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "adversarial.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    passed = 0
    for case in cases:
        ticket = Ticket(
            id=case["id"],
            tenant_id="eval-tenant",
            subject=case["subject"],
            body=case["body"],
        )
        guard = inspect_and_redact(ticket)
        actual = escalation("prompt-injection risk detected") if guard.injection_detected else None
        if actual and actual.action is Action(case["expected_action"]):
            passed += 1
    assert passed / len(cases) >= 1.0
