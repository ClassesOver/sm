"""Fresh executions must observe current files even in the same session."""

import asyncio
from types import SimpleNamespace

import pytest
from agno.tools.code import CodeMode

from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceRegistry,
)
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _ProcessCodeMode:
    """Run the real script wrapper without requiring Jupyter's TCP sockets."""

    def __init__(self, root):
        self.root = root

    async def arun(self, _session_id, code):
        if not code.startswith("%%bash\n"):
            return SimpleNamespace(status="ok")
        process = await asyncio.create_subprocess_exec(
            "bash",
            "-c",
            code.removeprefix("%%bash\n"),
            cwd=self.root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return SimpleNamespace(
            status="ok" if process.returncode == 0 else "error",
            stdout=stdout.decode(),
            stderr=stderr.decode(),
        )

    async def ashutdown(self):
        pass


@pytest.mark.anyio
@pytest.mark.parametrize(
    "engine",
    ["process", pytest.param("agno", marks=pytest.mark.integration)],
)
async def test_completed_script_reruns_with_changed_input_and_source(tmp_path, engine):
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
    workspace = HostReportingWorkspace(
        ReportingWorkspaceRegistry(tmp_path, secret="0" * 32).resolve(scope)
    )
    code_mode = (
        CodeMode(
            snapshot=False,
            allow_shell=True,
            cwd=str(workspace.identity.root),
            timeout=30,
            max_kernels=1,
        )
        if engine == "agno"
        else _ProcessCodeMode(workspace.identity.root)
    )
    runtime = ReportingCodeModeRuntime(code_mode)
    root = workspace.identity.root
    script = (
        "from pathlib import Path\n"
        "value = Path('input.txt').read_text()\n"
        "Path('output.txt').write_text(value)\n"
        "with Path('runs.txt').open('a') as runs:\n"
        "    runs.write('executed\\n')\n"
    )
    try:
        (root / "input.txt").write_text("first")
        (root / "script.py").write_text(script)
        for expected in ("first", "second", "SECOND"):
            if expected == "second":
                (root / "input.txt").write_text("second")
                (root / "output.txt").write_text("stale output")
            elif expected == "SECOND":
                (root / "script.py").write_text(
                    script.replace("write_text(value)", "write_text(value.upper())")
                )
            result = await runtime.execute_script(
                "same-session", workspace, "script.py", timeout=30, matplotlib_agg=False
            )
            assert result["status"] == "completed"
            assert (root / "output.txt").read_text() == expected
        assert (root / "runs.txt").read_text().splitlines() == ["executed"] * 3
        assert list((root / ".reporting-exits").iterdir()) == []
    finally:
        await runtime.aclose()
