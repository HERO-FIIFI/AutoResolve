from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import TypedDict


class SessionClaims(TypedDict):
    sub: str
    tenant: str
    roles: list[str]
    exp: int


def issue_token(
    secret: str, *, subject: str, tenant_id: str, roles: list[str], lifetime_seconds: int = 28_800
) -> str:
    payload = _encode(
        json.dumps(
            {
                "sub": subject,
                "tenant": tenant_id,
                "roles": roles,
                "exp": int(time.time()) + lifetime_seconds,
            },
            separators=(",", ":"),
        ).encode()
    )
    signature = _encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_token(secret: str, token: str) -> SessionClaims:
    try:
        payload, supplied_signature = token.split(".", 1)
        expected = _encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied_signature, expected):
            raise ValueError("invalid signature")
        raw: object = json.loads(_decode(payload))
        if not isinstance(raw, dict):
            raise ValueError("invalid claims")
        subject = raw.get("sub")
        tenant = raw.get("tenant")
        roles = raw.get("roles")
        expires_at = raw.get("exp")
        if not (
            isinstance(subject, str)
            and isinstance(tenant, str)
            and isinstance(roles, list)
            and all(isinstance(role, str) for role in roles)
            and isinstance(expires_at, int)
        ):
            raise ValueError("invalid claims")
        if expires_at < int(time.time()):
            raise ValueError("expired token")
        return {"sub": subject, "tenant": tenant, "roles": roles, "exp": expires_at}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid session") from exc


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
