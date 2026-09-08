import hashlib

import pytest

from smart_reporting.sandbox import (
    ExecutionStatus,
    RunPythonScriptRequest,
    RunPythonScriptResult,
)
from smart_reporting.sandbox.python_runner import PythonScriptRunner


class RecordingExecution:
    def __init__(self) -> None:
        self.requests = []

    async def run_python_script(self, request):
        self.requests.append(request)
        return RunPythonScriptResult(
            status=ExecutionStatus.SUCCEEDED,
            exit_code=0,
            stdout="ok",
            script_hash=hashlib.sha256(request.script.encode()).hexdigest(),
        )


@pytest.mark.anyio
async def test_runner_uses_structured_execution_without_shell_command() -> None:
    execution = RecordingExecution()
    runner = PythonScriptRunner(execution)

    result = await runner.run(RunPythonScriptRequest(script="print('ok')", cwd="analysis"))

    assert execution.requests[0].script == "print('ok')"
    assert not hasattr(execution.requests[0], "command")
    assert result.script_hash == hashlib.sha256(b"print('ok')").hexdigest()
