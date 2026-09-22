from __future__ import annotations

import json
from ast import literal_eval
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from agno.models.message import Message
from agno.tools.code.types import CellResult
from agno.tools.function import Function, FunctionCall
from openai import AsyncOpenAI

from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.code_agent.toolkit import (
    MAX_DIAGNOSTIC_BYTES,
    ReportingCodeModeToolkit,
)
from smart_reporting.reporting.code_mode import ScriptProcessResult
from smart_reporting.reporting.model_policy import ThinkingDecision, bind_reporting_thinking
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    ToolkitRuntime,
    _run_context,
    _task_context,
    _visualization_task_context,
    binding,  # noqa: F401
    workspace,  # noqa: F401
)
from smart_reporting.reporting.workflow.runtime.analysis import _CODING_SCRIPT_MAX_BYTES
from smart_reporting.reporting.workflow.runtime.code_generation import (
    MAX_DIAGNOSTIC_OUTPUT_LENGTH,
    ReportingCodeGenerationRunner,
    _code_failure_kind,
)
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    VisualizationSectionWorkflow,
)


@pytest.mark.parametrize("code,expected", [
    ("report_code_source_invalid", "python_compile_failure"),
    ("report_code_mode_execution_failed", "python_execution_failure"),
    ("report_analysis_evidence_schema_invalid", "schema_failure"),
    ("unknown", None),
])
def test_current_code_errors_have_correct_failure_kind(code, expected):
    assert _code_failure_kind({"code": code}) == expected


@pytest.mark.anyio
async def test_repeated_failure_warns_and_success_marks_diagnostic_resolved(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    await toolkit.write_script("if True print('broken')\n")
    for attempt in range(3):
        call = FunctionCall(function=functions["run_script"], arguments={})
        await call.aexecute()
        assert call.result["ok"] is False
        if attempt:
            assert call.result["repeatedFailureCount"] == attempt + 1
            assert "修复" in call.result["repairHint"]
    await FunctionCall(function=functions["read_script"], arguments={}).aexecute()
    assert toolkit.last_failure["resolved"] is False
    await toolkit.write_script(SOURCE)
    await FunctionCall(function=functions["run_script"], arguments={}).aexecute()
    assert toolkit.last_failure["resolved"] is True
    assert toolkit.last_failure["code"] == "report_code_source_invalid"


@pytest.mark.anyio
@pytest.mark.parametrize("exhausted", [False, True])
async def test_no_submission_reports_actual_failure_and_usage(workspace, exhausted):  # noqa: F811
    class Agent:
        def __init__(self, tools):
            self.tools = {tool.name: tool for tool in tools}

        async def arun(self, *_args, **_kwargs):
            await FunctionCall(function=self.tools["write_script"], arguments={
                "source": "if True print('broken')\n",
            }).aexecute()
            await FunctionCall(function=self.tools["run_script"], arguments={}).aexecute()
            return SimpleNamespace(messages=[Message(role="tool", content="skipped")] * (30 if exhausted else 2))

    runner = ReportingCodeGenerationRunner(Agent, ToolkitRuntime(), ReportingLspProcessManager())
    with pytest.raises(ReportingError) as caught:
        await runner.run(_task_context(workspace), workspace, {}, run_context=_run_context())
    details = caught.value.details
    assert caught.value.code == "report_code_generation_no_submission"
    assert details["retryable"] is False
    assert details["lastTool"] == "run_script"
    assert details["lastFailure"]["code"] == "report_code_source_invalid"
    assert details["lastFailure"]["resolved"] is False
    assert len(details["sourceSha256"]) == 64
    assert details["hasExecutionReceipt"] is False
    assert details["completedToolCalls"] == 2
    assert details["terminationReason"] == (
        "tool_call_limit_reached" if exhausted else "model_ended_without_submission"
    )


def test_shared_evidence_validator_uses_trusted_identity_and_allows_semantic_warning():
    from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
        validate_supplemental_evidence,
    )
    evidence = validate_supplemental_evidence(json.dumps({
        "analysisId": "untrusted", "analysis_id": "also-untrusted",
        "datasetIds": ["untrusted"], "dataset_ids": ["also-untrusted"],
        "findings": [{"text": "finding"}],
        "reconciliations": [{"name": "check", "passed": False}],
        "warnings": [],
    }), {"analysisId": "analysis_001", "datasetIds": ["ds_1", "ds_1"]})
    assert evidence.analysis_id == "analysis_001"
    assert evidence.dataset_ids == ("ds_1",)
    assert evidence.reconciliations[0]["passed"] is False


