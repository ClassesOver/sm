"""真实 kernel：日志到达后才允许脚本结束，验证没有等待最终结果。"""

import asyncio

import pytest
from agno.tools.code import CodeMode
from loguru import logger

from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    workspace,  # noqa: F401
)


@pytest.mark.anyio
@pytest.mark.parametrize("script", [False, True])
async def test_stream_logged_before_execution_finishes(workspace, script):  # noqa: F811
    runtime = ReportingCodeModeRuntime(CodeMode(allow_shell=True, snapshot=False, timeout=15))
    release = workspace.identity.root / "release"
    observed = asyncio.Event()
    records = []

    def capture(message):
        text = str(message)
        records.append(text)
        if "report_code_mode_stream" in text and "progress-marker" in text:
            observed.set()

    sink = logger.add(capture, format="{message}")
    code = (
        "import sys, time\nfrom pathlib import Path\n"
        "print('progress-marker')\n"
        "print('stderr-marker', file=sys.stderr, flush=True)\n"
        "sys.stdout.flush()\n" if not script else
        "import sys, time\nfrom pathlib import Path\n"
        "print('progress-marker')\n"
        "print('stderr-marker', file=sys.stderr)\n"
    )
    code += (
        "deadline = time.monotonic() + 10\n"
        f"while not Path({str(release)!r}).exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.05)\n"
    )
    task = None
    try:
        if script:
            await workspace.awrite_text("stream-test", "analysis/progress.py", code)
            operation = runtime.execute_script("stream-test", workspace, "analysis/progress.py", timeout=15)
        else:
            operation = runtime.execute("stream-test", workspace, code)
        task = asyncio.create_task(operation)
        await asyncio.wait_for(observed.wait(), timeout=15)
        assert not task.done()
        release.touch()
        await task
        await runtime.aclose()
        output = "\n".join(row for row in records if "report_code_mode_stream" in row)
        assert "session_id=stream-test" in output
        assert "name=stdout" in output and "name=stderr" in output
        assert "stderr-marker" in output
        assert not runtime._monitor.clients
    finally:
        release.touch()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await runtime.aclose()
        logger.remove(sink)
