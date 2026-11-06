"""仅在已核验的服务端入口绑定报告身份；不从 JSON/dependencies 读取可信标记。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from fastmcp.server.dependencies import get_access_token

from ..models import ReportingError


@dataclass(frozen=True)
class VerifiedReportingIdentity:
    database: str
    company_id: str
    user_id: str
    thread_id: str
    entrypoint: Literal["http-capability", "mcp", "cli"]

    def require_scope(self, database: str, company_id: str, user_id: str, thread_id: str) -> None:
        if (database, company_id, user_id, thread_id) != (
            self.database,
            self.company_id,
            self.user_id,
            self.thread_id,
        ):
            raise ReportingError(
                "report_workflow_scope_mismatch", "报告作用域与已核验入口身份不一致。"
            )


_VERIFIED_IDENTITY: ContextVar[VerifiedReportingIdentity | None] = ContextVar(
    "reporting_verified_identity",
    default=None,
)


@contextmanager
def bind_verified_reporting_identity(identity: VerifiedReportingIdentity):
    """供验签后的 HTTP 中间件/主机 CLI 调用，不注册为 API 或模型工具。"""
    values = (identity.database, identity.company_id, identity.user_id, identity.thread_id)
    if any(not value or len(value) > 256 for value in values):
        raise ReportingError("report_verified_identity_required", "缺少已核验的报告入口身份。")
    token = _VERIFIED_IDENTITY.set(identity)
    try:
        yield identity
    finally:
        _VERIFIED_IDENTITY.reset(token)


def require_verified_reporting_identity() -> VerifiedReportingIdentity:
    identity = _VERIFIED_IDENTITY.get()
    if identity is not None:
        return identity
    # FastMCP 只在通过 TokenVerifier 的请求上下文中提供此 token。
    token = get_access_token()
    claims = token.claims if token is not None and isinstance(token.claims, dict) else {}
    values = (
        claims.get("database"),
        claims.get("company"),
        claims.get("user"),
        claims.get("thread"),
    )
    if any(
        not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value)
        for value in values
    ):
        raise ReportingError("report_verified_identity_required", "缺少已核验的报告入口身份。")
    database, company, user, thread = (str(value) for value in values)
    return VerifiedReportingIdentity(database, company, user, thread, "mcp")
