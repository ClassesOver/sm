from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from ..http.security import CapabilityError, verify_capability
from ..reporting.models import ReportingError

DSH_REPORTING_AUDIENCE = "smart-reporting-mcp"
DSH_REPORTING_ISSUER = "dsh"
DSH_REPORTING_MAX_TTL = 5 * 60


@dataclass(frozen=True)
class McpRequestIdentity:
    database: str
    user_id: str
    company_id: str
    thread_id: str

    def require_thread(self, thread_id: str) -> None:
        if not thread_id or thread_id != self.thread_id:
            raise ReportingError(
                "report_mcp_thread_mismatch",
                "MCP 请求的 threadId 与 capability 不一致。",
            )


@dataclass(frozen=True)
class DshReportingClaims:
    subject: str
    thread: str
    issued_at: int
    expires_at: int


class CapabilityTokenVerifier(TokenVerifier):
    """通过 AgentOS mcp_auth 验证 Reporting workspace capability。"""

    def __init__(self, secret: str, *, clock: Callable[[], float] = time.time) -> None:
        super().__init__()
        self._secret = secret
        self._clock = clock

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            header = _unverified_header(token)
            if header == {"alg": "HS256", "typ": "WORKSPACE-CAP"}:
                thread = _unverified_thread(token)
                claims = verify_capability(
                    token,
                    self._secret,
                    thread,
                    now=int(self._clock()),
                )
                database = claims.database
                user: int | str = claims.user
                company: int | str = claims.company
                expires_at = claims.expires_at
            elif header == {"alg": "HS256", "typ": "DSH-REPORTING"}:
                dsh_claims = verify_dsh_reporting_token(
                    token,
                    self._secret,
                    now=int(self._clock()),
                )
                thread = dsh_claims.thread
                database = "dsh"
                user = dsh_claims.subject
                company = "default"
                expires_at = dsh_claims.expires_at
            else:
                return None
        except CapabilityError:
            return None
        return AccessToken(
            token=token,
            client_id=f"{database}:{user}",
            subject=str(user),
            scopes=["workflows:enterprise-reporting-workflow-v1:run"],
            expires_at=expires_at,
            claims={
                "sub": str(user),
                "database": database,
                "user": user,
                "company": company,
                "thread": thread,
            },
        )


def require_mcp_identity(thread_id: str) -> McpRequestIdentity:
    token = get_access_token()
    claims: dict[str, Any] = token.claims if token is not None else {}
    database = claims.get("database")
    user = claims.get("user")
    company = claims.get("company")
    token_thread = claims.get("thread")
    if (
        not isinstance(database, str)
        or not database
        or not _valid_identity_value(user)
        or not _valid_identity_value(company)
        or not isinstance(token_thread, str)
        or not token_thread
    ):
        raise ReportingError("report_mcp_unauthorized", "MCP capability 身份无效。")
    identity = McpRequestIdentity(
        database=database,
        user_id=str(user),
        company_id=str(company),
        thread_id=token_thread,
    )
    identity.require_thread(thread_id)
    return identity


def verify_dsh_reporting_token(
    token: str,
    secret: str,
    *,
    now: int,
) -> DshReportingClaims:
    if len(secret.encode("utf-8")) < 32:
        raise CapabilityError("dsh_reporting_secret_invalid")
    try:
        header_value, claims_value, signature_value = str(token or "").split(".")
        signing_input = f"{header_value}.{claims_value}"
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected_signature, _decode_segment(signature_value)):
            raise CapabilityError("dsh_reporting_signature_invalid")
        header = json.loads(_decode_segment(header_value))
        claims: dict[str, Any] = json.loads(_decode_segment(claims_value))
    except CapabilityError:
        raise
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise CapabilityError("dsh_reporting_invalid") from error

    if header != {"alg": "HS256", "typ": "DSH-REPORTING"}:
        raise CapabilityError("dsh_reporting_header_invalid")
    if not isinstance(claims, dict):
        raise CapabilityError("dsh_reporting_invalid")
    if claims.get("iss") != DSH_REPORTING_ISSUER:
        raise CapabilityError("dsh_reporting_issuer_invalid")
    if claims.get("aud") != DSH_REPORTING_AUDIENCE:
        raise CapabilityError("dsh_reporting_audience_invalid")
    if type(claims.get("ver")) is not int or claims["ver"] != 1:
        raise CapabilityError("dsh_reporting_version_invalid")
    if claims.get("database") != "dsh" or claims.get("company") != "default":
        raise CapabilityError("dsh_reporting_tenant_invalid")

    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if type(issued_at) is not int or type(expires_at) is not int:
        raise CapabilityError("dsh_reporting_time_invalid")
    if expires_at <= now:
        raise CapabilityError("dsh_reporting_expired")
    if issued_at > now or expires_at <= issued_at or expires_at - issued_at > DSH_REPORTING_MAX_TTL:
        raise CapabilityError("dsh_reporting_time_invalid")

    subject = claims.get("sub")
    thread = claims.get("thread")
    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(thread, str)
        or not thread
        or subject != thread
    ):
        raise CapabilityError("dsh_reporting_identity_invalid")
    return DshReportingClaims(
        subject=subject,
        thread=thread,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _valid_identity_value(value: object) -> bool:
    return (type(value) is int) or (isinstance(value, str) and bool(value))


def _decode_segment(value: str) -> bytes:
    try:
        raw = value.encode("ascii")
        return base64.b64decode(
            raw + b"=" * (-len(raw) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeError, ValueError) as error:
        raise CapabilityError("dsh_reporting_invalid") from error


def _unverified_header(token: str) -> dict[str, Any]:
    try:
        header, _payload, _signature = str(token or "").split(".")
        value = json.loads(_decode_segment(header))
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise CapabilityError("capability_invalid") from error
    if not isinstance(value, dict):
        raise CapabilityError("capability_invalid")
    return value


def _unverified_thread(token: str) -> str:
    """只提取待验签 token 的 thread，用作完整 verify_capability 的预期值。"""

    try:
        _header, payload, _signature = str(token or "").split(".")
        value = json.loads(_decode_segment(payload))
        thread = value.get("thread")
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise CapabilityError("capability_invalid") from error
    if not isinstance(thread, str) or not thread:
        raise CapabilityError("capability_thread_mismatch")
    return thread
