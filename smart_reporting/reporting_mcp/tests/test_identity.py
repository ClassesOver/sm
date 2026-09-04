import base64
import hashlib
import hmac
import json

import pytest

from smart_reporting.reporting_mcp.identity import (
    CapabilityTokenVerifier,
    McpRequestIdentity,
)


def _segment(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _token(secret: str, *, thread: str = "thread-1", now: int = 1_800_000_000) -> str:
    header = _segment({"alg": "HS256", "typ": "WORKSPACE-CAP"})
    claims = _segment(
        {
            "aud": "agentos-workspace",
            "iat": now,
            "exp": now + 300,
            "database": "odoo",
            "user": 7,
            "company": 11,
            "odoo_session": "a" * 64,
            "thread": thread,
        }
    )
    payload = f"{header}.{claims}"
    signature = (
        base64.urlsafe_b64encode(
            hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        )
        .decode()
        .rstrip("=")
    )
    return f"{payload}.{signature}"


@pytest.mark.anyio
async def test_capability_verifier_returns_tenant_claims() -> None:
    secret = "s" * 32
    verifier = CapabilityTokenVerifier(secret, clock=lambda: 1_800_000_000)

    access_token = await verifier.verify_token(_token(secret))

    assert access_token is not None
    assert access_token.claims["thread"] == "thread-1"
    assert access_token.claims["database"] == "odoo"
    assert access_token.claims["company"] == 11
    assert access_token.claims["user"] == 7
    assert "odoo_session" not in access_token.claims


@pytest.mark.anyio
async def test_capability_verifier_rejects_expired_token() -> None:
    secret = "s" * 32
    verifier = CapabilityTokenVerifier(secret, clock=lambda: 1_800_001_000)

    assert await verifier.verify_token(_token(secret)) is None


def test_request_identity_rejects_cross_thread() -> None:
    identity = McpRequestIdentity(
        database="odoo",
        user_id="7",
        company_id="11",
        thread_id="thread-1",
    )

    with pytest.raises(ValueError, match="thread"):
        identity.require_thread("thread-2")
