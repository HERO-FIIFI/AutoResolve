from agentictriage.models import Citation, Decision, RetrievedChunk
from agentictriage.verification import verify_decision


def test_rejects_invented_quote() -> None:
    chunks = [
        RetrievedChunk(
            id="kb-1", tenant_id="a", kb_version="1", content="Reset links expire.", score=1
        )
    ]
    decision = Decision(
        action="respond",
        confidence_score=0.95,
        suggested_reply="It lasts one hour.",
        cited_sources=[Citation(chunk_id="kb-1", quote="links last one hour")],
    )
    result = verify_decision(decision, chunks, confidence_threshold=0.8)
    assert not result.accepted
    assert result.errors == ("citation quote not found: kb-1",)
