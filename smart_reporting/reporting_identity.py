"""当前 Reporting HTTP 请求中经过验证的 Odoo 调用方身份。"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReportServerIdentity:
    database: str
    user_id: str
    company_id: str
    session_id: str
    thread_id: str


_CURRENT_IDENTITY: ContextVar[ReportServerIdentity | None] = ContextVar(
    "report_server_identity", default=None
)


def requires_workspace_capability(path: str, *, has_thread: bool, has_capability: bool) -> bool:
    normalized = str(path or "").rstrip("/") or "/"
    if normalized.startswith("/reports/v1/download/"):
        return False
    protected_resource = normalized.startswith("/workspace")
    # 通用 AgentOS Console 只提供原生 user_id/session_id，不能生成 Odoo capability。
    # 两个扩展头均缺失时允许普通 run；访问受保护资源或任一扩展头已经出现时，
    # 必须进入完整验签流程，禁止用默认身份或部分请求头静默降级。
    return protected_resource or has_thread or has_capability


def apply_report_identity(request: Any, identity: ReportServerIdentity) -> None:
    """把已验签身份交给 AgentOS，覆盖客户端提交的 run 作用域。"""
    request.state.user_id = identity.user_id
    request.state.session_id = identity.thread_id


@contextmanager
def bind_report_identity(identity: ReportServerIdentity) -> Iterator[None]:
    token = _CURRENT_IDENTITY.set(identity)
    try:
        yield
    finally:
        _CURRENT_IDENTITY.reset(token)


def current_report_identity() -> ReportServerIdentity | None:
    return _CURRENT_IDENTITY.get()
