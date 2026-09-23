"""Reporting 交付状态必须跨上下文压缩保留。"""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.models.message import Message
from agno.tools.function import FunctionCall

from smart_reporting.reporting.agent import _INTERACTIVE_CODE_INSTRUCTIONS
from smart_reporting.reporting.code_agent.delivery import (
    _visual_review_model_receipt,
    merge_visual_failures,
)
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.code_mode import ScriptProcessResult
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_code_edit import edit_patch
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    VISUAL_SOURCE,
    ToolkitRuntime,
    _failed_cell,
    _prepared_visualization_toolkit,
    _visual_receipt,
    binding,  # noqa: F401
    workspace,  # noqa: F401
)
from smart_reporting.reporting.workflow.checkpoint import (
    ChartVisualInspectionIssue,
    ChartVisualInspectionReceipt,
)
from smart_reporting.workspace import WorkspaceError


@pytest.mark.anyio
async def test_plotly_sidecar_is_not_scheduled_for_visual_review(workspace):  # noqa: F811
    task_binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, ToolkitRuntime(),
    )
    sidecar = output.model_copy(update={"path": "charts/chart.plotly.json"})
    task_binding.execution_receipt = task_binding.execution_receipt.model_copy(
        update={"output_files": (output, sidecar)},
    )
    toolkit._declared_output_identities = AsyncMock(return_value=(output, sidecar))
    await toolkit.refresh_delivery_state()
    assert toolkit.delivery_state()["nextReviewPaths"] == [output.path]
    task_binding.visual_inspection_receipts[output.path] = _visual_receipt(output)
    await toolkit.refresh_delivery_state()
    assert toolkit.delivery_state()["nextReviewPaths"] == []
    assert toolkit.delivery_state()["nextTools"] == ["submit_script"]


@pytest.mark.anyio
@pytest.mark.parametrize("code", [
    "report_chart_file_missing", "report_chart_source_invalid", "report_chart_blank",
    "report_code_visual_review_unavailable",
])
async def test_visual_check_failure_routes_repair_or_stops(workspace, code):  # noqa: F811
    reviewer = AsyncMock()
    reviewer.review.side_effect = ReportingError(code, "private provider body")
    task_binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, ToolkitRuntime(), reviewer,
    )
    function = next(tool for tool in toolkit.tool_functions if tool.name == "view_image")
    call = FunctionCall(function=function, arguments={"path": output.path})
    await call.aexecute()
    await toolkit.refresh_delivery_state()
    state = toolkit.delivery_state()
    assert call.result["code"] == code
    assert "private provider body" not in str(call.result)
    assert not task_binding.visual_inspection_receipts
    if code == "report_code_visual_review_unavailable":
        assert function.stop_after_tool_call
        assert toolkit.terminal_failure is not None
        assert state["nextTools"] == []
    else:
        assert toolkit.terminal_failure is None
        assert state["nextTools"] == ["read_script", "edit_script", "run_script"]
        assert state["lastFailure"]["details"]["path"] == output.path


def test_visual_failures_merge_identical_issues_across_paths():
    merged = merge_visual_failures([
        {
            "path": "charts/a.png",
            "summary": "需修订",
            "issues": [{"category": "text_overlap", "severity": "critical", "description": "标签重叠"}],
            "suggestions": ["调整布局"],
        },
        {
            "path": "charts/b.png",
            "summary": "需修订",
            "issues": [{"category": "text_overlap", "severity": "critical", "description": "标签重叠"}],
            "suggestions": ["调整布局"],
        },
    ])
    assert merged == [{
        "path": "charts/a.png",
        "paths": ["charts/a.png", "charts/b.png"],
        "summary": "需修订",
        "issues": [{"category": "text_overlap", "severity": "critical", "description": "标签重叠"}],
        "suggestions": ["调整布局"],
    }]


