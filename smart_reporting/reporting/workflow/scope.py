"""Reporting Workflow 的租户、thread 与运行环境作用域。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from fastmcp.server.dependencies import get_access_token

from ..models import ReportingError

REPORT_WORKFLOW_SCOPE_DEPENDENCY = "AgentOS 报表工作流"
REPORT_WORKFLOW_ENTRYPOINT_DEPENDENCY = "Reporting Workflow 入口"
REPORT_WORKFLOW_ENTRYPOINT_STATE_KEY = "report_workflow_entrypoint"


@dataclass(frozen=True)
class ReportingScopeKeys:
    thread_lease_key: str
    workspace_key: str


@dataclass(frozen=True)
class ReportingWorkflowScope:
    run_id: str
    session_id: str
    user_id: str
    database: str
    company_id: str
    thread_lease_key: str
    workspace_key: str

    def as_state(self) -> dict[str, str]:
        return {
            "externalRunId": self.run_id,
            "sessionId": self.session_id,
            "threadId": self.workspace_key,
            "userId": self.user_id,
            "database": self.database,
            "companyId": self.company_id,
            "threadLeaseKey": self.thread_lease_key,
        }


def _scope_digest(kind: str, values: tuple[str, ...]) -> str:
    payload = json.dumps(
        [kind, *values],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reporting_scope_keys(
    *,
    database: str,
    company_id: str,
    user_id: str,
    thread_id: str,
    run_id: str,
) -> ReportingScopeKeys:
    """生成不暴露明文身份的 thread lease 和单 Run workspace key。"""

    thread_values = (database, company_id, user_id, thread_id)
    return ReportingScopeKeys(
        thread_lease_key=f"reporting-thread-{_scope_digest('thread', thread_values)}",
        workspace_key=f"reporting-run-{_scope_digest('workspace', (*thread_values, run_id))}",
    )


def resolve_reporting_workflow_scope(
    *,
    run_id: str,
    session_id: str,
    user_id: str | None,
    dependencies: dict[str, Any] | None = None,
    stored_scope: dict[str, Any] | None = None,
) -> ReportingWorkflowScope:
    dependency = (dependencies or {}).get(REPORT_WORKFLOW_SCOPE_DEPENDENCY)
    dependency = dependency if isinstance(dependency, dict) else {}
    stored = stored_scope if isinstance(stored_scope, dict) else {}

    database = str(stored.get("database") or dependency.get("database") or "")
    company_id = str(stored.get("companyId") or dependency.get("companyId") or "")
    effective_user_id = str(user_id or stored.get("userId") or "")
    effective_session_id = str(session_id or stored.get("sessionId") or "")

    token = get_access_token()
    if token is not None:
        claims = token.claims if isinstance(token.claims, dict) else {}
        claim_values = (
            claims.get("database"),
            claims.get("company"),
            claims.get("user"),
            claims.get("thread"),
        )
        if any(value is None or not str(value) for value in claim_values):
            raise ReportingError("report_mcp_unauthorized", "MCP capability 身份无效。")
        token_database, token_company, token_user, token_thread = (
            str(value) for value in claim_values
        )
        if database and database != token_database:
            raise ReportingError("report_workflow_scope_mismatch", "Reporting Workflow 租户作用域不一致。")
        if company_id and company_id != token_company:
            raise ReportingError("report_workflow_scope_mismatch", "Reporting Workflow 公司作用域不一致。")
        if effective_user_id and effective_user_id != token_user:
            raise ReportingError("report_workflow_scope_mismatch", "Reporting Workflow 用户作用域不一致。")
        if effective_session_id and effective_session_id != token_thread:
            raise ReportingError("report_mcp_thread_mismatch", "MCP session_id 与 capability thread 不一致。")
        database = token_database
        company_id = token_company
        effective_user_id = token_user
        effective_session_id = token_thread

    if not database and not company_id:
        database = company_id = "default"
    values = (run_id, effective_session_id, effective_user_id, database, company_id)
    if any(not value or len(value) > 256 for value in values):
        raise ReportingError("report_workflow_context_missing", "报表工作流作用域不完整。")

    keys = reporting_scope_keys(
        database=database,
        company_id=company_id,
        user_id=effective_user_id,
        thread_id=effective_session_id,
        run_id=run_id,
    )
    scope = ReportingWorkflowScope(
        run_id=run_id,
        session_id=effective_session_id,
        user_id=effective_user_id,
        database=database,
        company_id=company_id,
        thread_lease_key=keys.thread_lease_key,
        workspace_key=keys.workspace_key,
    )
    if stored and any(
        str(stored.get(key) or "") != value for key, value in scope.as_state().items()
    ):
        raise ReportingError("report_workflow_scope_mismatch", "Reporting Workflow 运行作用域不一致。")
    return scope


__all__ = [
    "REPORT_WORKFLOW_ENTRYPOINT_DEPENDENCY",
    "REPORT_WORKFLOW_ENTRYPOINT_STATE_KEY",
    "REPORT_WORKFLOW_SCOPE_DEPENDENCY",
    "ReportingScopeKeys",
    "ReportingWorkflowScope",
    "reporting_scope_keys",
    "resolve_reporting_workflow_scope",
]
