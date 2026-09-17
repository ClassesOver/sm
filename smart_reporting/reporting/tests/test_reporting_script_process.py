"""Exercise the actual shell wrapper independently of captured output streams."""

import asyncio
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
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