def test_visual_review_model_receipt_hides_non_blocking_text() -> None:
    receipt = ChartVisualInspectionReceipt(
        sourcePath="charts/a.png",
        sha256="a" * 64,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=False,
        issues=(
            ChartVisualInspectionIssue(
                category="missing_units",
                severity="warning",
                description="不得进入模型上下文的 warning。",
            ),
        ),
        summary="不得进入模型上下文的摘要。",
        warnings=("不得进入模型上下文的 warnings 字段。",),
        suggestions=("不得进入模型上下文的建议。",),
    )

    assert _visual_review_model_receipt(receipt) == {
        "sourcePath": "charts/a.png",
        "sha256": "a" * 64,
        "visualReviewStatus": "passed",
        "reviewed": True,
        "requiresRevision": False,
        "warningCount": 1,
        "message": "非阻断问题已记录，无需修改。",
    }


def test_visual_review_model_receipt_keeps_only_critical_issues() -> None:
    receipt = ChartVisualInspectionReceipt(
        sourcePath="charts/a.png",
        sha256="a" * 64,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=True,
        issues=(
            ChartVisualInspectionIssue(
                category="text_overlap",
                severity="critical",
                description="关键标签无法辨认。",
            ),
            ChartVisualInspectionIssue(
                category="missing_units",
                severity="warning",
                description="不得进入模型上下文的 warning。",
            ),
        ),
        summary="不得进入模型上下文的混合摘要。",
        suggestions=("无法确定属于哪个 issue 的建议。",),
    )

    assert _visual_review_model_receipt(receipt) == {
        "sourcePath": "charts/a.png",
        "sha256": "a" * 64,
        "visualReviewStatus": "passed",
        "reviewed": True,
        "requiresRevision": True,
        "criticalIssues": [
            {
                "category": "text_overlap",
                "severity": "critical",
                "description": "关键标签无法辨认。",
            }
        ],
    }


def test_visual_review_model_receipt_hides_unlinked_suggestions_for_critical_issues() -> None:
    receipt = ChartVisualInspectionReceipt(
        sourcePath="charts/a.png",
        sha256="a" * 64,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=True,
        issues=(
            ChartVisualInspectionIssue(
                category="text_overlap",
                severity="critical",
                description="关键标签无法辨认。",
            ),
        ),
        suggestions=("移动关键标签并重新审查。", "可选改进：更换配色和字体。"),
    )

    projected = _visual_review_model_receipt(receipt)
    assert "suggestions" not in projected
    assert projected["criticalIssues"][0]["description"] == "关键标签无法辨认。"
    assert receipt.suggestions == ("移动关键标签并重新审查。", "可选改进：更换配色和字体。")


def test_visual_review_model_receipt_hides_suggestions_when_independent_warnings_exist() -> None:
    receipt = ChartVisualInspectionReceipt(
        sourcePath="charts/a.png",
        sha256="a" * 64,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=True,
        issues=(
            ChartVisualInspectionIssue(
                category="text_overlap",
                severity="critical",
                description="关键标签无法辨认。",
            ),
        ),
        warnings=("warning-only issue",),
        suggestions=("不要把这条 warning 建议传给模型。",),
    )

    assert "suggestions" not in _visual_review_model_receipt(receipt)


