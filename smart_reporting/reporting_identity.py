"""Reporting HTTP 请求的 capability 保护与 AgentOS 身份覆盖。"""

from typing import Any

from .reporting.workflow.controller import REPORT_WORKFLOW_SCOPE_DEPENDENCY


def requires_workspace_capability(path: str, *, has_thread: bool, has_capability: bool) -> bool:
    normalized = str(path or "").rstrip("/") or "/"
    if normalized.startswith("/reports/v1/download/"):
        return False
    protected_resource = normalized.startswith(("/workspace", "/quality-warnings"))
    # 通用 AgentOS Console 只提供原生 user_id/session_id，不能生成 Odoo capability。
    # 两个扩展头均缺失时允许普通 run；访问受保护资源或任一扩展头已经出现时，
    # 必须进入完整验签流程，禁止用默认身份或部分请求头静默降级。
    return protected_resource or has_thread or has_capability


def apply_report_identity(
    request: Any,
    *,
    user_id: str,
    thread_id: str,
    database: str,
    company_id: str,
) -> None:
    """把已验签身份和租户边界交给 AgentOS，覆盖客户端提交的同名字段。"""
    request.state.user_id = user_id
    request.state.session_id = thread_id
    request.state.dependencies = {
        REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
            "database": database,
            "companyId": company_id,
        }
    }
