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
async def test_run_snippet_returns_expression_value(binding):  # noqa: F811
    runtime = SimpleNamespace(execute=AsyncMock(return_value=CellResult(result="2")))
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run_snippet("1 + 1")

    assert result["ok"] is True
    assert result["result"] == "2"
    assert result["stdout"] == ""
    assert result["stderr"] == ""
    assert result["truncated"] == []


@pytest.mark.anyio
async def test_run_snippet_bounds_output_and_preserves_truncation(binding):  # noqa: F811
    cell = CellResult(
        result=("表格\\\"\n" * 5000) + "last row",
        stdout="noise" * 5000,
        stderr="warning",
        truncated=["stderr"],
    )
    runtime = SimpleNamespace(execute=AsyncMock(return_value=cell))
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.run_snippet("df")

    assert result["ok"] is True
    assert result["result"].endswith("last row")
    assert result["truncated"] == ["result", "stderr", "stdout"]
    outputs = {key: result[key] for key in ("result", "stdout", "stderr") if key in result}
    assert len(json.dumps(outputs, ensure_ascii=False).encode()) <= MAX_DIAGNOSTIC_BYTES


@pytest.mark.anyio
async def test_analysis_run_snippet_budget_preserves_formal_delivery(binding):  # noqa: F811
    runtime = ToolkitRuntime()
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    for _ in range(4):
        assert (await toolkit.run_snippet("1 + 1"))["ok"] is True

    rejected = await toolkit.run_snippet("1 + 1")

    assert rejected == {
        "ok": False,
        "status": "rejected",
        "code": "report_code_exploration_budget_exhausted",
        "message": "交互探索额度已用尽；请立即更新并运行正式脚本，然后提交交付结果。",
        "details": {
            "used": 4,
            "limit": 4,
            "requiredNextTools": ["write_script", "run_script", "submit_script"],
        },
    }
    assert (await toolkit.write_script(SOURCE))["ok"] is True
    assert (await toolkit.run_script())["ok"] is True
    assert (await toolkit.submit_script())["ok"] is True


@pytest.mark.anyio
async def test_visualization_run_snippet_budget_is_eight(workspace):  # noqa: F811
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskBinding

    runtime = ToolkitRuntime()
    visual_binding = ReportingCodingTaskBinding(
        _visualization_task_context(workspace), workspace
    )
    toolkit = ReportingCodeModeToolkit(
        visual_binding, runtime, ReportingLspProcessManager()
    )

    for _ in range(8):
        assert (await toolkit.run_snippet("1 + 1"))["ok"] is True

    rejected = await toolkit.run_snippet("1 + 1")

    assert rejected["code"] == "report_code_exploration_budget_exhausted"
    assert rejected["details"]["used"] == 8
    assert rejected["details"]["limit"] == 8


@pytest.mark.anyio
async def test_run_snippet_budget_stops_remaining_batch_but_allows_next_delivery(
    binding,  # noqa: F811
):
    runtime = SimpleNamespace(execute=AsyncMock(return_value=CellResult(result="ok")))
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    calls = [
        FunctionCall(
            function=functions["run_snippet"],
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

    assert runtime.execute.await_count == 4
    assert literal_eval(results[4].content)["code"] == (
        "report_code_exploration_budget_exhausted"
    )
    assert json.loads(results[5].content)["status"] == "skipped"
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
async def test_run_script_tolerates_truncated_exit_marker_when_status_ok(
    binding, workspace  # noqa: F811
):
    """stderr 中的 __REPORT_EXIT__ 标记只是交叉校验；status=="ok" 时标记缺失
    （截断或与 stdout 合并）不得让已经成功的脚本被误判失败。"""

    class Runtime(ToolkitRuntime):
        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_text("task-1", "analysis/out.json", "{}")
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

    toolkit = ReportingCodeModeToolkit(binding, Runtime(), ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)

    result = await toolkit.run_script()

    assert result["ok"] is True


@pytest.mark.anyio
async def test_run_script_fails_closed_on_exit_marker_status_mismatch(
    binding  # noqa: F811
):
    """cell status=="ok" 但退出码标记解析出非零值属于真实异常（例如宿主与
    IPython 状态不一致），必须拒绝而不是信任 status。"""
    runtime = SimpleNamespace(
        execute_script_process=AsyncMock(
            return_value=SimpleNamespace(
                status="ok", stdout="", stderr="boom\n__REPORT_EXIT__=7\n", traceback=None
            )
        )
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)

    result = await toolkit.run_script()

    assert result["ok"] is False
    assert result["code"] == "report_code_mode_execution_failed"
    assert result["details"]["exitCode"] == 7


@pytest.mark.anyio
async def test_run_script_finds_exit_marker_in_stdout_when_streams_merged(
    binding  # noqa: F811
):
    """某些运行环境会把 stderr 合并进 stdout；退出码标记必须在两个流都能查找到。"""
    runtime = SimpleNamespace(
        execute_script_process=AsyncMock(
            return_value=SimpleNamespace(
                status="ok", stdout="__REPORT_EXIT__=9\n", stderr="", traceback=None
            )
        )
    )
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)

    result = await toolkit.run_script()

    assert result["ok"] is False
    assert result["code"] == "report_code_mode_execution_failed"
    assert result["details"]["exitCode"] == 9


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
            "object": "response", "status": "completed", "output": [],
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })

    client = AsyncOpenAI(
        api_key="test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    client._platform = "Linux"
    model = ReportingCodeOpenAIResponses(
        id=model_id, api_key="test", async_client=client,
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
            await model.aresponse([Message(role="user", content="write")], tools=tools)
        await model.aresponse([Message(role="user", content="next task")], tools=tools)
    finally:
        await client.close()

    selected, original = requests
    assert selected["enable_thinking"] is (budget > 0)
    if budget:
        assert selected["thinking_budget"] == budget
        expected_effort = "xhigh" if effort == "max" and model_id.startswith("qwen") else effort
        assert selected["reasoning"]["effort"] == expected_effort
    else:
        assert "thinking_budget" not in selected
        assert "effort" not in selected.get("reasoning", {})
    assert selected["temperature"] == 0.2
    assert selected["tools"][0]["type"] == "custom"
    assert selected["tool_choice"] == "auto"
    assert original["enable_thinking"] is True
    assert original["thinking_budget"] == 4096
    assert original["reasoning"]["effort"] == "high"
    assert model.extra_body == {"enable_thinking": True, "thinking_budget": 4096}
    assert model.reasoning == {"effort": "high"}