@pytest.mark.anyio
async def test_first_write_failure_code_survives_successful_write(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    write = next(tool for tool in toolkit.tool_functions if tool.name == "write_script")
    rejected = FunctionCall(function=write, arguments={"source": '{"code": "print(1)"}'})
    await rejected.aexecute()
    assert rejected.result["ok"] is False
    assert rejected.result["code"] == "report_code_input_wrapped"
    await FunctionCall(function=write, arguments={"source": SOURCE}).aexecute()
    assert toolkit.first_script_success is False
    assert toolkit.first_script_failure_code == "report_code_input_wrapped"


@pytest.mark.anyio
async def test_delivery_state_tracks_write_run_submit_and_invalidates_edit(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    await toolkit.refresh_delivery_state()
    assert toolkit.delivery_state()["nextTools"] == ["write_script"]
    await FunctionCall(function=functions["write_script"], arguments={"source": SOURCE}).aexecute()
    assert toolkit.first_script_success is True
    assert toolkit.delivery_state()["nextTools"] == ["read_script", "edit_script", "run_script"]
    await FunctionCall(function=functions["run_script"], arguments={}).aexecute()
    assert toolkit.first_run_success is True
    state = toolkit.delivery_state()
    assert state["nextTools"] == ["submit_script"]
    assert state["execution"]["valid"] is True
    assert state["script"]["sha256"] == binding.execution_receipt.source_file.sha256
    await FunctionCall(function=functions["write_script"], arguments={"source": SOURCE + "\n# changed"}).aexecute()
    assert toolkit.delivery_state()["execution"] is None
    assert toolkit.delivery_state()["nextTools"] == ["read_script", "edit_script", "run_script"]
    await FunctionCall(function=functions["run_script"], arguments={}).aexecute()
    await FunctionCall(function=functions["submit_script"], arguments={}).aexecute()
    assert toolkit.delivery_state()["submitted"] is True
    assert toolkit.delivery_state()["nextTools"] == []
    assert toolkit.tool_call_metrics() == {
        "write_script": 2,
        "run_script": 2,
        "submit_script": 1,
    }


@pytest.mark.anyio
async def test_successive_patches_remain_declared_until_execution(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    write = FunctionCall(function=functions["write_script"], arguments={"source": SOURCE})
    await write.aexecute()
    model = ReportingCodeOpenAIResponses(id="test", api_key="test")
    model.configure_code_run(
        toolkit.tool_functions, max_model_requests=10,
        delivery_state_reader=toolkit.delivery_state,
    )
    for old, new in [('write_text("{}")', 'write_text("{ }")'),
                     ('write_text("{ }")', 'write_text("{  }")')]:
        read = FunctionCall(function=functions["read_script"], arguments={})
        await read.aexecute()
        patch = edit_patch(read.result["source"], old, new)
        edit = FunctionCall(function=functions["edit_script"], arguments={"patch": patch})
        await edit.aexecute()
        assert edit.result["ok"] is True
        params = model.get_request_params(messages=[], tools=toolkit.tool_functions)
        assert {tool["name"]: tool["type"] for tool in params["tools"]} == {
            "read_script": "function", "edit_script": "custom", "run_script": "function",
        }
        assert params["parallel_tool_calls"] is True
    run = FunctionCall(function=functions["run_script"], arguments={})
    await run.aexecute()
    assert run.result["ok"] is True
    assert toolkit.delivery_state()["nextTools"] == ["submit_script"]


@pytest.mark.anyio
async def test_edit_script_replaces_one_exact_block_without_rewriting_whole_source(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    source = SOURCE + "print('done')\n"
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, source)
    before = await toolkit.read_script()

    result = await toolkit.edit_script(edit_patch(source, "print('done')", "print('finished')"))

    assert result["ok"] is True
    assert toolkit.first_patch_applied is True
    assert result["replacedOccurrences"] == 1
    after = await toolkit.read_script()
    assert "print('finished')" in after["source"]
    assert "print('done')" not in after["source"]
    assert len(after["source"]) <= len(before["source"]) + len("finished")


@pytest.mark.anyio
@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_first_repair_success_tracks_first_run_after_applied_patch(
    binding, repair_succeeds  # noqa: F811
):
    runtime = ToolkitRuntime()
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    write = FunctionCall(
        function=functions["write_script"], arguments={"source": SOURCE}
    )
    assert await write.aexecute()
    saved_source = write.result.get("savedSource") or SOURCE
    runtime.next_cell = _failed_cell("ValueError: first run failed")
    first_run = FunctionCall(function=functions["run_script"], arguments={})
    assert await first_run.aexecute()
    assert first_run.result["ok"] is False
    assert toolkit.first_run_success is False
    assert toolkit.first_run_failure_code == first_run.result["code"]
    assert toolkit.first_run_failure["code"] == first_run.result["code"]
    assert toolkit.first_run_failure["sourceSha256"] == hashlib.sha256(
        saved_source.encode()
    ).hexdigest()

    patch = edit_patch(
        saved_source,
        'Path("analysis/out.json").write_text("{}")',
        'output_path = Path("analysis/out.json")\noutput_path.write_text("{}")',
    )
    edit = FunctionCall(function=functions["edit_script"], arguments={"patch": patch})
    assert await edit.aexecute()
    assert edit.result["ok"] is True
    if not repair_succeeds:
        runtime.next_cell = _failed_cell("ValueError: repaired run failed")

    repaired_run = FunctionCall(function=functions["run_script"], arguments={})
    assert await repaired_run.aexecute()

    if repair_succeeds:
        assert toolkit.first_repair_success == "unknown"
        assert toolkit.first_run_failure["code"] == first_run.result["code"]
        submitted = FunctionCall(function=functions["submit_script"], arguments={})
        assert await submitted.aexecute()
        assert submitted.result["ok"] is True

    assert toolkit.first_repair_success is repair_succeeds


@pytest.mark.anyio
async def test_edit_script_rejects_ambiguous_match_without_mutating_source(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    source = "value = 1\nvalue = 1\n"
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, source)

    result = await toolkit.edit_script(edit_patch(source, "value = 1", "value = 2"))

    assert result["ok"] is False
    assert result["code"] == "report_code_script_edit_ambiguous"
    assert (await toolkit.read_script())["source"] == source


@pytest.mark.anyio
async def test_delivery_state_survives_rebase_without_parsing_tool_results(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)
    await toolkit.run_script()
    await toolkit.refresh_delivery_state()
    model = ReportingCodeOpenAIResponses(id="test", api_key="test")
    model.configure_code_run(toolkit.tool_functions, max_model_requests=30,
                             delivery_state_reader=toolkit.delivery_state)
    model._task_execution_input_token_budget = 1800
    model.count_tokens = lambda messages, *args, **kwargs: sum(len(str(m.content)) // 4 + 1 for m in messages)
    messages = [Message(role="user", content="complete task")]
    for index in range(12):
        messages.extend([
            Message(role="assistant", content="exploration " * 400),
            Message(role="user", content="continue"),
        ])
    projected = model._project(messages, (), {})
    states = [json.loads(m.content) for m in projected if isinstance(m.content, str)
              and '"marker":"REPORTING_CODE_DELIVERY_STATE"' in m.content]
    assert len(states) == 1
    assert states[0]["execution"]["valid"] is True
    assert states[0]["nextTools"] == ["submit_script"]
    assert len(projected) < len(messages)
    assert all("REPORTING_CODE_DELIVERY_STATE" not in str(m.content) for m in messages)


@pytest.mark.anyio
async def test_failure_identity_survives_delivery_without_disabling_repeat_detection(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)
    function = next(tool for tool in toolkit.tool_functions if tool.name == "edit_script")
    for call_id in ("failed-one", "failed-two"):
        call = FunctionCall(function=function, call_id=call_id, arguments={"patch": "invalid"})
        await call.aexecute()
        assert toolkit.delivery_state()["lastFailure"]["callId"] == call_id
    assert toolkit._repeated_failure_count == 2


@pytest.mark.anyio
async def test_delivery_feedback_tracks_visual_receipts_and_changed_output(workspace):  # noqa: F811
    task_binding, toolkit, output = await _prepared_visualization_toolkit(workspace, ToolkitRuntime())
    await toolkit.refresh_delivery_state()
    assert toolkit.delivery_state()["nextReviewPaths"] == [output.path]
    assert toolkit.delivery_state()["nextTools"] == ["view_image", "submit_script"]
    task_binding.visual_inspection_receipts[output.path] = _visual_receipt(output)
    await toolkit.refresh_delivery_state()
    assert toolkit.delivery_state()["nextTools"] == ["submit_script"]
    await workspace.awrite_text(task_binding.context.task_id, output.path, "changed", overwrite=True)
    await toolkit.refresh_delivery_state()
    assert toolkit.delivery_state()["execution"]["valid"] is False
    assert toolkit.delivery_state()["nextTools"] == ["read_script", "edit_script", "run_script"]


@pytest.mark.anyio
async def test_visual_warning_is_recorded_without_repair_loop(workspace):  # noqa: F811
    task_binding, toolkit, output = await _prepared_visualization_toolkit(workspace, ToolkitRuntime())
    await toolkit.refresh_delivery_state()
    task_binding.visual_inspection_receipts[output.path] = ChartVisualInspectionReceipt(
        sourcePath=output.path,
        sha256=output.sha256,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=False,
        issues=(ChartVisualInspectionIssue(
            category="text_overlap",
            severity="warning",
            description="图例轻微重叠，仅记录告警。",
        ),),
    )
    await toolkit.refresh_delivery_state()
    state = toolkit.delivery_state()
    assert state["nextTools"] == ["submit_script"]
    assert state["visualFailures"] == []


@pytest.mark.anyio
async def test_delivery_failed_execution_has_actionable_diagnostic(binding):  # noqa: F811
    runtime = ToolkitRuntime()
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    await FunctionCall(function=functions["write_script"], arguments={"source": SOURCE}).aexecute()
    runtime.next_cell = _failed_cell("ValueError: broken input")
    await FunctionCall(function=functions["run_script"], arguments={}).aexecute()
    state = toolkit.delivery_state()
    assert state["execution"] is None
    assert state["lastFailure"]["tool"] == "run_script"
    assert "ValueError: broken input" in state["lastFailure"]["details"]["traceback"]
    assert state["nextTools"] == ["read_script", "edit_script", "run_script"]


@pytest.mark.anyio
async def test_run_script_failure_receipt_advises_next_tools(binding, monkeypatch):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    monkeypatch.setattr(
        toolkit,
        "_validated_source_identity",
        AsyncMock(side_effect=WorkspaceError("missing")),
    )

    result = await toolkit.run_script()

    assert result["ok"] is False
    assert result["details"]["nextTools"] == ["write_script"]


@pytest.mark.anyio
async def test_run_script_failure_includes_matching_source_context_for_direct_edit(binding):  # noqa: F811
    runtime = ToolkitRuntime()
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    source = (
        "import pandas as pd\n"
        "frame = pd.DataFrame({'income_type': ['outpatient'], 'amount': [100]})\n"
        "summary = frame.groupby(['income_type', '收入类型构成（门诊/住院）'])['amount'].sum()\n"
        "print(summary)\n"
    )
    await toolkit.workspace.awrite_text(
        toolkit.context.task_id, toolkit.context.script_path, source
    )
    runtime.next_cell = _failed_cell(
        'Traceback (most recent call last):\n'
        '  File "analysis/a.py", line 3, in <module>\n'
        "KeyError: ('income_type', '收入类型构成（门诊/住院）')"
    )

    function = next(tool for tool in toolkit.tool_functions if tool.name == "run_script")
    call = FunctionCall(function=function, arguments={})
    await call.aexecute()
    result = call.result

    details = result["details"]
    assert details["sourceSha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert details["sourceStartLine"] == 1
    assert details["sourceEndLine"] == 4
    assert details["errorLine"] == 3
    assert details["sourceExcerpt"] == source
    assert details["errorType"] == "KeyError"
    assert details["allowedEditRegion"] == {
        "path": "analysis/a.py", "startLine": 1, "endLine": 4,
    }
    assert details["forbiddenEditRegions"][0]["outside"]["allowedStartLine"] == 1
    assert details["nextTools"] == ["edit_script", "run_script"]
    assert "write_script" not in details["nextTools"]

    failure = toolkit.delivery_state()["lastFailure"]
    assert failure["details"]["sourceSha256"] == details["sourceSha256"]
    assert failure["details"]["sourceExcerpt"] == source


@pytest.mark.anyio
async def test_run_script_failure_points_to_innermost_script_frame(binding):  # noqa: F811
    runtime = ToolkitRuntime()
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    source = "".join(f"value_{line} = {line}\n" for line in range(1, 31))
    await toolkit.workspace.awrite_text(
        toolkit.context.task_id, toolkit.context.script_path, source
    )
    runtime.next_cell = _failed_cell(
        'Traceback (most recent call last):\n'
        '  File "analysis/a.py", line 28, in <module>\n'
        '  File "analysis/a.py", line 20, in build_chart\n'
        '  File "analysis/a.py", line 4, in parse_number\n'
        'ValueError: null value'
    )

    result = await toolkit.run_script()

    assert result["details"]["errorLine"] == 4
    assert "value_4 = 4" in result["details"]["sourceExcerpt"]


@pytest.mark.anyio
async def test_run_script_failure_does_not_offer_stale_source_excerpt(binding):  # noqa: F811
    class ChangingRuntime(ToolkitRuntime):
        async def execute_script_process(self, session_id, received_workspace, path, **kwargs):
            await received_workspace.awrite_text("task-1", path, "print('changed')\n", overwrite=True)
            return await super().execute_script_process(session_id, received_workspace, path, **kwargs)

    runtime = ChangingRuntime()
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.workspace.awrite_text(toolkit.context.task_id, toolkit.context.script_path, "print('original')\n")
    runtime.next_cell = _failed_cell('  File "analysis/a.py", line 1\nValueError: failed')

    result = await toolkit.run_script()

    assert "sourceSha256" not in result["details"]
    assert "sourceExcerpt" not in result["details"]
    assert result["details"]["nextTools"] == ["read_script", "edit_script", "run_script"]


@pytest.mark.anyio
async def test_missing_declared_output_includes_matching_source_context(binding):  # noqa: F811
    class MissingOutputRuntime(ToolkitRuntime):
        async def execute_script_process(self, _session_id, _workspace, _path, **_kwargs):
            return ScriptProcessResult(
                SimpleNamespace(status="ok", stdout="", stderr="", traceback=None),
                0,
            )

    toolkit = ReportingCodeModeToolkit(
        binding, MissingOutputRuntime(), ReportingLspProcessManager()
    )
    await toolkit.workspace.awrite_text(
        toolkit.context.task_id, toolkit.context.script_path, SOURCE
    )

    result = await toolkit.run_script()

    details = result["details"]
    assert result["code"] == "report_code_declared_output_missing"
    assert "不代表脚本不存在" in result["message"]
    assert "edit_script 局部修复" in result["message"]
    assert "不得调用 write_script" in result["message"]
    assert details["path"] == "analysis/out.json"
    assert details["sourceSha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert details["sourceExcerpt"] == SOURCE
    assert details["errorLine"] == 2
    assert details["nextTools"] == ["edit_script", "run_script"]


def test_common_instructions_delegate_patch_wire_format_to_tool_description():
    instructions = "\n".join(_INTERACTIVE_CODE_INSTRUCTIONS)
    assert "REPORTING_CODE_DELIVERY_STATE.nextTools" in instructions
    assert "edit_script 的工具输入是原始补丁" not in instructions
    assert "写入 evidence 文件的内容才是 JSON" not in instructions


def test_edit_tool_description_rejects_json_envelope(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    descriptions = {tool.name: tool.description or "" for tool in toolkit.tool_functions}
    assert '不要包裹成 JSON 或 {"data": ...}' in descriptions["edit_script"]
    assert "执行失败回执" in descriptions["edit_script"]
    assert "语法错误草稿" in descriptions["write_script"]
    assert "运行已保存的绑定脚本" in descriptions["run_script"]
    assert "成功执行" in descriptions["submit_script"]
    assert "会话" in descriptions["restart_code_mode"]
    assert "explorationVariables" in descriptions["run"]
    for name in (
        "read_script", "run", "lsp_diagnostics", "lsp_hover", "lsp_definition",
        "lsp_references", "lsp_document_symbols",
    ):
        assert descriptions[name]


def test_code_tool_descriptions_reach_provider_wire(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())
    model = ReportingCodeOpenAIResponses(id="test", api_key="test")
    wire = {
        tool["name"]: tool
        for tool in model._format_tool_params([], list(toolkit.tool_functions))
    }
    for name in ("write_script", "edit_script", "run"):
        assert wire[name]["type"] == "custom"
        assert "parameters" not in wire[name]
    assert '{"data": ...}' in wire["edit_script"]["description"]
    for name in ("read_script", "run_script", "submit_script", "restart_code_mode",
                 "lsp_diagnostics", "lsp_hover", "lsp_definition", "lsp_references",
                 "lsp_document_symbols"):
        assert wire[name]["type"] == "function"
        assert wire[name]["description"]


@pytest.mark.anyio
async def test_visual_tool_description_targets_current_output(workspace):  # noqa: F811
    _, toolkit, _ = await _prepared_visualization_toolkit(workspace, ToolkitRuntime())
    model = ReportingCodeOpenAIResponses(id="test", api_key="test")
    wire = {tool["name"]: tool for tool in model._format_tool_params([], list(toolkit.tool_functions))}
    assert wire["view_image"]["type"] == "function"
    assert "当前图片输出" in wire["view_image"]["description"]


@pytest.mark.anyio
async def test_submit_script_without_execution_advises_run_script(binding):  # noqa: F811
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager())

    result = await toolkit.submit_script()

    assert result["ok"] is False
    assert result["details"]["nextTools"] == ["run_script"]


@pytest.mark.anyio
async def test_failed_visual_review_requires_edit_instead_of_cached_review(workspace):  # noqa: F811
    task_binding, toolkit, output = await _prepared_visualization_toolkit(workspace, ToolkitRuntime())
    receipt = _visual_receipt(output, requires_revision=True)
    task_binding.visual_inspection_receipts[output.path] = receipt.model_copy(
        update={"issues": (ChartVisualInspectionIssue(
            category="text_overlap", severity="critical", description="关键标签无法辨认。"
        ),)}
    )
    await toolkit.refresh_delivery_state()
    state = toolkit.delivery_state()
    assert state["nextTools"] == ["read_script", "edit_script", "run_script"]
    assert state["nextReviewPaths"] == []
    assert state["visualFailures"][0]["summary"] == ""
    assert state["visualFailures"][0]["issues"] == [{
        "category": "text_overlap",
        "severity": "critical",
        "description": "关键标签无法辨认。",
    }]


@pytest.mark.anyio
async def test_delivery_state_excludes_warning_text_from_visual_repair(workspace):  # noqa: F811
    task_binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, ToolkitRuntime()
    )
    task_binding.visual_inspection_receipts[output.path] = _visual_receipt(
        output, requires_revision=True
    ).model_copy(
        update={
            "issues": (
                ChartVisualInspectionIssue(
                    category="text_overlap",
                    severity="critical",
                    description="关键标签无法辨认。",
                ),
                ChartVisualInspectionIssue(
                    category="missing_units",
                    severity="warning",
                    description="不应进入修复上下文的 warning。",
                ),
            ),
            "summary": "不应进入修复上下文的混合摘要。",
            "warnings": ("不应进入修复上下文的 warnings 字段。",),
            "suggestions": ("无法确定属于哪个 issue 的建议。",),
        }
    )

    await toolkit.refresh_delivery_state()

    state = toolkit.delivery_state()
    assert state["visualFailures"] == [
        {
            "path": output.path,
            "paths": [output.path],
            "summary": "",
            "issues": [
                {
                    "category": "text_overlap",
                    "severity": "critical",
                    "description": "关键标签无法辨认。",
                }
            ],
            "suggestions": [],
        }
    ]
    assert "warning" not in str(state["visualFailures"])
    assert "哪个 issue" not in str(state["visualFailures"])


def test_delivery_projection_hides_visual_noncritical_text_from_next_request():
    model = ReportingCodeOpenAIResponses(id="test", api_key="test")
    model._code_delivery_state_reader = lambda: {
        "marker": "REPORTING_CODE_DELIVERY_STATE",
        "visualFailures": [
            {
                "path": "charts/chart.png",
                "issues": [
                    {
                        "category": "text_overlap",
                        "severity": "critical",
                        "description": "critical-only wire issue",
                    }
                ],
                "summary": "",
                "suggestions": [],
            }
        ],
    }
    model.count_tokens = lambda messages, *args, **kwargs: sum(
        len(str(message.content)) // 4 + 1 for message in messages
    )
    projected = model._project([Message(role="user", content="继续")], (), {})
    delivery_messages = [
        message
        for message in projected
        if isinstance(message.content, str)
        and '"marker":"REPORTING_CODE_DELIVERY_STATE"' in message.content
    ]
    assert len(delivery_messages) == 1
    delivery_text = delivery_messages[0].content
    assert "critical-only wire issue" in delivery_text
    assert "wire warning sentinel" not in delivery_text
    assert "wire summary sentinel" not in delivery_text
    assert "wire suggestion sentinel" not in delivery_text


@pytest.mark.anyio
async def test_first_visual_repair_fails_when_repaired_output_still_requires_revision(
    workspace,  # noqa: F811
):
    reviewer = AsyncMock()
    runtime = ToolkitRuntime()

    async def run_visual_script(_session_id, runtime_workspace, _path, **_kwargs):
        await runtime_workspace.awrite_text(
            "task-1", "charts/chart.png", "image-v2", overwrite=True
        )
        return ScriptProcessResult(
            SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0
        )

    runtime.execute_script_process = run_visual_script
    task_binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, runtime, reviewer
    )
    task_binding.visual_inspection_receipts[output.path] = _visual_receipt(
        output, requires_revision=True
    )
    await toolkit.refresh_delivery_state()
    functions = {tool.name: tool for tool in toolkit.tool_functions}
    patch = edit_patch(VISUAL_SOURCE, "b'image'", "b'image-v2'")

    edit = FunctionCall(function=functions["edit_script"], arguments={"patch": patch})
    assert await edit.aexecute()
    assert edit.result["ok"] is True
    repaired_run = FunctionCall(function=functions["run_script"], arguments={})
    assert await repaired_run.aexecute()
    assert repaired_run.result["ok"] is True
    assert toolkit.first_repair_success == "unknown"

    current_output = task_binding.execution_receipt.output_files[0]
    reviewer.review.return_value = _visual_receipt(
        current_output, requires_revision=True
    )
    review = FunctionCall(
        function=functions["view_image"], arguments={"path": output.path}
    )
    assert await review.aexecute()
    assert review.result["ok"] is True
    assert toolkit.first_repair_success is False


@pytest.mark.anyio
async def test_delivery_preflight_diagnostic_is_bounded(binding):  # noqa: F811
    async def preflight(receipt):
        return {"ok": False, "code": "invalid_structure", "message": "缺少字段" * 10000}
    toolkit = ReportingCodeModeToolkit(binding, ToolkitRuntime(), ReportingLspProcessManager(), output_preflight=preflight)
    await toolkit.write_script(SOURCE)
    await toolkit.run_script()
    await toolkit.refresh_delivery_state()
    state = toolkit.delivery_state()
    assert state["outputValidation"] == "failed"
    assert state["nextTools"] == ["read_script", "edit_script", "run_script"]
    assert len(state["validationFailure"]["message"]) <= 512
    assert len(json.dumps(state, ensure_ascii=False).encode()) < 8192