@pytest.mark.anyio
async def test_evidence_preflight_blocks_workflow_handoff_until_repaired(binding):  # noqa: F811
    from pydantic import ValidationError

    from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
        supplemental_evidence_schema_error,
        validate_supplemental_evidence,
    )

    async def preflight(receipt):
        raw = await binding.workspace.read_limited_regular_file(
            binding.context.task_id, receipt.output_files[0].path, max_bytes=1000,
        )
        try:
            validate_supplemental_evidence(raw, {
                "analysisId": "analysis_001", "datasetIds": ["ds_1"],
            })
        except ValidationError as error:
            rejection = supplemental_evidence_schema_error(error)
            return {"code": rejection.code, "message": rejection.message,
                    "details": rejection.details}
        return None

    toolkit = ReportingCodeModeToolkit(
        binding, ToolkitRuntime(), ReportingLspProcessManager(), output_preflight=preflight,
    )
    await toolkit.write_script(SOURCE)
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    call = FunctionCall(function=functions["run_script"], arguments={})
    await call.aexecute()
    result = call.result
    assert result["ok"] is False
    diagnostic = result["outputValidation"]
    assert diagnostic["code"] == "report_analysis_evidence_schema_invalid"
    assert "findings" in diagnostic["details"]["issueSummary"]
    assert toolkit.last_failure["code"] == diagnostic["code"]
    submission = await toolkit.submit_script()
    assert submission["code"] == "report_code_output_validation_pending"


@pytest.mark.anyio
async def test_preflight_failure_blocks_submission_instead_of_passing(binding):  # noqa: F811
    """预检自身抛错时不得默认放行；未获得结论等于未通过。"""

    calls = 0

    async def preflight(receipt):
        nonlocal calls
        calls += 1
        raise RuntimeError("validator exploded")

    toolkit = ReportingCodeModeToolkit(
        binding, ToolkitRuntime(), ReportingLspProcessManager(), output_preflight=preflight,
    )
    await toolkit.write_script(SOURCE)
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    call = FunctionCall(function=functions["run_script"], arguments={})
    await call.aexecute()
    result = call.result
    assert calls == 1
    assert result["ok"] is False
    assert result["outputValidation"]["code"] == "report_code_output_validation_unavailable"
    assert result["outputValidation"]["details"]["errorType"] == "RuntimeError"
    assert result["outputValidation"]["details"]["reason"] == "validator exploded"
    assert binding.output_validation.status == "unavailable"
    assert toolkit.last_failure["code"] == "report_code_output_validation_unavailable"
    assert (await toolkit.submit_script())["code"] == "report_code_output_validation_pending"

    # 预检恢复正常后成功执行一次，阻塞必须被解除。
    async def healthy_preflight(receipt):
        return None

    toolkit.output_preflight = healthy_preflight
    await FunctionCall(function=functions["run_script"], arguments={}).aexecute()
    assert (await toolkit.submit_script())["ok"] is True


@pytest.mark.anyio
async def test_stale_validation_failure_blocks_current_run_submission(binding):  # noqa: F811
    """当前执行没有匹配的通过结论时必须 fail-closed。"""

    async def preflight(receipt):
        return {"code": "report_analysis_evidence_schema_invalid", "message": "结构未通过"}

    toolkit = ReportingCodeModeToolkit(
        binding, ToolkitRuntime(), ReportingLspProcessManager(), output_preflight=preflight,
    )
    await toolkit.write_script(SOURCE)
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    await FunctionCall(function=functions["run_script"], arguments={}).aexecute()
    assert toolkit.pending_output_validation is not None

    # 伪造一个属于别次执行的失败结论：当前回执没有通过结论，仍须阻塞。
    binding.output_validation = replace(binding.output_validation, run_id="other-run")
    assert toolkit.pending_output_validation is not None
    assert binding.output_validation.blocking is True
    submission = await toolkit.submit_script()
    assert submission["code"] == "report_code_output_validation_pending"
    assert submission["details"]["status"] == "failed"


