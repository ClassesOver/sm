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


def _signed_token(secret: str, header: object, claims: object) -> str:
    payload = f"{_segment(header)}.{_segment(claims)}"
    signature = (
        base64.urlsafe_b64encode(
            hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        )
        .decode()
        .rstrip("=")
    )
    return f"{payload}.{signature}"


def _dsh_token(
    secret: str,
    *,
    now: int = 1_800_000_000,
    header_override: dict[str, object] | None = None,
    claims_override: dict[str, object] | None = None,
) -> str:
    header: dict[str, object] = {"alg": "HS256", "typ": "DSH-REPORTING"}
    header.update(header_override or {})
    claims: dict[str, object] = {
        "iss": "dsh",
        "aud": "smart-reporting-mcp",
        "sub": "session-1",
        "thread": "session-1",
        "database": "dsh",
        "company": "default",
        "iat": now,
        "exp": now + 300,
        "ver": 1,
    }
    claims.update(claims_override or {})
    return _signed_token(secret, header, claims)


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


@pytest.mark.anyio
async def test_dsh_verifier_returns_session_identity() -> None:
    secret = "s" * 32
    verifier = CapabilityTokenVerifier(secret, clock=lambda: 1_800_000_000)

    access_token = await verifier.verify_token(_dsh_token(secret))

    assert access_token is not None
    assert access_token.client_id == "dsh:session-1"
    assert access_token.subject == "session-1"
    assert access_token.expires_at == 1_800_000_300
    assert access_token.claims == {
        "sub": "session-1",
        "database": "dsh",
        "user": "session-1",
        "company": "default",
        "thread": "session-1",
    }


@pytest.mark.parametrize(
    ("claims_override", "clock"),
    [
        ({"exp": 1_800_000_000}, 1_800_000_000),
        ({"iat": 1_800_000_001}, 1_800_000_000),
        ({"exp": 1_800_000_301}, 1_800_000_000),
        ({"iss": "other"}, 1_800_000_000),
        ({"aud": "other"}, 1_800_000_000),
        ({"ver": 2}, 1_800_000_000),
        ({"ver": True}, 1_800_000_000),
        ({"database": "odoo"}, 1_800_000_000),
        ({"company": "other"}, 1_800_000_000),
        ({"sub": ""}, 1_800_000_000),
        ({"thread": ""}, 1_800_000_000),
        ({"sub": "session-2"}, 1_800_000_000),
    ],
)
@pytest.mark.anyio
async def test_dsh_verifier_rejects_invalid_protocol_claims(
    claims_override: dict[str, object], clock: int
) -> None:
    secret = "s" * 32
    verifier = CapabilityTokenVerifier(secret, clock=lambda: clock)

    assert await verifier.verify_token(_dsh_token(secret, claims_override=claims_override)) is None


@pytest.mark.anyio
async def test_dsh_verifier_rejects_invalid_header_and_signature() -> None:
    secret = "s" * 32
    verifier = CapabilityTokenVerifier(secret, clock=lambda: 1_800_000_000)
    wrong_header = _dsh_token(secret, header_override={"typ": "WORKSPACE-CAP"})
    wrong_signature = _dsh_token("x" * 32)

    assert await verifier.verify_token(wrong_header) is None
    assert await verifier.verify_token(wrong_signature) is None


@pytest.mark.anyio
async def test_dsh_verifier_rejects_non_object_claims() -> None:
    secret = "s" * 32
    verifier = CapabilityTokenVerifier(secret, clock=lambda: 1_800_000_000)
    token = _signed_token(
        secret,
        {"alg": "HS256", "typ": "DSH-REPORTING"},
        [],
    )

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_dsh_header_never_falls_back_to_workspace_capability() -> None:
    secret = "s" * 32
    verifier = CapabilityTokenVerifier(secret, clock=lambda: 1_800_000_000)
    odoo_claims = {
        "aud": "agentos-workspace",
        "database": "odoo",
        "user": 7,
        "company": 11,
        "odoo_session": "a" * 64,
        "thread": "session-1",
    }

    assert await verifier.verify_token(_dsh_token(secret, claims_override=odoo_claims)) is None


def test_request_identity_rejects_cross_thread() -> None:
    identity = McpRequestIdentity(
        database="odoo",
        user_id="7",
        company_id="11",
        thread_id="thread-1",
    )

    with pytest.raises(ValueError, match="thread"):
        identity.require_thread("thread-2")


@pytest.mark.anyio
@pytest.mark.parametrize("claims", [[], 7, "thread-1"])
async def test_capability_verifier_rejects_non_object_claims_without_crashing(
    claims: object,
) -> None:
    secret = "s" * 32
    verifier = CapabilityTokenVerifier(secret, clock=lambda: 1_800_000_000)

    unsigned = f"{_segment({'alg': 'HS256', 'typ': 'WORKSPACE-CAP'})}.{_segment(claims)}.x"
    signed = _signed_token(secret, {"alg": "HS256", "typ": "WORKSPACE-CAP"}, claims)

    assert await verifier.verify_token(unsigned) is None
    assert await verifier.verify_token(signed) is None
