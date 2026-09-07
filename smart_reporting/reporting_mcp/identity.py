from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from ..http.security import CapabilityError, verify_capability
from ..reporting.models import ReportingError


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


class CapabilityTokenVerifier(TokenVerifier):
    """通过 AgentOS mcp_auth 验证 Reporting workspace capability。"""

    def __init__(self, secret: str, *, clock: Callable[[], float] = time.time) -> None:
        super().__init__()
        self._secret = secret
        self._clock = clock

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            thread = _unverified_thread(token)
            claims = verify_capability(
                token,
                self._secret,
                thread,
                now=int(self._clock()),
            )
        except CapabilityError:
            return None
        return AccessToken(
            token=token,
            client_id=f"{claims.database}:{claims.user}",
            subject=str(claims.user),
            scopes=["reporting"],
            expires_at=claims.expires_at,
            claims={
                "sub": str(claims.user),
                "database": claims.database,
                "user": claims.user,
                "company": claims.company,
                "thread": claims.thread,
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
        or not isinstance(user, int)
        or not isinstance(company, int)
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


def _unverified_thread(token: str) -> str:
    """只提取待验签 token 的 thread，用作完整 verify_capability 的预期值。"""

    try:
        _header, payload, _signature = str(token or "").split(".")
        raw = payload.encode("ascii")
        decoded = base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))
        value = json.loads(decoded)
        thread = value.get("thread")
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise CapabilityError("capability_invalid") from error
    if not isinstance(thread, str) or not thread:
        raise CapabilityError("capability_thread_mismatch")
    return thread
