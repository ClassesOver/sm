"""Reporting 会话专属的宿主机 Agno Workspace。"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path

from agno.tools.workspace import Workspace

from .models import ReportingError
from .workflow.scope import ReportingWorkflowScope


def validate_host_workspace_root(root: str | Path) -> Path:
    """校验并创建 Reporting 宿主机工作区根目录。"""

    raw = str(root).strip()
    if not raw:
        raise ValueError("REPORTING_HOST_WORKSPACE_ROOT 不能为空")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("REPORTING_HOST_WORKSPACE_ROOT 必须是绝对路径")
    if path.is_symlink():
        raise ValueError("REPORTING_HOST_WORKSPACE_ROOT 不得是符号链接")
    if path.exists() and not path.is_dir():
        raise ValueError("REPORTING_HOST_WORKSPACE_ROOT 必须是目录")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("REPORTING_HOST_WORKSPACE_ROOT 必须是非符号链接目录")
    return path


@dataclass(frozen=True)
class ReportingWorkspaceIdentity:
    """一个报表 run 的宿主机目录和原生 Agno Workspace。"""

    workflow_session_id: str
    workspace_key: str
    scope_fingerprint: str
    root: Path
    workspace: Workspace


class ReportingWorkspaceRegistry:
    """按可信 workspace key 复用当前进程内的 Reporting Workspace。"""

    def __init__(self, root: str | Path, *, secret: str) -> None:
        self.root = validate_host_workspace_root(root)
        self._secret = secret.encode("utf-8")
        self._entries: dict[str, ReportingWorkspaceIdentity] = {}

    def _fingerprint(self, scope: ReportingWorkflowScope) -> str:
        payload = json.dumps(
            [
                scope.database,
                scope.company_id,
                scope.user_id,
                scope.caller_thread_id,
                scope.session_id,
                scope.workspace_key,
                scope.run_id,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def resolve(self, scope: ReportingWorkflowScope) -> ReportingWorkspaceIdentity:
        fingerprint = self._fingerprint(scope)
        existing = self._entries.get(scope.workspace_key)
        if existing is not None:
            if (
                existing.workflow_session_id != scope.session_id
                or existing.scope_fingerprint != fingerprint
            ):
                raise ReportingError(
                    "report_host_workspace_scope_mismatch",
                    "Reporting Workspace 作用域不一致。",
                )
            return existing

        session_root = self.root / "sessions" / fingerprint
        session_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        workspace = Workspace(
            root=session_root,
            allowed=Workspace.ALL_TOOLS,
            confirm=[],
        )
        identity = ReportingWorkspaceIdentity(
            workflow_session_id=scope.session_id,
            workspace_key=scope.workspace_key,
            scope_fingerprint=fingerprint,
            root=session_root,
            workspace=workspace,
        )
        self._entries[scope.workspace_key] = identity
        return identity

    def get(self, workspace_key: str) -> ReportingWorkspaceIdentity | None:
        return self._entries.get(workspace_key)

    def release(self, workspace_key: str) -> bool:
        return self._entries.pop(workspace_key, None) is not None

    async def aclose(self) -> None:
        self._entries.clear()


__all__ = [
    "ReportingWorkspaceIdentity",
    "ReportingWorkspaceRegistry",
    "validate_host_workspace_root",
]
