import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any


CAPABILITY_AUDIENCE = "agui-agentos-workspace"
MAX_CAPABILITY_TTL = 10 * 60


class CapabilityError(ValueError):
    pass


def _decode_segment(value: str) -> bytes:
    try:
        raw = value.encode("ascii")
        return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))
    except (UnicodeEncodeError, ValueError) as error:
        raise CapabilityError("capability_invalid") from error


@dataclass(frozen=True)
class CapabilityClaims:
    database: str
    user: int
    company: int
    odoo_session: str
    thread: str
    issued_at: int
    expires_at: int


def verify_capability(
    token: str,
    secret: str,
    expected_thread: str,
    now: int | None = None,
) -> CapabilityClaims:
    if len(secret.encode("utf-8")) < 32:
        raise CapabilityError("capability_secret_invalid")
    try:
        header_value, claims_value, signature_value = str(token or "").split(".")
        signing_input = f"{header_value}.{claims_value}"
        expected = hmac.new(
            secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _decode_segment(signature_value)):
            raise CapabilityError("capability_signature_invalid")
        header = json.loads(_decode_segment(header_value))
        claims: dict[str, Any] = json.loads(_decode_segment(claims_value))
    except CapabilityError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise CapabilityError("capability_invalid") from error

    if header != {"alg": "HS256", "typ": "AGUI-CAP"}:
        raise CapabilityError("capability_header_invalid")
    if claims.get("aud") != CAPABILITY_AUDIENCE:
        raise CapabilityError("capability_audience_invalid")
    current = int(time.time() if now is None else now)
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if not isinstance(issued_at, int) or not isinstance(expires_at, int):
        raise CapabilityError("capability_time_invalid")
    if expires_at <= current:
        raise CapabilityError("capability_expired")
    if issued_at > current + 30 or expires_at - issued_at > MAX_CAPABILITY_TTL:
        raise CapabilityError("capability_time_invalid")
    if claims.get("thread") != expected_thread or not expected_thread:
        raise CapabilityError("capability_thread_mismatch")
    database = claims.get("database")
    user = claims.get("user")
    company = claims.get("company")
    odoo_session = claims.get("odoo_session")
    if not isinstance(database, str) or not database:
        raise CapabilityError("capability_identity_invalid")
    if not isinstance(user, int) or not isinstance(company, int):
        raise CapabilityError("capability_identity_invalid")
    if (
        not isinstance(odoo_session, str)
        or len(odoo_session) != 64
        or any(char not in "0123456789abcdef" for char in odoo_session)
    ):
        raise CapabilityError("capability_identity_invalid")
    return CapabilityClaims(
        database=database,
        user=user,
        company=company,
        odoo_session=odoo_session,
        thread=expected_thread,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def thread_label(thread: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), thread.encode("utf-8"), hashlib.sha256
    ).hexdigest()