@pytest.mark.anyio
async def test_skipped_batch_calls_do_not_overwrite_failure(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    await toolkit.write_script("if True print('broken')\n")
    calls = [FunctionCall(function=functions[name], call_id=name, arguments={})
             for name in ("run_script", "submit_script", "read_script")]
    model = ReportingCodeOpenAIResponses(id="test", api_key="test")
    results = []
    _ = [event async for event in model.arun_function_calls(
        function_calls=calls, function_call_results=results,
        current_function_call_count=0, function_call_limit=20,
    )]
    assert len(results) == 3
    assert json.loads(results[-1].content)["status"] == "skipped"
    assert toolkit.last_tool == "run_script"
    assert toolkit.completed_tool_calls == 1
    assert toolkit.last_failure["code"] == "report_code_source_invalid"
    await FunctionCall(function=functions["submit_script"], arguments={}).aexecute()
    assert toolkit.last_tool == "submit_script"
    assert toolkit.last_failure["code"] == "report_code_source_invalid"


@pytest.mark.anyio
async def test_preflight_cannot_accept_changed_output(binding):  # noqa: F811
    async def preflight(receipt):
        await binding.workspace.awrite_text(
            binding.context.task_id, receipt.output_files[0].path, '{"changed": true}',
            overwrite=True,
        )
        return None

    toolkit = ReportingCodeModeToolkit(
        binding, ToolkitRuntime(), ReportingLspProcessManager(), output_preflight=preflight,
    )
    await toolkit.write_script(SOURCE)
    with pytest.raises(ReportingError, match="report_phase_artifact_changed"):
        await toolkit.run_script()
    assert (await toolkit.submit_script())["ok"] is False


@pytest.mark.anyio
async def test_preflight_exception_cannot_hide_changed_output(binding):  # noqa: F811
    async def preflight(receipt):
        await binding.workspace.awrite_text(
            binding.context.task_id,
            receipt.output_files[0].path,
            '{"changed": true}',
            overwrite=True,
        )
        raise OSError("validator unavailable")

    toolkit = ReportingCodeModeToolkit(
        binding,
        ToolkitRuntime(),
        ReportingLspProcessManager(),
        output_preflight=preflight,
    )
    await toolkit.write_script(SOURCE)

    with pytest.raises(ReportingError) as caught:
        await toolkit.run_script()

    assert caught.value.code == "report_phase_artifact_changed"
    assert toolkit.terminal_failure is caught.value
    assert (await toolkit.submit_script())["ok"] is False


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_evidence_repair_prompt_retains_bounded_field_diagnostic(workspace):  # noqa: F811
    prompts = []

    class Agent:
        tool_call_limit = 20

        async def arun(self, prompt, **_kwargs):
            prompts.append(json.loads(prompt))

    summary = "findings.0.rows: Field required; " + "后续错误" * 1000
    runner = ReportingCodeGenerationRunner(
        lambda _tools: Agent(),
        SimpleNamespace(shutdown=AsyncMock()),
        ReportingLspProcessManager(),
    )
    with pytest.raises(ReportingError) as caught:
        await runner.run(
            _task_context(workspace), workspace, {}, run_context=_run_context(),
            diagnostic={
                "code": "report_analysis_evidence_schema_invalid",
                "message": "补充 evidence 不符合机器结构契约。",
                "details": {
                    "issueSummary": summary,
                    "issues": [{"input": "private raw input"}],
                },
            },
        )

    assert caught.value.code == "report_code_generation_no_submission"
    details = prompts[0]["diagnostic"]["details"]
    assert details["issueSummary"].startswith("findings.0.rows: Field required;")
    assert len(details["issueSummary"]) <= MAX_DIAGNOSTIC_OUTPUT_LENGTH
    assert "private raw input" not in json.dumps(prompts)


@pytest.mark.anyio
async def test_run_returns_expression_value(binding):  # noqa: F811
    runtime = SimpleNamespace(execute=AsyncMock(return_value=CellResult(result="2")))
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run("1 + 1")

    assert result["ok"] is True
    assert result["result"] == "2"
    assert result["stdout"] == ""
    assert result["stderr"] == ""
    assert result["truncated"] == []


@pytest.mark.anyio
async def test_run_returns_bounded_exploration_variable_types(binding):  # noqa: F811
    runtime = SimpleNamespace(
        execute=AsyncMock(return_value=CellResult(result="loaded")),
        exploration_variables=AsyncMock(
            return_value={"df1": "DataFrame", "count": "int"}
        ),
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run("df1 = load()")

    assert result["explorationVariables"] == {"count": "int", "df1": "DataFrame"}
    runtime.exploration_variables.assert_awaited_once_with(
        binding.context.code_mode_session_id
    )


@pytest.mark.anyio
async def test_run_failure_returns_exploration_types_without_values(binding):  # noqa: F811
    runtime = SimpleNamespace(
        execute=AsyncMock(
            return_value=CellResult(status="error", traceback="NameError: missing")
        ),
        exploration_variables=AsyncMock(return_value={"df1": "DataFrame"}),
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run("missing")

    assert result["ok"] is False
    assert result["details"]["explorationVariables"] == {"df1": "DataFrame"}
    assert "value" not in json.dumps(result["details"]["explorationVariables"])


@pytest.mark.anyio
async def test_run_aborted_cell_skips_exploration_and_requires_restart(binding):  # noqa: F811
    runtime = SimpleNamespace(
        execute=AsyncMock(return_value=CellResult(status="aborted", traceback="cancelled")),
        exploration_variables=AsyncMock(return_value={"df1": "DataFrame"}),
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run("long_running_cell()")

    assert result["ok"] is False
    assert result["details"]["nextTools"] == ["restart_code_mode"]
    assert "explorationVariables" not in result["details"]
    runtime.exploration_variables.assert_not_awaited()


@pytest.mark.anyio
async def test_run_kernel_busy_error_skips_exploration_and_requires_restart(binding):  # noqa: F811
    runtime = SimpleNamespace(
        execute=AsyncMock(
            side_effect=ReportingError(
                "report_code_mode_execution_failed",
                "CodeMode 执行失败。",
                details={"errorType": "KernelBusyError"},
            )
        ),
        exploration_variables=AsyncMock(return_value={"df1": "DataFrame"}),
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run("next_cell()")

    assert result["ok"] is False
    assert result["details"]["nextTools"] == ["restart_code_mode"]
    assert "explorationVariables" not in result["details"]
    runtime.exploration_variables.assert_not_awaited()


@pytest.mark.anyio
async def test_run_transport_failure_returns_exploration_variable_types(binding):  # noqa: F811
    runtime = SimpleNamespace(
        execute=AsyncMock(
            side_effect=ReportingError(
                "report_code_mode_execution_failed",
                "CodeMode 执行失败。",
                details={"errorType": "KernelDiedError"},
            )
        ),
        exploration_variables=AsyncMock(return_value={"df1": "DataFrame"}),
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run("df1")

    assert result["ok"] is False
    assert result["details"]["explorationVariables"] == {"df1": "DataFrame"}


@pytest.mark.anyio
async def test_run_variable_query_failure_does_not_replace_success(binding):  # noqa: F811
    runtime = SimpleNamespace(
        execute=AsyncMock(return_value=CellResult(result="42")),
        exploration_variables=AsyncMock(side_effect=RuntimeError("private failure")),
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run("40 + 2")

    assert result["ok"] is True
    assert result["result"] == "42"
    assert "explorationVariables" not in result
    assert "private failure" not in json.dumps(result)


@pytest.mark.anyio
async def test_run_bounds_and_filters_exploration_variable_types(binding):  # noqa: F811
    variables = {
        "_private": "secret",
        **{f"value_{'x' * 100}_{index:02d}": "x" * 200 for index in range(40)},
        "not-valid": "str",
    }
    runtime = SimpleNamespace(
        execute=AsyncMock(
            return_value=CellResult(result="loaded" * 5000, stdout="rows" * 5000)
        ),
        exploration_variables=AsyncMock(return_value=variables),
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run("value_00 = load()")

    summary = result["explorationVariables"]
    assert len(summary) == 32
    assert list(summary) == sorted(summary)
    assert "_private" not in summary
    assert "not-valid" not in summary
    assert all(len(value.encode("utf-8")) <= 128 for value in summary.values())
    diagnostics = {
        key: result[key]
        for key in ("result", "stdout", "stderr", "explorationVariables")
        if key in result
    }
    assert len(json.dumps(diagnostics, ensure_ascii=False).encode()) <= MAX_DIAGNOSTIC_BYTES


@pytest.mark.anyio
async def test_restart_code_mode_reports_exploration_variables_cleared(binding):  # noqa: F811
    runtime = SimpleNamespace(shutdown=AsyncMock())
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.restart_code_mode()

    assert result == {
        "ok": True,
        "explorationVariables": {},
        "variablesCleared": True,
    }


@pytest.mark.anyio
async def test_run_bounds_output_and_preserves_truncation(binding):  # noqa: F811
    cell = CellResult(
        result=("表格\\\"\n" * 5000) + "last row",
        stdout="noise" * 5000,
        stderr="warning",
        truncated=["stderr"],
    )
    runtime = SimpleNamespace(execute=AsyncMock(return_value=cell))
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run("df")

    assert result["ok"] is True
    assert result["result"].endswith("last row")
    assert result["truncated"] == ["result", "stderr", "stdout"]
    outputs = {key: result[key] for key in ("result", "stdout", "stderr") if key in result}
    assert len(json.dumps(outputs, ensure_ascii=False).encode()) <= MAX_DIAGNOSTIC_BYTES


@pytest.mark.anyio
async def test_analysis_run_has_no_separate_budget(binding):  # noqa: F811
    runtime = ToolkitRuntime()
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    for _ in range(10):
        assert (await toolkit.run("1 + 1"))["ok"] is True

    assert (await toolkit.write_script(SOURCE))["ok"] is True
    assert (await toolkit.run_script())["ok"] is True
    assert (await toolkit.submit_script())["ok"] is True


@pytest.mark.anyio
async def test_visualization_run_has_no_separate_budget(workspace):  # noqa: F811
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskBinding

    runtime = ToolkitRuntime()
    visual_binding = ReportingCodingTaskBinding(
        _visualization_task_context(workspace), workspace
    )
    toolkit = ReportingCodeModeToolkit(
        visual_binding, runtime, ReportingLspProcessManager()
    )

    for _ in range(10):
        assert (await toolkit.run("1 + 1"))["ok"] is True


@pytest.mark.anyio
async def test_run_batch_exceeds_former_exploration_limit(
    binding,  # noqa: F811
):
    runtime = SimpleNamespace(execute=AsyncMock(return_value=CellResult(result="ok")))
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    calls = [
        FunctionCall(
            function=functions["run"],
            call_id=f"snippet-{index}",
            arguments={"code": "1 + 1"},
        )
        for index in range(6)
    ]
    results: list[Message] = []
    model = ReportingCodeOpenAIResponses(id="test", api_key="test")

    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=calls,
            function_call_results=results,
            current_function_call_count=0,
            function_call_limit=20,
        )
    ]

    assert runtime.execute.await_count == 6
    assert len(results) == 6
    assert all(literal_eval(result.content)["ok"] for result in results)
    assert (await toolkit.write_script(SOURCE))["ok"] is True


@pytest.mark.anyio
async def test_write_script_accepts_large_workspace_backed_source(workspace):  # noqa: F811
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskBinding

    context = replace(_task_context(workspace), max_source_bytes=_CODING_SCRIPT_MAX_BYTES)
    large_binding = ReportingCodingTaskBinding(context, workspace)
    toolkit = ReportingCodeModeToolkit(large_binding, ToolkitRuntime(), ReportingLspProcessManager())
    source = ("# workspace-backed data stays outside source\n" * 5000) + "print('ok')"

    result = await toolkit.write_script(source)

    assert result["ok"] is True
    assert result["size"] > 128 * 1024


@pytest.mark.anyio
async def test_runner_rejects_missing_authorized_input_before_model_call(workspace):  # noqa: F811
    context = replace(
        _task_context(workspace),
        authorized_read_paths=("datasets/missing.csv",),
    )
    agent_factory = AsyncMock()
    runner = ReportingCodeGenerationRunner(
        agent_factory,
        ToolkitRuntime(),
        ReportingLspProcessManager(),
    )

    with pytest.raises(ReportingError) as caught:
        await runner.run(context, workspace, {}, run_context=_run_context())

    assert caught.value.code == "report_code_authorized_input_missing"
    assert caught.value.details == {"missingPaths": ["datasets/missing.csv"]}
    agent_factory.assert_not_called()


@pytest.mark.anyio
async def test_run_script_accepts_structured_zero_exit_code(
    binding, workspace  # noqa: F811
):
    class Runtime(ToolkitRuntime):
        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_text("task-1", "analysis/out.json", "{}")
            cell = SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)
            return ScriptProcessResult(cell=cell, exit_code=0)

    toolkit = ReportingCodeModeToolkit(binding, Runtime(), ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)

    result = await toolkit.run_script()

    assert result["ok"] is True
    assert binding.output_validation.status == "not_required"
    assert binding.output_validation.run_id == result["executionReceipt"]["runId"]


@pytest.mark.anyio
async def test_run_script_rejects_structured_nonzero_exit_code(
    binding  # noqa: F811
):
    cell = SimpleNamespace(status="error", stdout="", stderr="boom", traceback=None)
    runtime = SimpleNamespace(
        execute_script_process=AsyncMock(
            return_value=ScriptProcessResult(cell=cell, exit_code=7)
        )
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)

    result = await toolkit.run_script()

    assert result["ok"] is False
    assert result["code"] == "report_code_mode_execution_failed"


@pytest.mark.anyio
async def test_run_script_rejects_missing_structured_exit_receipt(
    binding  # noqa: F811
):
    cell = SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)
    runtime = SimpleNamespace(
        execute_script_process=AsyncMock(
            return_value=ScriptProcessResult(cell=cell, exit_code=None)
        )
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)

    result = await toolkit.run_script()

    assert result == {
        "ok": False,
        "status": "rejected",
        "code": "report_code_exit_receipt_invalid",
        "message": "Coding Agent 脚本退出码回执缺失或无效。",
        "details": {"nextTools": ["read_script", "edit_script", "run_script"]},
    }


@pytest.mark.anyio
async def test_visualization_last_generation_failure_preserves_original_error():
    from smart_reporting.reporting.tests.test_reporting_code_diagnostics import (
        _visualization_plan,
    )

    degradable = ReportingError("report_chart_file_missing", "missing")
    final = ReportingError("report_code_generation_agent_failed", "provider failed")
    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=AsyncMock(side_effect=[degradable, degradable, degradable, final]),
        submit=AsyncMock(),
    )

    with pytest.raises(ReportingError) as caught:
        await workflow.run(
            {"visualizationWorkspace": {"scriptPath": "charts/charts.py"}},
            _run_context(),
        )

    assert caught.value is final


@pytest.mark.anyio
async def test_visualization_recoverable_nondegradable_failure_capped_at_max_generate_attempts():
    """既不在 _NON_RECOVERABLE_CODES 也不在 _DEGRADABLE_CODES 的失败（例如未预见的
    瞬时错误）必须按 _MAX_GENERATE_ATTEMPTS 独立封顶，不能借用可降级失败更大的重试
    预算——否则每次都会多烧一次昂贵的模型调用才放弃。"""
    from smart_reporting.reporting.tests.test_reporting_code_diagnostics import (
        _visualization_plan,
    )
    from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
        _MAX_GENERATE_ATTEMPTS,
    )

    recoverable = ReportingError("report_visualization_transient_error", "transient")
    run_code = AsyncMock(side_effect=[recoverable] * (_MAX_GENERATE_ATTEMPTS + 2))
    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=run_code,
        submit=AsyncMock(),
    )

    with pytest.raises(ReportingError) as caught:
        await workflow.run(
            {"visualizationWorkspace": {"scriptPath": "charts/charts.py"}},
            _run_context(),
        )

    assert caught.value is recoverable
    assert run_code.await_count == _MAX_GENERATE_ATTEMPTS


def test_short_diagnostic_flattens_last_tool_failure_execution_context():
    diagnostic = ReportingCodeGenerationRunner._short_diagnostic(
        {
            "code": "report_code_generation_no_submission",
            "message": "failed",
            "details": {
                "lastFailure": {
                    "code": "report_code_mode_execution_failed",
                    "message": "script failed",
                    "details": {
                        "stderr": "ValueError: bad input",
                        "traceback": "frame\nValueError: bad input",
                    },
                }
            },
        }
    )

    assert diagnostic["details"]["toolCode"] == "report_code_mode_execution_failed"
    assert diagnostic["details"]["toolMessage"] == "script failed"
    assert diagnostic["details"]["stderr"] == "ValueError: bad input"
    assert diagnostic["details"]["traceback"].endswith("ValueError: bad input")


def test_short_diagnostic_prefers_pending_output_validation_over_stale_last_failure():
    """lastFailure 可能已被之后一次无关的探索失败覆盖；仍在阻塞提交的
    pendingOutputValidation 才是当前真实原因，必须优先展示。"""
    diagnostic = ReportingCodeGenerationRunner._short_diagnostic(
        {
            "code": "report_code_generation_no_submission",
            "message": "failed",
            "details": {
                "lastFailure": {
                    "code": "report_code_mode_execution_failed",
                    "message": "unrelated exploration failure",
                },
                "pendingOutputValidation": {
                    "code": "report_analysis_evidence_schema_invalid",
                    "message": "evidence 结构校验未通过",
                    "details": {"issueSummary": "字段缺失"},
                },
            },
        }
    )

    assert diagnostic["details"]["toolCode"] == "report_analysis_evidence_schema_invalid"
    assert diagnostic["details"]["toolMessage"] == "evidence 结构校验未通过"
    assert diagnostic["details"]["issueSummary"] == "字段缺失"


def test_visualization_repair_diagnostic_prefers_pending_output_validation():
    """visualization 的 _repair_diagnostic 同样必须优先反映 pendingOutputValidation，
    而不是可能已过期的 lastFailure。"""
    from smart_reporting.reporting.tests.test_reporting_code_diagnostics import (
        _visualization_plan,
    )
    from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
        _repair_diagnostic,
    )

    error = ReportingError(
        "report_code_generation_no_submission",
        "failed",
        details={
            "lastFailure": {
                "code": "report_code_mode_execution_failed",
                "message": "unrelated exploration failure",
            },
            "pendingOutputValidation": {
                "code": "report_visualization_evidence_schema_invalid",
                "message": "图表数据契约校验未通过",
            },
        },
    )

    diagnostic = _repair_diagnostic(_visualization_plan(), error, "charts/charts.py")

    assert diagnostic["details"]["toolCode"] == "report_visualization_evidence_schema_invalid"
    assert diagnostic["details"]["toolMessage"] == "图表数据契约校验未通过"


