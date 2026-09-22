"""Exercise the actual shell wrapper independently of captured output streams."""

import asyncio
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from loguru import logger

from smart_reporting.reporting.code_mode import (
    ReportingCodeModeRuntime,
    _script_process_cell,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    workspace,  # noqa: F401
)


class ShellCodeMode:
    def __init__(self, root, receipt=None):
        self.root = root
        self.receipt = receipt
        self.paths = []

    async def arun(self, session_id, code):
        if not code.startswith("%%bash\n"):
            return SimpleNamespace(status="ok")
        receipt = shlex.split(code.splitlines()[-2])[-1]
        self.paths.append(receipt)
        process = await asyncio.create_subprocess_exec(
            "bash", "-c", code.removeprefix("%%bash\n"), cwd=self.root,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        if self.receipt is not None:
            if self.receipt == b"missing":
                Path(receipt).unlink()
            else:
                Path(receipt).write_bytes(self.receipt)
        # Deliberately discard both streams, as CodeMode truncation may do.
        return SimpleNamespace(status="ok" if process.returncode == 0 else "error",
                               stdout="", stderr="", traceback=None)


def test_visualization_shell_wrapper_runs_font_bootstrap_in_script_process(tmp_path):
    script_path = tmp_path / "chart.py"
    output_path = tmp_path / "font.txt"
    receipt_path = tmp_path / "exit.status"
    script_path.write_text(
        "from pathlib import Path\n"
        "from matplotlib import font_manager, rcParams\n"
        "font = font_manager.findfont('Noto Sans CJK SC', fallback_to_default=False)\n"
        f"Path({str(output_path)!r}).write_text("
        "rcParams['font.sans-serif'][0] + '\\n' + font, encoding='utf-8')\n",
        encoding="utf-8",
    )
    cell = _script_process_cell(
        str(script_path),
        str(receipt_path),
        matplotlib_root=str(tmp_path / "runtime"),
    )

    result = subprocess.run(
        ["bash", "-c", cell.removeprefix("%%bash\n")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert receipt_path.read_text(encoding="ascii").strip() == "0"
    family, font_path = output_path.read_text(encoding="utf-8").splitlines()
    assert family == "Noto Sans CJK SC"
    assert font_path.endswith(("NotoSansCJKSC-Regular.otf", "NotoSansCJK-Regular.ttc"))


def test_visualization_shell_wrapper_runs_outside_project_cwd(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    output_path = workspace_root / "completed.txt"
    receipt_path = workspace_root / "exit.status"
    (workspace_root / "chart.py").write_text(
        "from pathlib import Path\n"
        "Path('completed.txt').write_text('ok', encoding='utf-8')\n",
        encoding="utf-8",
    )
    cell = _script_process_cell(
        "chart.py",
        str(receipt_path),
        matplotlib_root=str(workspace_root / "runtime"),
    )

    result = subprocess.run(
        ["bash", "-c", cell.removeprefix("%%bash\n")],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert output_path.read_text(encoding="utf-8") == "ok"
    assert receipt_path.read_text(encoding="ascii").strip() == "0"


@pytest.mark.anyio
async def test_connection_log_precedes_execution_and_refreshes_after_restart(workspace):  # noqa: F811
    records = []
    path = "/tmp/kernel debug.json"

    class ObservableCodeMode(ShellCodeMode):
        def __init__(self):
            super().__init__(workspace.identity.root)
            self._sessions = {"task": SimpleNamespace(
                km=SimpleNamespace(connection_file=path, key="must-not-be-logged"),
                generation=1,
            )}

        async def arun(self, session_id, code):
            if code == "business()":
                assert any("report_code_mode_connection" in row for row in records)
            return SimpleNamespace(status="ok")

    code_mode = ObservableCodeMode()
    runtime = ReportingCodeModeRuntime(code_mode)
    sink = logger.add(lambda message: records.append(str(message)), format="{message}")
    try:
        await runtime.execute("task", workspace, "business()")
        await runtime.execute("task", workspace, "business()")
        rows = [row for row in records if "report_code_mode_connection" in row]
        assert len(rows) == 1
        command = rows[0].split("qtconsole_command=", 1)[1].strip()
        assert shlex.split(command) == [
            "jupyter", "qtconsole", "--existing", path,
            "--ConsoleWidget.include_other_output=True",
        ]
        assert "session_id=task" in rows[0]
        assert "must-not-be-logged" not in rows[0]
        code_mode._sessions["task"].generation = 2
        await runtime.execute("task", workspace, "business()")
        assert len([row for row in records if "report_code_mode_connection" in row]) == 2
    finally:
        logger.remove(sink)


def test_runtime_records_and_drains_execution_spans_without_kernel_internals():
    runtime = ReportingCodeModeRuntime(ShellCodeMode("."))
    for name in ("bootstrap", "monitor", "cell", "script", "shutdown"):
        runtime._record_execution_span("span-task", name, 0.0)
    for _ in range(70):
        runtime._record_execution_span("span-task", "cell", 0.0)

    spans = runtime.drain_execution_spans("span-task")
    assert isinstance(spans, dict)
    assert set(spans) == {"bootstrap", "monitor", "cell", "script", "shutdown"}
    assert all(
        isinstance(value, list) and value and all(item >= 0 for item in value)
        for value in spans.values()
    )
    assert len(spans["cell"]) == 64
    assert runtime.drain_execution_spans("span-task") == "unknown"

    runtime._record_execution_span("other-task", "cell", 0.0)
    other = runtime.drain_execution_spans("other-task")
    assert isinstance(other, dict)
    assert set(other) == {"cell"}
    assert runtime.drain_execution_spans("span-task") == "unknown"


@pytest.mark.anyio
async def test_script_exit_receipts_survive_output_loss_and_concurrency(workspace):  # noqa: F811
    code_mode = ShellCodeMode(workspace.identity.root)
    runtime = ReportingCodeModeRuntime(code_mode)
    for code in (0, 7):
        await workspace.awrite_text("task", f"analysis/exit {code}.py",
                                    f"print('__REPORT_EXIT__=99'); raise SystemExit({code})")
    results = await asyncio.gather(*(
        runtime.execute_script_process(str(code), workspace, f"analysis/exit {code}.py",
                                       matplotlib_agg=False)
        for code in (0, 7)
    ))
    assert [result.exit_code for result in results] == [0, 7]
    assert len(set(code_mode.paths)) == 2
    assert list((workspace.identity.root / ".reporting-exits").iterdir()) == []


@pytest.mark.anyio
@pytest.mark.parametrize("receipt", [b"missing", b"garbage", b"256", b"0" * 17])
async def test_execute_script_rejects_invalid_receipt(workspace, receipt):  # noqa: F811
    await workspace.awrite_text("task", "analysis/a.py", "pass")
    runtime = ReportingCodeModeRuntime(ShellCodeMode(workspace.identity.root, receipt))
    with pytest.raises(ReportingError) as caught:
        await runtime.execute_script("task", workspace, "analysis/a.py", timeout=10)
    assert caught.value.code == "report_code_exit_receipt_invalid"
    assert list((workspace.identity.root / ".reporting-exits").iterdir()) == []


@pytest.mark.anyio
async def test_script_process_cleans_receipt_after_transport_error(workspace):  # noqa: F811
    await workspace.awrite_text("task", "analysis/a.py", "pass")

    class BrokenCodeMode(ShellCodeMode):
        async def arun(self, session_id, code):
            result = await super().arun(session_id, code)
            if code.startswith("%%bash\n"):
                raise RuntimeError("transport lost after execution")
            return result

    runtime = ReportingCodeModeRuntime(BrokenCodeMode(workspace.identity.root))
    with pytest.raises(ReportingError) as caught:
        await runtime.execute_script_process("task", workspace, "analysis/a.py", matplotlib_agg=False)
    assert caught.value.code == "report_code_mode_execution_failed"
    assert list((workspace.identity.root / ".reporting-exits").iterdir()) == []


@pytest.mark.anyio
async def test_real_agno_kernel_receipts_survive_stream_truncation(workspace):  # noqa: F811
    from agno.tools.code import CodeMode

    runtime = ReportingCodeModeRuntime(CodeMode(
        snapshot=False, allow_shell=True, cwd=str(workspace.identity.root),
        timeout=30, max_output_chars=128, max_kernels=1,
    ))
    try:
        for code in (0, 7):
            path = f"analysis/exit {code}.py"
            await workspace.awrite_text("task", path,
                f"import sys\nprint('x' * 2000)\nprint('y' * 2000, file=sys.stderr)\n"
                f"raise SystemExit({code})\n")
            process = await runtime.execute_script_process("real-kernel", workspace, path,
                                                           matplotlib_agg=False)
            assert process.exit_code == code
            assert process.cell.status == ("ok" if code == 0 else "error")
            assert "stdout" in process.cell.truncated
            assert "stderr" in process.cell.truncated
            assert list((workspace.identity.root / ".reporting-exits").iterdir()) == []
    finally:
        await runtime.aclose()


@pytest.mark.anyio
async def test_real_agno_kernel_exploration_variables_persist_until_shutdown(workspace):  # noqa: F811
    from agno.tools.code import CodeMode

    runtime = ReportingCodeModeRuntime(CodeMode(
        snapshot=False,
        cwd=str(workspace.identity.root),
        timeout=30,
        max_kernels=1,
    ))
    try:
        first = await runtime.execute(
            "exploration-state",
            workspace,
            "import pandas as pd\ndf1 = pd.DataFrame({'value': [41]})",
        )
        second = await runtime.execute(
            "exploration-state",
            workspace,
            "int(df1['value'].sum()) + 1",
        )

        assert first.status == "ok"
        assert second.status == "ok"
        assert second.result == "42"
        variables = await runtime.exploration_variables("exploration-state")
        assert variables["df1"] == "DataFrame"
        assert variables["pd"] == "module"

        await runtime.shutdown("exploration-state")
        assert await runtime.exploration_variables("exploration-state") == {}
    finally:
        await runtime.aclose()


@pytest.mark.anyio
async def test_exploration_variables_timeout_returns_empty_and_cancels(monkeypatch):
    class SlowCodeMode:
        cancelled = False

        async def avariables(self, _session_id):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    code_mode = SlowCodeMode()
    runtime = ReportingCodeModeRuntime(code_mode)
    monkeypatch.setattr(
        "smart_reporting.reporting.code_mode._EXPLORATION_VARIABLES_TIMEOUT_SECONDS",
        0.01,
    )

    assert await runtime.exploration_variables("busy") == {}
    assert code_mode.cancelled is True
