from agentictriage.models import RetrievedChunk
from agentictriage.retrieval import rank_chunks


def test_retrieval_enforces_tenant_scope() -> None:
    chunks = [
        RetrievedChunk(id="own", tenant_id="a", kb_version="1", content="reset password", score=0),
        RetrievedChunk(
            id="other", tenant_id="b", kb_version="1", content="reset password", score=0
        ),
    ]
    assert [item.id for item in rank_chunks("password", chunks, tenant_id="a")] == ["own"]
