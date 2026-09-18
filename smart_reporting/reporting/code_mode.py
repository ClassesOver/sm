"""Reporting 对 Agno CodeMode 的最小宿主机适配。"""

from __future__ import annotations

import asyncio
import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from agno.tools.code import CodeMode
from loguru import logger

from ..code_monitor.agno import CodeModeSource
from ..code_monitor.service import CodeMonitor
from ..workspace import WorkspaceError
from .host_workspace import HostReportingWorkspace
from .models import ReportingError

_SCRIPT_EXIT_DIRECTORY = ".reporting-exits"
_SCRIPT_EXIT_RECEIPT_MAX_BYTES = 16


@dataclass(frozen=True)
class ScriptProcessResult:
    """Agno cell 诊断与独立文件回执；None 表示没有有效的进程退出凭据。"""

    cell: Any
    exit_code: int | None


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


def _script_process_cell(script_path: str, exit_receipt_path: str) -> str:
    command = " ".join((shlex.quote(sys.executable), "-u", shlex.quote(script_path)))
    return (
        "%%bash\n"
        "set +e\n"
        f"{command}\n"
        "report_exit=$?\n"
        f"printf '%s\\n' \"$report_exit\" > {shlex.quote(exit_receipt_path)}\n"
        "exit $report_exit\n"
    )


def _parse_script_exit_receipt(raw: bytes) -> int | None:
    try:
        text = raw.decode("ascii").strip()
    except UnicodeDecodeError:
        return None
    if not text.isascii() or not text.isdigit():
        return None
    exit_code = int(text)
    return exit_code if 0 <= exit_code <= 255 else None


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
        self._logged_connections: dict[str, tuple[str, Any]] = {}
        self._monitor = CodeMonitor(log_streams=True)
        self._monitor_source = CodeModeSource(code_mode)
        self._monitor_lock = asyncio.Lock()

    async def _sync_monitor(self) -> None:
        async with self._monitor_lock:
            try:
                await self._monitor.reconcile(await self._monitor_source(), wait_for_ready=True)
            except Exception as error:
                logger.warning("report_code_mode_monitor_failed error_type={}", type(error).__name__)

    def _log_connection(self, session_id: str) -> None:
        # Agno 暂无公开连接查询接口；仅在此处只读访问，不改变 kernel 生命周期。
        sessions = getattr(self.code_mode, "_sessions", None)
        if not isinstance(sessions, Mapping):
            return
        for expired in list(self._logged_connections):
            if expired not in sessions:
                self._logged_connections.pop(expired, None)
        session = sessions.get(session_id)
        manager = getattr(session, "km", None)
        path = getattr(manager, "connection_file", None)
        if not isinstance(path, str) or not path:
            return
        connection = (path, getattr(session, "generation", None))
        if self._logged_connections.get(session_id) == connection:
            return
        command = shlex.join([
            "jupyter", "qtconsole", "--existing", path,
            "--ConsoleWidget.include_other_output=True",
        ])
        logger.info(
            "report_code_mode_connection session_id={} connection_file={} qtconsole_command={}",
            session_id, path, command,
        )
        self._logged_connections[session_id] = connection

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
        self._log_connection(session_id)
        await self._sync_monitor()

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
            process = await self.execute_script_process(
                session_id,
                workspace,
                normalized,
                matplotlib_agg=matplotlib_agg,
            )
            cell = process.cell
            status = _cell_field(cell, "status")
            exit_code = process.exit_code
            if exit_code is None and status == "ok":
                raise ReportingError(
                    "report_code_exit_receipt_invalid",
                    "CodeMode 脚本退出码回执缺失或无效。",
                    details={"sessionId": session_id, "scriptPath": normalized},
                )
            if status != "ok" or exit_code != 0:
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
    ) -> ScriptProcessResult:
        normalized = workspace.paths.normalize(script_path)
        receipt_path = f"{_SCRIPT_EXIT_DIRECTORY}/{uuid4().hex}.status"
        receipt_host_path = str(workspace.paths.to_host_path(receipt_path))
        await workspace.aensure_directory(session_id, _SCRIPT_EXIT_DIRECTORY)
        await self._bootstrap(session_id, workspace, matplotlib_agg=matplotlib_agg)
        try:
            try:
                cell = await self.code_mode.arun(
                    session_id, _script_process_cell(normalized, receipt_host_path)
                )
            except Exception as error:
                raise ReportingError(
                    "report_code_mode_execution_failed",
                    "CodeMode 脚本执行失败。",
                    details={"sessionId": session_id, "errorType": type(error).__name__},
                ) from error
            try:
                raw_receipt = await workspace.read_limited_regular_file(
                    session_id,
                    receipt_path,
                    max_bytes=_SCRIPT_EXIT_RECEIPT_MAX_BYTES,
                )
            except WorkspaceError:
                exit_code = None
            else:
                exit_code = _parse_script_exit_receipt(raw_receipt)
            return ScriptProcessResult(cell=cell, exit_code=exit_code)
        finally:
            try:
                await workspace.adelete_file(session_id, receipt_path)
            except (WorkspaceError, OSError) as error:
                logger.warning(
                    "report_code_exit_receipt_cleanup_failed session_id={} error_type={}",
                    session_id, type(error).__name__,
                )

    async def shutdown(self, session_id: str) -> None:
        await self.code_mode.ashutdown(session_id)
        await self._sync_monitor()
        self._logged_connections.pop(session_id, None)

    async def aclose(self) -> None:
        try:
            await self.code_mode.ashutdown()
        finally:
            await self._monitor.aclose()
            self._logged_connections.clear()


__all__ = [
    "ReportingCodeModeRuntime",
    "ScriptProcessResult",
    "create_reporting_code_mode_runtime",
]
