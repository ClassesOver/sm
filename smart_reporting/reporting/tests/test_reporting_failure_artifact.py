import hashlib
import json

import pytest
from agno.tools.function import FunctionCall

from scripts import replay_visualization_task as replay
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.tests.test_reporting_code_edit import edit_patch
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    ToolkitRuntime,
    _failed_cell,
    binding,  # noqa: F401
    workspace,  # noqa: F401
)


@pytest.mark.anyio
async def test_first_failure_artifact_survives_edit_without_entering_metrics(binding, tmp_path):  # noqa: F811
    artifacts = []
    path = tmp_path / "failure.json"
    runtime = ToolkitRuntime()
    toolkit = ReportingCodeModeToolkit(
        binding, runtime, ReportingLspProcessManager(),
        failure_artifact_recorder=lambda payload: artifacts.append(
            replay.write_failure_artifact(path, payload)
        ),
    )
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, SOURCE)
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    runtime.next_cell = _failed_cell("ValueError: first failure")
    call = FunctionCall(function=functions["run_script"], arguments={})
    assert await call.aexecute()
    assert call.result["ok"] is False
    original = path.read_bytes()
    snapshot = json.loads(original)
    assert snapshot["source"] == SOURCE
    assert snapshot["sourceSha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert "ValueError: first failure" in snapshot["diagnostic"]["traceback"]
    assert "source" not in toolkit.first_run_failure
    assert artifacts == [{"path": str(path), "sha256": hashlib.sha256(original).hexdigest(), "size": len(original)}]
    assert path.stat().st_mode & 0o777 == 0o600

    edit = FunctionCall(function=functions["edit_script"], arguments={
        "patch": edit_patch(SOURCE, "write_text('{}')", "write_text('[]')"),
    })
    assert await edit.aexecute()
    assert edit.result["ok"] is True
    runtime.next_cell = _failed_cell("TypeError: later failure")
    assert await FunctionCall(function=functions["run_script"], arguments={}).aexecute()
    assert len(artifacts) == 1
    assert path.read_bytes() == original
    with pytest.raises(FileExistsError):
        replay.write_failure_artifact(path, {"source": "overwrite"})
    assert path.read_bytes() == original


@pytest.mark.anyio
async def test_failure_artifact_recorder_error_preserves_original_failure(binding):  # noqa: F811
    def broken_recorder(_payload):
        raise OSError("disk unavailable")

    runtime = ToolkitRuntime()
    toolkit = ReportingCodeModeToolkit(
        binding, runtime, ReportingLspProcessManager(),
        failure_artifact_recorder=broken_recorder,
    )
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, SOURCE)
    runtime.next_cell = _failed_cell("ValueError: original failure")
    function = next(tool for tool in toolkit.tool_functions if tool.name == "run_script")
    call = FunctionCall(function=function, arguments={})
    assert await call.aexecute()
    assert call.result["code"] == "report_code_mode_execution_failed"
    assert "original failure" in call.result["details"]["traceback"]
    assert toolkit.first_run_success is False


@pytest.mark.anyio
async def test_failure_artifact_does_not_capture_a_changed_source(binding, tmp_path):  # noqa: F811
    class ChangedSourceRuntime(ToolkitRuntime):
        async def execute_script_process(self, session_id, host_workspace, script_path, **kwargs):
            await host_workspace.awrite_text("task-1", script_path, SOURCE + "# changed\n", overwrite=True)
            return await super().execute_script_process(session_id, host_workspace, script_path, **kwargs)

    path = tmp_path / "failure.json"
    runtime = ChangedSourceRuntime()
    toolkit = ReportingCodeModeToolkit(
        binding, runtime, ReportingLspProcessManager(),
        failure_artifact_recorder=lambda payload: replay.write_failure_artifact(path, payload),
    )
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, SOURCE)
    runtime.next_cell = _failed_cell("ValueError: original failure")
    function = next(tool for tool in toolkit.tool_functions if tool.name == "run_script")
    call = FunctionCall(function=function, arguments={})
    assert await call.aexecute()
    assert call.result["code"] == "report_code_mode_execution_failed"
    assert not path.exists()
