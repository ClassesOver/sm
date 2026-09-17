"""Reporting 对 Agno CodeMode 的最小宿主机适配。"""

from __future__ import annotations

import re
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agno.tools.code import CodeMode

from .host_workspace import HostReportingWorkspace
from .models import ReportingError

_SCRIPT_EXIT_MARKER = "__REPORT_EXIT__="
_SCRIPT_EXIT_PATTERN = re.compile(r"__REPORT_EXIT__=(-?\d+)(?:\n|$)")


def _cell_field(cell: Any, name: str, default: Any = None) -> Any:
    if isinstance(cell, Mapping):
        return cell.get(name, default)
    return getattr(cell, name, default)


def _bootstrap_cell(workspace: HostReportingWorkspace, *, matplotlib_agg: bool) -> str:
    lines = [
        "import os",
        f"os.chdir({str(workspace.identity.root)!r})",
    ]
    if matplotlib_agg:
        lines.append("os.environ['MPLBACKEND'] = 'Agg'")
    return "\n".join(lines)


def _script_process_cell(script_path: str) -> str:
    command = " ".join((shlex.quote(sys.executable), shlex.quote(script_path)))
    return (
        "%%bash\n"
        "set +e\n"
        f"{command}\n"
        "report_exit=$?\n"
        f'echo "{_SCRIPT_EXIT_MARKER}$report_exit" >&2\n'
    )


def script_process_exit_code(cell: Any) -> int | None:
    stderr = _cell_field(cell, "stderr", "")
    if not isinstance(stderr, str):
        return None
    matches = list(_SCRIPT_EXIT_PATTERN.finditer(stderr))
    return int(matches[-1].group(1)) if matches else None


def create_reporting_code_mode_runtime(
    workspace_root: str | Path,
    *,
    analysis_concurrency: int,
    section_concurrency: int,
    timeout: int,
) -> ReportingCodeModeRuntime:
    """为 Reporting 进程创建共享的宿主机 CodeMode 运行时。"""

    return ReportingCodeModeRuntime(
        CodeMode(
            allow_shell=True,
            allow_restart=True,
            snapshot=False,
            cwd=str(workspace_root),
            timeout=timeout,
            max_kernels=analysis_concurrency + section_concurrency,
        )
    )


class ReportingCodeModeRuntime:
    """共享 CodeMode 实例的任务级执行与关闭边界。"""

    def __init__(self, code_mode: CodeMode) -> None:
        self.code_mode = code_mode

    async def _bootstrap(
        self,
        session_id: str,
        workspace: HostReportingWorkspace,
        *,
        matplotlib_agg: bool,
    ) -> None:
        try:
            result = await self.code_mode.arun(
                session_id,
                _bootstrap_cell(workspace, matplotlib_agg=matplotlib_agg),
            )
        except Exception as error:
            raise ReportingError(
                "report_code_mode_bootstrap_failed",
                "CodeMode 工作区初始化失败。",
                details={"sessionId": session_id, "errorType": type(error).__name__},
            ) from error
        if _cell_field(result, "status") != "ok":
            raise ReportingError(
                "report_code_mode_bootstrap_failed",
                "CodeMode 工作区初始化失败。",
                details={
                    "sessionId": session_id,
                    "status": _cell_field(result, "status"),
                    "traceback": _cell_field(result, "traceback"),
                },
            )

    async def execute(
        self,
        session_id: str,
        workspace: HostReportingWorkspace,
        code: str,
        *,
        matplotlib_agg: bool = False,
    ) -> Any:
        await self._bootstrap(session_id, workspace, matplotlib_agg=matplotlib_agg)
        try:
            return await self.code_mode.arun(session_id, code)
        except Exception as error:
            raise ReportingError(
                "report_code_mode_execution_failed",
                "CodeMode 执行失败。",
                details={"sessionId": session_id, "errorType": type(error).__name__},
            ) from error

    async def execute_script(
        self,
        session_id: str,
        workspace: HostReportingWorkspace,
        script_path: str,
        *,
        timeout: int,
        close: bool = False,
        matplotlib_agg: bool = True,
    ) -> dict[str, Any]:
        del timeout  # CodeMode 的 cell timeout 在实例级配置；调用方仍保留该契约参数。
        try:
            normalized = workspace.paths.normalize(script_path)
            cell = await self.execute_script_process(
                session_id,
                workspace,
                normalized,
                matplotlib_agg=matplotlib_agg,
            )
            status = _cell_field(cell, "status")
            exit_code = script_process_exit_code(cell)
            if status != "ok" or exit_code is None or exit_code != 0:
                details = {
                    "sessionId": session_id,
                    "scriptPath": normalized,
                    "status": status,
                    "stdout": _cell_field(cell, "stdout", "") or "",
                    "stderr": _cell_field(cell, "stderr", "") or "",
                    "traceback": _cell_field(cell, "traceback"),
                    "exitCode": exit_code,
                }
                raise ReportingError(
                    "report_code_mode_execution_failed",
                    "CodeMode 脚本执行失败。",
                    details=details,
                )
            return {
                "ok": True,
                "status": "completed",
                "exitCode": 0,
                "stdout": _cell_field(cell, "stdout", "") or "",
                "stderr": _cell_field(cell, "stderr", "") or "",
            }
        finally:
            if close:
                await self.shutdown(session_id)

    async def execute_script_process(
        self,
        session_id: str,
        workspace: HostReportingWorkspace,
        script_path: str,
        *,
        matplotlib_agg: bool,
    ) -> Any:
        normalized = workspace.paths.normalize(script_path)
        await self._bootstrap(session_id, workspace, matplotlib_agg=matplotlib_agg)
        try:
            return await self.code_mode.arun(session_id, _script_process_cell(normalized))
        except Exception as error:
            raise ReportingError(
                "report_code_mode_execution_failed",
                "CodeMode 脚本执行失败。",
                details={"sessionId": session_id, "errorType": type(error).__name__},
            ) from error

    async def shutdown(self, session_id: str) -> None:
        await self.code_mode.ashutdown(session_id)

    async def aclose(self) -> None:
        await self.code_mode.ashutdown()


__all__ = [
    "ReportingCodeModeRuntime",
    "create_reporting_code_mode_runtime",
    "script_process_exit_code",
]
