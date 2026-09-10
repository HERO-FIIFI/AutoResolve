import time

import pytest

from agentictriage.auth import issue_token, verify_token


def test_signed_session_rejects_tampering_and_expiry() -> None:
    token = issue_token("secret", subject="operator", tenant_id="example", roles=["admin"])
    assert verify_token("secret", token)["tenant"] == "example"
    with pytest.raises(ValueError):
        verify_token("secret", token + "changed")
    expired = issue_token(
        "secret", subject="operator", tenant_id="example", roles=["admin"], lifetime_seconds=-1
    )
    time.sleep(0.01)
    with pytest.raises(ValueError):
        verify_token("secret", expired)