@pytest.mark.anyio
async def test_runner_raises_terminal_tool_failure_after_agno_converts_exception(workspace):  # noqa: F811
    class Agent:
        def __init__(self, tools):
            self.tools = {tool.name: tool for tool in tools}

        async def arun(self, *_args, **_kwargs):
            await FunctionCall(
                function=self.tools["write_script"], arguments={"source": SOURCE}
            ).aexecute()
            await FunctionCall(function=self.tools["run_script"], arguments={}).aexecute()
            return SimpleNamespace(messages=[])

    async def mutate_output(receipt):
        await workspace.awrite_text(
            "task-1", receipt.output_files[0].path, '{"changed":true}', overwrite=True
        )
        return None

    runner = ReportingCodeGenerationRunner(
        Agent, ToolkitRuntime(), ReportingLspProcessManager()
    )

    with pytest.raises(ReportingError) as caught:
        await runner.run(
            _task_context(workspace),
            workspace,
            {},
            run_context=_run_context(),
            output_preflight=mutate_output,
        )

    assert caught.value.code == "report_phase_artifact_changed"


@pytest.mark.anyio
@pytest.mark.parametrize("model_id", ["deepseek-v4-flash-0731", "qwen3.8-flash"])
@pytest.mark.parametrize("budget,effort", [(0, None), (2048, "high"), (8192, "max")])
async def test_code_thinking_decision_reaches_responses_wire(model_id, budget, effort, monkeypatch):
    requests = []

    async def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "resp-1", "created_at": 0, "model": model_id,
            "object": "response", "status": "completed", "output": [
                {"id": "rs-summary", "type": "reasoning", "summary": [
                    {"type": "summary_text", "text": "先检查输入，再执行脚本。"},
                ]},
            ],
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })

    client = AsyncOpenAI(
        api_key="test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    client._platform = "Linux"
    model = ReportingCodeOpenAIResponses(
        id=model_id, api_key="test", async_client=client,
        base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/api/v2",
        extra_body={"enable_thinking": True, "thinking_budget": 4096},
        reasoning_effort="high", reasoning={"effort": "high"}, temperature=0.2,
    )
    monkeypatch.setattr(model, "count_tokens", lambda *args, **kwargs: 1)
    decision = ThinkingDecision(
        operation="analysis_script", complexity="standard", enabled=budget > 0,
        reasoning_effort=effort, thinking_budget=budget, attempt=1, reason="test",
    )
    tools = [Function(name="write_script", parameters={"type": "object", "properties": {}})]
    try:
        with bind_reporting_thinking(decision):
            response = await model.aresponse([Message(role="user", content="write")], tools=tools)
            assert response.reasoning_content == "先检查输入，再执行脚本。"
        await model.aresponse([Message(role="user", content="next task")], tools=tools)
    finally:
        await client.close()

    selected, original = requests
    assert selected["enable_thinking"] is (budget > 0)
    assert "thinking_budget" not in selected
    if budget:
        expected_effort = "xhigh" if effort == "max" and model_id.startswith("qwen") else effort
        assert selected["reasoning"]["effort"] == expected_effort
        assert selected["reasoning"]["effort"] == expected_effort
        assert selected["reasoning"]["summary"] == "auto"
    else:
        assert selected["reasoning"]["effort"] == "none"
        assert "summary" not in selected.get("reasoning", {})
    assert selected["temperature"] == 0.2
    assert selected["tools"][0]["type"] == "custom"
    assert selected["tool_choice"] == "auto"
    assert original["enable_thinking"] is True
    assert "thinking_budget" not in original
    assert original["reasoning"] == {"effort": "high", "summary": "auto"}
    assert model.extra_body == {"enable_thinking": True, "thinking_budget": 4096}
    assert model.reasoning == {"effort": "high"}


@pytest.mark.parametrize(
    "base_url,extra_body,expected_extra_body",
    [
        (
            "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v2",
            {"enable_thinking": True, "thinking_budget": 4096},
            {"enable_thinking": True},
        ),
        (
            "http://localhost:8000/v1",
            {"chat_template_kwargs": {}, "thinking_budget": 4096},
            {"chat_template_kwargs": {"enable_thinking": True}},
        ),
        (
            "https://api.openai.com/v1",
            {"enable_thinking": True, "thinking_budget": 4096},
            None,
        ),
    ],
)
def test_responses_thinking_transport_is_projected_per_provider(
    base_url, extra_body, expected_extra_body
):
    model = ReportingCodeOpenAIResponses(
        id="reasoning-model",
        api_key="test",
        base_url=base_url,
        extra_body=extra_body,
        reasoning_effort="high",
        reasoning={"effort": "high", "summary": "detailed"},
    )

    params = model._phase_request_model([]).get_request_params()

    assert params.get("extra_body") == expected_extra_body
    assert params["reasoning"] == {"effort": "high", "summary": "detailed"}


@pytest.mark.anyio
@pytest.mark.parametrize("large_output", [False, True])
async def test_run_script_missing_output_preserves_execution_diagnostics(binding, large_output):  # noqa: F811
    stdout = ("输出\n" * 10000 if large_output else "computed result")
    cell = CellResult(stdout=stdout, stderr="warning", truncated=["stderr"])
    runtime = SimpleNamespace(
        execute_script_process=AsyncMock(return_value=ScriptProcessResult(cell=cell, exit_code=0))
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script("print('computed result')\n")

    result = await toolkit.run_script()

    assert result["code"] == "report_code_declared_output_missing"
    details = result["details"]
    assert details["path"] == "analysis/out.json"
    assert details["exitCode"] == 0
    assert details["stderr"] == "warning"
    assert details["stdout"]
    assert result["truncated"] == (["stderr", "stdout"] if large_output else ["stderr"])
    assert len(json.dumps(details, ensure_ascii=False).encode()) <= MAX_DIAGNOSTIC_BYTES
    if not large_output:
        assert details["stdout"] == stdout
    assert toolkit.binding.execution_receipt is None
