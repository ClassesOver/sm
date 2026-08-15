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


def is_report_run_path(path: str) -> bool:
    normalized = str(path or "").rstrip("/") or "/"
    return normalized == "/agents/report-agent/runs" or normalized.startswith(
        "/agents/report-agent/runs/"
    )


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
