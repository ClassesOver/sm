import base64
import hashlib
import hmac
import json

import pytest

from smart_reporting.http.security import CapabilityError, verify_capability

SECRET = "0123456789abcdef0123456789abcdef"


def encode(claims, secret=SECRET):
    header = {"alg": "HS256", "typ": "WORKSPACE-CAP"}

    def segment(value):
        return (
            base64.urlsafe_b64encode(
                json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            )
            .rstrip(b"=")
            .decode()
        )

    value = f"{segment(header)}.{segment(claims)}"
    signature = (
        base64.urlsafe_b64encode(hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest())
        .rstrip(b"=")
        .decode()
    )
    return f"{value}.{signature}"


def claims(**overrides):
    value = {
        "aud": "agentos-workspace",
        "database": "odoo",
        "user": 7,
        "company": 3,
        "odoo_session": "a" * 64,
        "thread": "thread-1",
        "iat": 1000,
        "exp": 1600,
        "jti": "id",
    }
    value.update(overrides)
    return value


def test_capability_is_bound_to_identity_thread_and_ten_minute_ttl():
    verified = verify_capability(encode(claims()), SECRET, "thread-1", now=1200)
    assert (verified.database, verified.user, verified.company) == ("odoo", 7, 3)
    assert verified.thread == "thread-1"

    with pytest.raises(CapabilityError, match="thread_mismatch"):
        verify_capability(encode(claims()), SECRET, "thread-2", now=1200)
    with pytest.raises(CapabilityError, match="time_invalid"):
        verify_capability(encode(claims(exp=1601)), SECRET, "thread-1", now=1200)


def test_capability_rejects_tampering_expiry_and_invalid_identity():
    token = encode(claims())
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload[:-1]}A.{signature}"
    with pytest.raises(CapabilityError, match="signature_invalid"):
        verify_capability(tampered, SECRET, "thread-1", now=1200)
    with pytest.raises(CapabilityError, match="expired"):
        verify_capability(token, SECRET, "thread-1", now=1600)
    with pytest.raises(CapabilityError, match="identity_invalid"):
        verify_capability(
            encode(claims(user="7")),
            SECRET,
            "thread-1",
            now=1200,
        )
