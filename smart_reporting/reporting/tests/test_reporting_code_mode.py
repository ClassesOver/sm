# ruff: noqa: E402
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skip(reason="V1 统一覆盖交互式 CodeMode 验收")

from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceRegistry,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope

SECRET = "0123456789abcdef0123456789abcdef"


class FakeCodeMode:
    def __init__(self, results: list[object] | None = None) -> None:
        self.results = list(results or [])
        self.cells: list[tuple[str, str]] = []
        self.shutdowns: list[str | None] = []

    async def arun(self, session_id: str, code: str) -> object:
        self.cells.append((session_id, code))
        if self.results:
            return self.results.pop(0)
        return SimpleNamespace(
            status="ok",
            stdout="",
            stderr="",
            result=None,
            traceback=None,
            truncated=[],
            execution_count=len(self.cells),
        )

    async def ashutdown(self, session_id: str | None = None) -> None:
        self.shutdowns.append(session_id)


def _workspace(tmp_path: Path) -> HostReportingWorkspace:
    scope = ReportingWorkflowScope(
        run_id="run-1",
        external_run_id="external-run-1",
        session_id="session-1",
        caller_thread_id="thread-1",
        user_id="user-1",
        database="database-1",
        company_id="company-1",
        thread_lease_key="lease-1",
        workspace_key="workspace-1",
    )
    identity = ReportingWorkspaceRegistry(tmp_path, secret=SECRET).resolve(scope)
    return HostReportingWorkspace(identity)


@pytest.mark.anyio
async def test_code_mode_bootstraps_workspace_and_shuts_down_task_kernel(
    tmp_path: Path,
) -> None:
    code_mode = FakeCodeMode()
    workspace = _workspace(tmp_path)
    await workspace.awrite_text("workspace-1", "analysis/charts.py", "answer = 42")
    runtime = ReportingCodeModeRuntime(code_mode)

    result = await runtime.execute_script(
        "visualization:task-1",
        workspace,
        "analysis/charts.py",
        timeout=30,
    )
    await runtime.shutdown("visualization:task-1")

    assert [session_id for session_id, _code in code_mode.cells] == [
        "visualization:task-1",
        "visualization:task-1",
    ]
    bootstrap = code_mode.cells[0][1]
    assert "os.chdir" in bootstrap
    assert "MPLBACKEND" in bootstrap
    assert code_mode.cells[1][1].startswith("exec(compile(open(")
    assert result["exitCode"] == 0
    assert result["status"] == "completed"
    assert code_mode.shutdowns == ["visualization:task-1"]


@pytest.mark.anyio
async def test_code_mode_execution_error_uses_stable_reporting_error(tmp_path: Path) -> None:
    failed = SimpleNamespace(
        status="error",
        stdout="before failure",
        stderr="",
        result=None,
        traceback="ValueError: failed",
        truncated=[],
        execution_count=2,
    )
    code_mode = FakeCodeMode(results=[SimpleNamespace(status="ok"), failed])
    workspace = _workspace(tmp_path)
    await workspace.awrite_text("workspace-1", "analysis/fail.py", "raise ValueError")
    runtime = ReportingCodeModeRuntime(code_mode)

    with pytest.raises(ReportingError) as caught:
        await runtime.execute_script(
            "analysis:task-1",
            workspace,
            "analysis/fail.py",
            timeout=30,
        )

    assert caught.value.code == "report_code_mode_execution_failed"
    assert caught.value.details == {
        "sessionId": "analysis:task-1",
        "scriptPath": "analysis/fail.py",
        "status": "error",
        "stdout": "before failure",
        "stderr": "",
        "traceback": "ValueError: failed",
    }


@pytest.mark.anyio
async def test_code_mode_close_shuts_down_all_kernels() -> None:
    code_mode = FakeCodeMode()
    runtime = ReportingCodeModeRuntime(code_mode)

    await runtime.aclose()

    assert code_mode.shutdowns == [None]
