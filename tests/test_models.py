import pytest
from pydantic import ValidationError

from agentictriage.jobs import JobReview
from agentictriage.models import Action, Citation, Decision


def test_valid_respond_decision() -> None:
    value = Decision(
        action=Action.RESPOND,
        confidence_score=0.91,
        suggested_reply="Reset the token.",
        cited_sources=[Citation(chunk_id="kb-1", quote="Reset the token")],
    )
    assert value.action is Action.RESPOND


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "respond", "confidence_score": 0.9, "suggested_reply": "answer"},
        {"action": "escalate", "confidence_score": 0.1},
        {
            "action": "respond",
            "confidence_score": 1.1,
            "suggested_reply": "answer",
            "cited_sources": [{"chunk_id": "a", "quote": "q"}],
        },
    ],
)
def test_invalid_decisions_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Decision.model_validate(payload)


def test_approved_review_requires_operator_response() -> None:
    with pytest.raises(ValidationError):
        JobReview(action="approve_response")
