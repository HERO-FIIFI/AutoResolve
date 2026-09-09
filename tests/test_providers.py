import asyncio
import json
from typing import Any

from agentictriage.models import RetrievedChunk, Ticket
from agentictriage.providers import lm_studio_provider


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        decision = {
            "schema_version": "1.0",
            "action": "respond",
            "confidence_score": 0.9,
            "suggested_reply": "Use Reset Password.",
            "escalation_reason": None,
            "cited_sources": [{"chunk_id": "c", "quote": "Use Reset Password."}],
        }
        return {"choices": [{"message": {"content": json.dumps(decision)}}]}


class FakeClient:
    last_url: str | None = None
    last_json: dict[str, Any] | None = None

    def __init__(self, *, timeout: float) -> None:
        assert timeout == 4

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self, url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> FakeResponse:
        type(self).last_url = url
        type(self).last_json = json
        assert "Authorization" not in headers
        return FakeResponse()


def test_lm_studio_uses_openai_compatible_endpoint(monkeypatch: Any) -> None:
    monkeypatch.setattr("agentictriage.providers.httpx.AsyncClient", FakeClient)
    provider = lm_studio_provider(
        base_url="http://127.0.0.1:1234/v1/", model="local-test", timeout_seconds=4
    )
    ticket = Ticket(id="t", tenant_id="a", subject="password", body="reset")
    chunks = [
        RetrievedChunk(
            id="c", tenant_id="a", kb_version="1", content="Use Reset Password.", score=1
        )
    ]
    decision = asyncio.run(provider.decide(ticket, chunks))
    assert decision.action == "respond"
    assert FakeClient.last_url == "http://127.0.0.1:1234/v1/chat/completions"
    assert FakeClient.last_json is not None
    assert FakeClient.last_json["model"] == "local-test"
    assert FakeClient.last_json["response_format"]["type"] == "json_schema"
