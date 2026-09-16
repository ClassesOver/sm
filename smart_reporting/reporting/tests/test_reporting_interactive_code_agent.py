from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agno.models.message import Message
from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.run import RunContext
from agno.tools.function import Function
from openai.types.responses import Response

from smart_reporting.reporting.agent import create_reporting_code_agent_factory
from smart_reporting.reporting.code_agent import protocol as code_protocol
from smart_reporting.reporting.code_agent.context import (
    ExecutionReceipt,
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
    ReportingCodingTaskRegistry,
)
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceRegistry,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.vision import ReportVisionReviewer
from smart_reporting.reporting.workflow.checkpoint import (
    ChartVisualInspectionReceipt,
    FileIdentity,
)
from smart_reporting.reporting.workflow.runtime.code_generation import (
    CodeGenerationResult,
    ReportingCodeGenerationRunner,
)
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope

SOURCE = "from pathlib import Path\nPath('analysis/out.json').write_text('{}')\n"
VISUAL_SOURCE = "from pathlib import Path\nPath('charts/chart.png').write_bytes(b'image')\n"
REVISED_VISUAL_SOURCE = (
    "from pathlib import Path\nPath('charts/chart.png').write_bytes(b'image-v2')\n"
)


def _code_responses_model() -> ReportingCodeOpenAIResponses:
    return ReportingCodeOpenAIResponses(
        id="test-model",
        api_key="test-key",
        base_url="http://localhost",
        parallel_tool_calls=False,
    )


def _function(name: str) -> Function:
    return Function(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
    )


def _custom_response(name: str, raw_input: str) -> Response:
    return Response.model_validate(
        {
            "id": "resp-1",
            "created_at": 0,
            "model": "test-model",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "item-1",
                    "call_id": "call-1",
                    "name": name,
                    "input": raw_input,
                    "type": "custom_tool_call",
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        }
    )


def _function_response(index: int, name: str, arguments: dict[str, Any]) -> Response:
    return Response.model_validate(
        {
            "id": f"resp-{index}",
            "created_at": 0,
            "model": "test-model",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": f"item-{index}",
                    "call_id": f"call-{index}",
                    "name": name,
                    "arguments": json.dumps(arguments, separators=(",", ":")),
                    "type": "function_call",
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        }
    )


def _message_response(text: str) -> Response:
    return Response.model_validate(
        {
            "id": "resp-message",
            "created_at": 0,
            "model": "test-model",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "message-1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": text, "annotations": []}
                    ],
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        }
    )


def _assistant_and_result_messages(call: dict[str, Any], result: dict[str, Any]) -> list[Message]:
    return [
        Message(role="assistant", content="", tool_calls=[call]),
        Message(
            role="tool",
            content=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            tool_call_id=call["call_id"],
            tool_name=call["function"]["name"],
        ),
    ]


def _task_context(
    workspace: HostReportingWorkspace,
    *,
    task_id: str = "task-1",
    script_path: str = "analysis/a.py",
) -> ReportingCodingTaskContext:
    return ReportingCodingTaskContext(
        task_id=task_id,
        task_kind="analysis",
        code_mode_session_id=f"code-{task_id}",
        workspace_key=workspace.identity.workspace_key,
        workspace_root=workspace.identity.root,
        script_path=script_path,
        authorized_read_paths=(),
        authorized_write_paths=(script_path, "analysis/out.json"),
        declared_output_paths=("analysis/out.json",),
        max_source_bytes=128 * 1024,
    )


def _visualization_task_context(
    workspace: HostReportingWorkspace,
) -> ReportingCodingTaskContext:
    return ReportingCodingTaskContext(
        task_id="task-1",
        task_kind="visualization",
        code_mode_session_id="code-task-1",
        workspace_key=workspace.identity.workspace_key,
        workspace_root=workspace.identity.root,
        script_path="analysis/chart.py",
        authorized_read_paths=(),
        authorized_write_paths=("analysis/chart.py", "charts/chart.png"),
        declared_output_paths=("charts/chart.png",),
        max_source_bytes=128 * 1024,
    )


def _identity(path: str, content: bytes) -> FileIdentity:
    return FileIdentity(
        path=path,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _valid_source() -> str:
    return SOURCE


def _run_context(task_id: str = "task-1") -> RunContext:
    return RunContext(run_id=task_id, session_id="session-1")


def _failed_cell(traceback: str) -> SimpleNamespace:
    return SimpleNamespace(
        status="error",
        stdout="",
        stderr="",
        result=None,
        traceback=traceback,
        truncated=[],
        execution_count=1,
    )


def _receipt() -> ExecutionReceipt:
    source = _valid_source().encode()
    return ExecutionReceipt(
        runId="old-run",
        sourceFile=_identity("analysis/a.py", source),
        outputFiles=(_identity("analysis/out.json", b"{}"),),
    )


def _visual_receipt(
    output: FileIdentity,
    *,
    requires_revision: bool = False,
    sha256: str | None = None,
) -> ChartVisualInspectionReceipt:
    return ChartVisualInspectionReceipt.model_validate(
        {
            "sourcePath": output.path,
            "sha256": sha256 or output.sha256,
            "inspectionMode": "vision",
            "visualReviewStatus": "passed",
            "modelId": "vision-test",
            "reviewed": True,
            "requiresRevision": requires_revision,
            "summary": "需要修订。" if requires_revision else "图表清晰。",
        }
    )


async def _prepared_visualization_toolkit(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
    reviewer: ReportVisionReviewer | None = None,
) -> tuple[ReportingCodingTaskBinding, ReportingCodeModeToolkit, FileIdentity]:
    context = _visualization_task_context(workspace)
    binding = ReportingCodingTaskBinding(context, workspace)
    await workspace.awrite_text(context.task_id, context.script_path, VISUAL_SOURCE)
    await workspace.awrite_text(context.task_id, "charts/chart.png", "image")
    source = FileIdentity.model_validate(
        await workspace.ahash_file(context.task_id, context.script_path)
    )
    output = FileIdentity.model_validate(
        await workspace.ahash_file(context.task_id, "charts/chart.png")
    )
    binding.execution_receipt = ExecutionReceipt(
        runId="visual-run",
        sourceFile=source,
        outputFiles=(output,),
    )
    toolkit = ReportingCodeModeToolkit(
        binding,
        runtime,
        ReportingLspProcessManager(),
        vision_reviewer=reviewer,
    )
    return binding, toolkit, output


def test_visual_receipt_state_is_cleared_with_execution_state(
    binding: ReportingCodingTaskBinding,
) -> None:
    receipt = ChartVisualInspectionReceipt.model_validate(
        {
            "sourcePath": "analysis/charts/chart.png",
            "sha256": "a" * 64,
            "inspectionMode": "vision",
            "visualReviewStatus": "passed",
            "modelId": "vision-test",
            "reviewed": True,
            "requiresRevision": False,
        }
    )
    binding.visual_inspection_receipts[receipt.source_path] = receipt
    binding.execution_receipt = _receipt()

    binding.clear_execution_state()

    assert binding.execution_receipt is None
    assert binding.visual_inspection_receipts == {}


def test_code_generation_result_visual_receipts_default_empty() -> None:
    execution_receipt = _receipt()

    result = CodeGenerationResult(
        script_file=execution_receipt.source_file,
        execution_receipt=execution_receipt,
    )

    assert result.visual_inspection_receipts == ()


async def _write_output(workspace: HostReportingWorkspace, path: str) -> None:
    await workspace.awrite_text("task-1", path, "{}", overwrite=False)


class ToolkitRuntime:
    def __init__(self) -> None:
        self.next_cell: SimpleNamespace | None = None
        self.shutdowns: list[str] = []

    async def execute(self, _session_id, _workspace, _code, **_kwargs):
        return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

    async def execute_script_process(self, _session_id, workspace, _path, **_kwargs):
        if self.next_cell is not None:
            cell, self.next_cell = self.next_cell, None
            return cell
        await workspace.awrite_text("task-1", "analysis/out.json", "{}")
        return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

    async def shutdown(self, session_id: str) -> None:
        self.shutdowns.append(session_id)


class FakeCodeMode:
    def __init__(self) -> None:
        self.cells: list[tuple[str, str]] = []
        self.shutdowns: list[str | None] = []

    async def arun(self, session_id: str, code: str) -> SimpleNamespace:
        self.cells.append((session_id, code))
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


@pytest.fixture
def workspace(tmp_path: Path) -> HostReportingWorkspace:
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
    identity = ReportingWorkspaceRegistry(tmp_path, secret="0" * 32).resolve(scope)
    return HostReportingWorkspace(identity)


@pytest.fixture
def binding(workspace: HostReportingWorkspace) -> ReportingCodingTaskBinding:
    return ReportingCodingTaskBinding(_task_context(workspace), workspace)


@pytest.fixture
def runtime() -> ToolkitRuntime:
    return ToolkitRuntime()


def test_mixed_protocol_formats_only_large_text_tools_as_custom() -> None:
    model = _code_responses_model()
    tools = model._format_tool_params(
        [],
        [_function("read_script"), _function("write_script"), _function("execute_code")],
    )

    assert tools[0]["type"] == "function"
    assert tools[1] == {
        "type": "custom",
        "name": "write_script",
        "description": "write_script",
        "format": {
            "type": "grammar",
            "syntax": "lark",
            "definition": "start: SOURCE\nSOURCE: /[\\s\\S]+/",
        },
    }
    assert tools[2]["type"] == "custom"


def test_custom_tool_call_is_rejected() -> None:
    with pytest.raises(ReportingError) as caught:
        _code_responses_model()._parse_provider_response(
            _custom_response("execute_code", "print('must not run')")
        )

    assert caught.value.code == "report_code_custom_tool_protocol_error"


def test_function_call_round_trip_stays_function_protocol() -> None:
    model = _code_responses_model()
    response = Response.model_validate(
        {
            "id": "resp-2",
            "created_at": 0,
            "model": "test-model",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "item-2",
                    "call_id": "call-2",
                    "name": "run_script",
                    "arguments": "{}",
                    "type": "function_call",
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        }
    )
    parsed = model._parse_provider_response(response)
    assert parsed.tool_calls is not None
    replay = model._format_messages(
        _assistant_and_result_messages(parsed.tool_calls[0], {"ok": True})
    )
    assert [item["type"] for item in replay[-2:]] == [
        "function_call",
        "function_call_output",
    ]


def test_request_with_custom_tool_forces_auto_choice() -> None:
    model = ReportingCodeOpenAIResponses(
        id="test-model",
        api_key="test-key",
        base_url="http://localhost",
        parallel_tool_calls=True,
    )

    params = model.get_request_params(
        messages=[Message(role="user", content="write")],
        tools=[_function("write_script"), _function("run_script")],
        tool_choice={"type": "custom", "name": "write_script"},
    )

    assert params["parallel_tool_calls"] is False
    assert params["tool_choice"] == "auto"


def test_function_only_request_preserves_explicit_choice() -> None:
    choice = {"type": "function", "name": "run_script"}
    params = _code_responses_model().get_request_params(
        messages=[Message(role="user", content="run")],
        tools=[_function("run_script"), _function("submit_script")],
        tool_choice=choice,
    )

    assert params["tool_choice"] == choice


def test_code_requests_default_to_auto_tool_choice() -> None:
    params = _code_responses_model().get_request_params(
        messages=[Message(role="user", content="write")],
        tools=[_function("write_script"), _function("run_script")],
    )

    assert params["parallel_tool_calls"] is False
    assert params["tool_choice"] == "auto"


def test_visualization_single_tool_choice_uses_auto_for_custom_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        code_protocol,
        "reporting_task_kind_from_run_context",
        lambda _context: "visualization_section",
    )
    monkeypatch.setattr(code_protocol, "current_reporting_run_context", lambda: object())
    monkeypatch.setattr(
        code_protocol,
        "phase_filtered_report_tools",
        lambda _messages, tools: tools,
    )

    _args, kwargs = code_protocol.phase_filtered_model_call(
        [], (), {"tools": [_function("write_script")]}
    )

    assert kwargs["tool_choice"] == "auto"


def test_visualization_single_tool_choice_names_function_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        code_protocol,
        "reporting_task_kind_from_run_context",
        lambda _context: "visualization_section",
    )
    monkeypatch.setattr(code_protocol, "current_reporting_run_context", lambda: object())
    monkeypatch.setattr(
        code_protocol,
        "phase_filtered_report_tools",
        lambda _messages, tools: tools,
    )

    _args, kwargs = code_protocol.phase_filtered_model_call(
        [], (), {"tools": [_function("view_image")]}
    )

    assert kwargs["tool_choice"] == {"type": "function", "name": "view_image"}


def test_streaming_freeform_tools_are_rejected_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_called = False

    def provider_stream(*_args: Any, **_kwargs: Any) -> Iterator[Any]:
        nonlocal provider_called
        provider_called = True
        return iter(())

    monkeypatch.setattr(OpenAIResponses, "invoke_stream", provider_stream)

    with pytest.raises(ReportingError, match="非流式") as caught:
        _code_responses_model().invoke_stream(
            [], Message(role="assistant", content=""), None, [_function("write_script")]
        )

    assert caught.value.code == "report_code_streaming_unsupported"
    assert provider_called is False


@pytest.mark.anyio
async def test_async_streaming_freeform_tools_are_rejected_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_called = False

    def provider_stream(*_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
        nonlocal provider_called
        provider_called = True

        async def empty() -> AsyncIterator[Any]:
            if False:
                yield None

        return empty()

    monkeypatch.setattr(OpenAIResponses, "ainvoke_stream", provider_stream)

    with pytest.raises(ReportingError, match="非流式") as caught:
        _code_responses_model().ainvoke_stream(
            [], Message(role="assistant", content=""), None, [_function("execute_code")]
        )

    assert caught.value.code == "report_code_streaming_unsupported"
    assert provider_called is False


def test_streaming_structured_tools_delegate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = iter(("response",))

    def provider_stream(*_args: Any, **_kwargs: Any) -> Iterator[Any]:
        return sentinel

    monkeypatch.setattr(OpenAIResponses, "invoke_stream", provider_stream)

    result = _code_responses_model().invoke_stream(
        [], Message(role="assistant", content=""), None, [_function("run_script")]
    )

    assert result is sentinel


def test_custom_protocol_rejects_dsml_assistant_text_without_executing_it() -> None:
    with pytest.raises(ReportingError) as caught:
        _code_responses_model()._parse_provider_response(
            _message_response("<|recipient=write_script|>print('must not run')")
        )

    assert caught.value.code == "report_code_custom_tool_protocol_error"
    assert caught.value.details == {"retryable": False}


@pytest.mark.parametrize(
    "text",
    [
        "```execute_code\nprint('must not run')\n```",
        (
            '<｜DSML｜tool_calls>\n<｜DSML｜invoke name="execute_code">\n'
            '<｜DSML｜parameter name="code" string="true">print(1)</｜DSML｜parameter>\n'
            "</｜DSML｜invoke>\n</｜DSML｜tool_calls>"
        ),
    ],
)
def test_code_protocol_rejects_textual_tool_call_variants(text: str) -> None:
    with pytest.raises(ReportingError) as caught:
        _code_responses_model()._parse_provider_response(_message_response(text))

    assert caught.value.code == "report_code_custom_tool_protocol_error"
    assert caught.value.details == {"retryable": False}


def test_custom_protocol_keeps_plain_assistant_text_as_text() -> None:
    parsed = _code_responses_model()._parse_provider_response(
        _message_response("无法在当前上下文完成脚本。")
    )

    assert parsed.content == "无法在当前上下文完成脚本。"
    assert not parsed.tool_calls


@pytest.mark.anyio
async def test_coding_task_registry_rejects_same_script_concurrently(
    workspace: HostReportingWorkspace,
) -> None:
    registry = ReportingCodingTaskRegistry()
    first = _task_context(workspace, task_id="first", script_path="analysis/a.py")
    second = _task_context(workspace, task_id="second", script_path="analysis/a.py")
    async with registry.bind(first, workspace):
        with pytest.raises(ReportingError) as caught:
            async with registry.bind(second, workspace):
                pass
    assert caught.value.code == "report_coding_task_conflict"


@pytest.mark.anyio
async def test_execute_script_uses_clean_python_subprocess(
    workspace: HostReportingWorkspace,
) -> None:
    code_mode = FakeCodeMode()
    runtime = ReportingCodeModeRuntime(code_mode)
    await runtime.execute("task-1", workspace, "leaked = 7")
    await runtime.execute_script_process("task-1", workspace, "analysis/a.py", matplotlib_agg=False)
    assert code_mode.cells[-1][1].startswith("%%bash\n")
    assert "exec(compile(" not in code_mode.cells[-1][1]
    assert "analysis/a.py" in code_mode.cells[-1][1]


@pytest.mark.anyio
async def test_view_image_is_registered_only_for_visualization_tasks(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    analysis = ReportingCodeModeToolkit(
        ReportingCodingTaskBinding(_task_context(workspace), workspace),
        runtime,
        ReportingLspProcessManager(),
    )
    visualization = ReportingCodeModeToolkit(
        ReportingCodingTaskBinding(_visualization_task_context(workspace), workspace),
        runtime,
        ReportingLspProcessManager(),
    )

    assert "view_image" not in {tool.name for tool in analysis.tool_functions}
    assert "view_image" in {tool.name for tool in visualization.tool_functions}


@pytest.mark.anyio
async def test_view_image_rejects_undeclared_path_before_execution(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    toolkit = ReportingCodeModeToolkit(
        ReportingCodingTaskBinding(_visualization_task_context(workspace), workspace),
        runtime,
        ReportingLspProcessManager(),
    )

    result = await toolkit.view_image("charts/not-declared.png")

    assert result["ok"] is False
    assert result["code"] == "report_code_visual_path_forbidden"


@pytest.mark.anyio
async def test_view_image_requires_current_execution(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    toolkit = ReportingCodeModeToolkit(
        ReportingCodingTaskBinding(_visualization_task_context(workspace), workspace),
        runtime,
        ReportingLspProcessManager(),
    )

    result = await toolkit.view_image("charts/chart.png")

    assert result["code"] == "report_code_visual_review_required_execution"


@pytest.mark.anyio
async def test_view_image_returns_and_stores_structured_visual_review(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    reviewer = AsyncMock(spec=ReportVisionReviewer)
    binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, runtime, reviewer
    )
    reviewed = _visual_receipt(output)
    reviewer.review.return_value = reviewed

    result = await toolkit.view_image("charts/chart.png", detail="original")

    assert result == {
        "ok": True,
        "receipt": reviewed.model_dump(mode="json", by_alias=True),
    }
    assert binding.visual_inspection_receipts == {"charts/chart.png": reviewed}
    reviewer.review.assert_awaited_once_with(
        workspace.identity.workspace_key,
        "charts/chart.png",
        detail="original",
    )


@pytest.mark.anyio
async def test_view_image_reuses_visual_review_for_same_sha256(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    reviewer = AsyncMock(spec=ReportVisionReviewer)
    binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, runtime, reviewer
    )
    reviewed = _visual_receipt(output)
    binding.visual_inspection_receipts[output.path] = reviewed

    result = await toolkit.view_image(output.path)

    assert result["receipt"]["sha256"] == output.sha256
    reviewer.review.assert_not_awaited()


@pytest.mark.anyio
async def test_view_image_rejects_output_changed_during_visual_review(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    reviewer = AsyncMock(spec=ReportVisionReviewer)
    binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, runtime, reviewer
    )

    def mutate_output(*_args: object, **_kwargs: object) -> ChartVisualInspectionReceipt:
        (workspace.identity.root / "charts/chart.png").write_bytes(b"changed")
        return _visual_receipt(output)

    reviewer.review.side_effect = mutate_output

    result = await toolkit.view_image(output.path)

    assert result["code"] == "report_code_visual_output_changed"
    assert binding.visual_inspection_receipts == {}




@pytest.mark.anyio
async def test_view_image_rejects_output_deleted_during_visual_review(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    reviewer = AsyncMock(spec=ReportVisionReviewer)
    binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, runtime, reviewer
    )

    def delete_output(*_args: object, **_kwargs: object) -> ChartVisualInspectionReceipt:
        (workspace.identity.root / "charts/chart.png").unlink()
        return _visual_receipt(output)

    reviewer.review.side_effect = delete_output

    result = await toolkit.view_image(output.path)

    assert result["code"] == "report_code_visual_output_changed"
    assert binding.visual_inspection_receipts == {}


@pytest.mark.anyio
async def test_view_image_bounds_visual_reviewer_failures(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    reviewer = AsyncMock(spec=ReportVisionReviewer)
    _binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, runtime, reviewer
    )
    reviewer.review.side_effect = RuntimeError("provider secret response")

    result = await toolkit.view_image(output.path)

    assert result["code"] == "report_code_visual_review_unavailable"
    assert "provider secret response" not in str(result)


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["write", "run", "restart"])
async def test_visual_review_state_is_invalidated_by_execution_changes(
    operation: str,
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    binding, toolkit, output = await _prepared_visualization_toolkit(workspace, runtime)
    binding.visual_inspection_receipts[output.path] = _visual_receipt(output)
    assert binding.execution_receipt is not None
    toolkit.submitted_receipt = binding.execution_receipt

    if operation == "write":
        await toolkit.write_script(VISUAL_SOURCE)
    elif operation == "run":
        await toolkit.run_script()
    else:
        await toolkit.restart_code_mode()

    assert binding.execution_receipt is None
    assert binding.visual_inspection_receipts == {}
    assert toolkit.submitted_receipt is None


@pytest.mark.anyio
async def test_run_and_submit_bind_source_and_declared_outputs(
    binding: ReportingCodingTaskBinding,
    runtime: ToolkitRuntime,
) -> None:
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script(_valid_source())
    run = await toolkit.run_script()
    assert run["ok"] is True
    submitted = await toolkit.submit_script()
    assert submitted["ok"] is True
    assert submitted["executionReceipt"]["sourceFile"]["path"] == "analysis/a.py"
    assert [item["path"] for item in submitted["executionReceipt"]["outputFiles"]] == [
        "analysis/out.json"
    ]


@pytest.mark.anyio
async def test_visual_submit_requires_review_for_every_current_output(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    _binding, toolkit, _output = await _prepared_visualization_toolkit(workspace, runtime)

    result = await toolkit.submit_script()

    assert result["code"] == "report_code_visual_review_required"


@pytest.mark.anyio
async def test_visual_submit_rejects_review_requiring_revision(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    binding, toolkit, output = await _prepared_visualization_toolkit(workspace, runtime)
    binding.visual_inspection_receipts[output.path] = _visual_receipt(
        output, requires_revision=True
    )

    result = await toolkit.submit_script()

    assert result["code"] == "report_code_visual_revision_required"


@pytest.mark.anyio
async def test_visual_submit_rejects_stale_visual_review(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    binding, toolkit, output = await _prepared_visualization_toolkit(workspace, runtime)
    binding.visual_inspection_receipts[output.path] = _visual_receipt(
        output, sha256="0" * 64
    )

    result = await toolkit.submit_script()

    assert result["code"] == "report_code_visual_output_changed"


@pytest.mark.anyio
async def test_visual_submit_accepts_all_current_visual_reviews(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    binding, toolkit, output = await _prepared_visualization_toolkit(workspace, runtime)
    binding.visual_inspection_receipts[output.path] = _visual_receipt(output)

    result = await toolkit.submit_script()

    assert result["ok"] is True
    assert toolkit.submitted_receipt is binding.execution_receipt


@pytest.mark.anyio
async def test_submit_rejects_source_or_output_changed_after_run(
    binding: ReportingCodingTaskBinding,
    runtime: ToolkitRuntime,
) -> None:
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script(_valid_source())
    assert (await toolkit.run_script())["ok"] is True
    await binding.workspace.awrite_text(
        "task", "analysis/out.json", '{"changed":true}', overwrite=True
    )
    rejected = await toolkit.submit_script()
    assert rejected["code"] == "report_code_output_modified_after_execution"


@pytest.mark.anyio
async def test_failed_run_clears_old_declared_output_and_receipt(
    binding: ReportingCodingTaskBinding,
    runtime: ToolkitRuntime,
) -> None:
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    binding.execution_receipt = _receipt()
    await _write_output(binding.workspace, "analysis/out.json")
    runtime.next_cell = _failed_cell("ValueError: bad")
    result = await toolkit.run_script()
    assert result["ok"] is False
    assert binding.execution_receipt is None
    assert not await binding.workspace.apath_exists("task", "analysis/out.json")


@pytest.mark.anyio
async def test_runner_uses_one_multitool_run_and_returns_submission(
    workspace: HostReportingWorkspace,
) -> None:
    created = []

    class Runtime:
        shutdowns: list[str] = []

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_text("task-1", "analysis/out.json", "{}")
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    runtime = Runtime()

    class ScriptedAgent:
        tool_call_limit = 20
        model = SimpleNamespace(parallel_tool_calls=False)

        def __init__(self, tools: Sequence[Function]) -> None:
            self.tools = {tool.name: tool for tool in tools}

        async def arun(self, _prompt: str, **_kwargs: Any) -> object:
            await self.tools["write_script"].entrypoint(source=SOURCE)
            await self.tools["run_script"].entrypoint()
            return await self.tools["submit_script"].entrypoint()

    def factory(tools: Sequence[Function]) -> ScriptedAgent:
        agent = ScriptedAgent(tools)
        created.append(agent)
        return agent

    result = await ReportingCodeGenerationRunner(factory, runtime, ReportingLspProcessManager()).run(
        _task_context(workspace),
        workspace,
        {"fact": 1},
        run_context=_run_context("task-1"),
    )
    assert len(created) == 1
    assert result.script_file.path == "analysis/a.py"
    assert result.execution_receipt.output_files[0].path == "analysis/out.json"
    assert created[0].tool_call_limit == 20
    assert created[0].model.parallel_tool_calls is False


@pytest.mark.anyio
async def test_runner_vision_uses_exact_reviewer_dynamic_budget_and_sorted_receipts(
    workspace: HostReportingWorkspace,
) -> None:
    output_paths = ("charts/b.png", "charts/a.png")
    source = (
        "from pathlib import Path\n"
        "Path('charts/b.png').write_bytes(b'b')\n"
        "Path('charts/a.png').write_bytes(b'a')\n"
    )
    context = ReportingCodingTaskContext(
        task_id="task-1",
        task_kind="visualization",
        code_mode_session_id="code-task-1",
        workspace_key=workspace.identity.workspace_key,
        workspace_root=workspace.identity.root,
        script_path="analysis/chart.py",
        authorized_read_paths=(),
        authorized_write_paths=("analysis/chart.py", *output_paths),
        declared_output_paths=output_paths,
        max_source_bytes=128 * 1024,
    )

    class Runtime:
        shutdowns: list[str] = []

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            for path in output_paths:
                await received.awrite_text("task-1", path, path)
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    class Reviewer:
        def __init__(self) -> None:
            self.reviewed_paths: list[str] = []

        async def review(self, workspace_key: str, path: str, *, detail: str):
            assert workspace_key == workspace.identity.workspace_key
            assert detail == "original"
            self.reviewed_paths.append(path)
            output = FileIdentity.model_validate(await workspace.ahash_file("task-1", path))
            return _visual_receipt(output)

    class ScriptedAgent:
        tool_call_limit = 20

        def __init__(self, tools: Sequence[Function]) -> None:
            self.tools = {tool.name: tool for tool in tools}

        async def arun(self, _prompt: str, **_kwargs: Any) -> object:
            await self.tools["write_script"].entrypoint(source=source)
            await self.tools["run_script"].entrypoint()
            for path in output_paths:
                await self.tools["view_image"].entrypoint(path=path, detail="original")
            return await self.tools["submit_script"].entrypoint()

    agents: list[ScriptedAgent] = []

    def factory(tools: Sequence[Function]) -> ScriptedAgent:
        agent = ScriptedAgent(tools)
        agents.append(agent)
        return agent

    reviewer = Reviewer()
    result = await ReportingCodeGenerationRunner(
        factory,
        Runtime(),
        ReportingLspProcessManager(),
        vision_reviewer=reviewer,
    ).run(
        context,
        workspace,
        {},
        run_context=_run_context("task-1"),
    )

    assert reviewer.reviewed_paths == list(output_paths)
    assert tuple(item.source_path for item in result.visual_inspection_receipts) == (
        "charts/a.png",
        "charts/b.png",
    )
    assert {item.sha256 for item in result.visual_inspection_receipts} == {
        item.sha256 for item in result.execution_receipt.output_files
    }
    assert agents[0].tool_call_limit == 31


@pytest.mark.anyio
async def test_runner_vision_requires_reviewer_before_agent_execution(
    workspace: HostReportingWorkspace,
) -> None:
    with pytest.raises(ReportingError) as caught:
        await ReportingCodeGenerationRunner(
            lambda _tools: object(),
            object(),
            ReportingLspProcessManager(),
        ).run(
            _visualization_task_context(workspace),
            workspace,
            {},
            run_context=_run_context("task-1"),
        )

    assert caught.value.code == "report_code_visual_reviewer_missing"


@pytest.mark.anyio
async def test_runner_tool_call_limit_rejects_visualization_above_hard_limit(
    workspace: HostReportingWorkspace,
) -> None:
    output_paths = tuple(f"charts/{index}.png" for index in range(112))
    context = ReportingCodingTaskContext(
        task_id="task-1",
        task_kind="visualization",
        code_mode_session_id="code-task-1",
        workspace_key=workspace.identity.workspace_key,
        workspace_root=workspace.identity.root,
        script_path="analysis/chart.py",
        authorized_read_paths=(),
        authorized_write_paths=("analysis/chart.py", *output_paths),
        declared_output_paths=output_paths,
        max_source_bytes=128 * 1024,
    )
    factory_called = False

    def factory(_tools: Sequence[Function]) -> object:
        nonlocal factory_called
        factory_called = True
        return object()

    with pytest.raises(ReportingError) as caught:
        await ReportingCodeGenerationRunner(
            factory,
            object(),
            ReportingLspProcessManager(),
            vision_reviewer=AsyncMock(),
        ).run(context, workspace, {}, run_context=_run_context("task-1"))

    assert caught.value.code == "report_code_tool_call_limit_exceeded"
    assert caught.value.details == {
        "declaredOutputCount": 112,
        "requestedToolCallLimit": 141,
        "maxToolCallLimit": 140,
    }
    assert factory_called is False


@pytest.mark.anyio
async def test_runner_shuts_down_kernel_on_no_submission(
    workspace: HostReportingWorkspace,
) -> None:
    class Runtime:
        def __init__(self) -> None:
            self.shutdowns: list[str] = []

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    runtime = Runtime()

    class TextOnlyAgent:
        async def arun(self, _prompt: str, **_kwargs: Any) -> str:
            return "done"

    with pytest.raises(ReportingError) as caught:
        await ReportingCodeGenerationRunner(lambda _tools: TextOnlyAgent(), runtime, ReportingLspProcessManager()).run(
            _task_context(workspace), workspace, {}, run_context=_run_context("task-1")
        )
    assert caught.value.code == "report_code_generation_no_submission"
    assert caught.value.details == {"retryable": False}
    assert runtime.shutdowns == ["code-task-1"]


@pytest.mark.anyio
async def test_runner_raises_recorded_protocol_error_before_no_submission(
    workspace: HostReportingWorkspace,
) -> None:
    class Runtime:
        def __init__(self) -> None:
            self.shutdowns: list[str] = []

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    protocol_error = ReportingError(
        "report_code_custom_tool_protocol_error",
        "Coding Agent 将工具调用写入了 assistant 正文。",
        details={"retryable": False},
    )

    class RecordedProtocolErrorAgent:
        model = SimpleNamespace(report_run_error=lambda: protocol_error)

        async def arun(self, _prompt: str, **_kwargs: Any) -> str:
            return "done"

    runtime = Runtime()
    with pytest.raises(ReportingError) as caught:
        await ReportingCodeGenerationRunner(
            lambda _tools: RecordedProtocolErrorAgent(),
            runtime,
            ReportingLspProcessManager(),
        ).run(_task_context(workspace), workspace, {}, run_context=_run_context("task-1"))

    assert caught.value is protocol_error
    assert runtime.shutdowns == ["code-task-1"]


@pytest.mark.anyio
async def test_runner_shuts_down_kernel_when_agent_factory_fails(
    workspace: HostReportingWorkspace,
) -> None:
    class Runtime:
        def __init__(self) -> None:
            self.shutdowns: list[str] = []

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    runtime = Runtime()

    def factory(_tools: Sequence[Function]) -> object:
        raise RuntimeError("factory failed")

    with pytest.raises(ReportingError) as caught:
        await ReportingCodeGenerationRunner(factory, runtime, ReportingLspProcessManager()).run(
            _task_context(workspace), workspace, {}, run_context=_run_context("task-1")
        )

    assert caught.value.code == "report_code_generation_agent_failed"
    assert runtime.shutdowns == ["code-task-1"]


@pytest.mark.anyio
async def test_runner_shuts_down_kernel_when_agent_is_cancelled(
    workspace: HostReportingWorkspace,
) -> None:
    class Runtime:
        def __init__(self) -> None:
            self.shutdowns: list[str] = []

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    class CancelledAgent:
        async def arun(self, _prompt: str, **_kwargs: Any) -> None:
            raise asyncio.CancelledError

    runtime = Runtime()
    registry = ReportingCodingTaskRegistry()
    with pytest.raises(asyncio.CancelledError):
        await ReportingCodeGenerationRunner(
            lambda _tools: CancelledAgent(),
            runtime,
            ReportingLspProcessManager(),
            registry=registry,
        ).run(
            _task_context(workspace), workspace, {}, run_context=_run_context("task-1")
        )

    assert runtime.shutdowns == ["code-task-1"]
    assert registry.active_count == 0


def test_code_agent_factory_creates_fresh_agent_with_custom_input_instructions() -> None:
    factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        name="reporting-code-agent",
    )
    first = factory([_function("read_script")])
    second = factory([_function("read_script")])
    assert first is not second
    assert first.model is not second.model
    assert first.tools[0] is not second.tools[0]
    instructions = "\n".join(str(item) for item in first.instructions)
    assert (
        "write_script 与 execute_code 的 custom input 只包含原始源码或 cell 文本，"
        "不得添加 JSON 包装或说明。"
    ) in instructions
    assert "source 参数" not in instructions
    assert "code 参数" not in instructions


def test_interactive_runner_exposes_only_run_public_entrypoint() -> None:
    runner = ReportingCodeGenerationRunner(lambda _tools: object(), object(), ReportingLspProcessManager())

    assert callable(runner.run)
    assert not hasattr(runner, "generate")
    assert not hasattr(runner, "repair")


@pytest.mark.anyio
async def test_interactive_v1_write_fail_fix_run_submit(
    workspace: HostReportingWorkspace,
) -> None:
    binding = ReportingCodingTaskBinding(_task_context(workspace), workspace)

    class Runtime:
        async def execute(self, _session_id, _workspace, _code, **_kwargs):
            return SimpleNamespace(status="ok", stdout="probe\n", stderr="", traceback=None)

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            source = await received.aread_text("task-1", "analysis/a.py")
            if "broken" in source:
                return _failed_cell("SyntaxError: invalid syntax")
            exists = await received.apath_exists("task-1", "analysis/out.json")
            await received.awrite_text(
                "task-1", "analysis/out.json", "{}", overwrite=exists
            )
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def shutdown(self, _session_id):
            return None

    runtime = Runtime()
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script("if True print('broken')\n")
    assert (await toolkit.run_script())["ok"] is False
    await toolkit.write_script(SOURCE)
    assert (await toolkit.execute_code("print('probe')"))["ok"] is True
    assert (await toolkit.run_script())["ok"] is True
    submitted = await toolkit.submit_script()
    assert submitted["ok"] is True
    receipt = ExecutionReceipt.model_validate(submitted["executionReceipt"])
    assert receipt.source_file == binding.execution_receipt.source_file
    assert receipt.output_files == binding.execution_receipt.output_files


@pytest.mark.anyio
async def test_interactive_v1_end_to_end_responses_loop(
    workspace: HostReportingWorkspace,
) -> None:
    responses = [
        _function_response(1, "write_script", {"source": "if True print('broken')\n"}),
        _function_response(2, "run_script", {}),
        _function_response(3, "write_script", {"source": SOURCE}),
        _function_response(4, "lsp_diagnostics", {}),
        _function_response(5, "search_knowledge", {"query": "脚本规范"}),
        _function_response(6, "run_script", {}),
        _function_response(7, "submit_script", {}),
    ]

    class FakeResponsesClient:
        def __init__(self) -> None:
            self.responses = self
            self.input_tokens = self
            self.requests: list[dict[str, Any]] = []

        def is_closed(self) -> bool:
            return False

        async def create(self, **kwargs: Any) -> Response:
            self.requests.append(kwargs)
            return responses.pop(0)

        async def count(self, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(input_tokens=1)

    class Runtime:
        def __init__(self) -> None:
            self.shutdowns: list[str] = []

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            source = await received.aread_text("task-1", "analysis/a.py")
            if "broken" in source:
                return _failed_cell("SyntaxError: invalid syntax")
            await received.awrite_text("task-1", "analysis/out.json", "{}")
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    class KnowledgeIndex:
        async def search(self, query: str, *, workspace_key: str) -> list[SimpleNamespace]:
            assert query == "脚本规范"
            assert workspace_key == workspace.identity.workspace_key
            return [
                SimpleNamespace(
                    identity="static:test",
                    kind="static",
                    snippet="脚本规范",
                    score=1.0,
                    content_sha256="a" * 64,
                )
            ]

    class LspManager:
        async def diagnostics(self, root: Path, uri: str, text: str):
            assert root == workspace.identity.root
            assert uri.endswith("/analysis/a.py")
            assert text == SOURCE
            return 1, []

    client = FakeResponsesClient()
    base_factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        name="reporting-code-agent-e2e",
    )

    def agent_factory(tools: Sequence[Function]):
        agent = base_factory(tools)
        agent.model.async_client = client
        return agent

    runtime = Runtime()
    result = await ReportingCodeGenerationRunner(
        agent_factory,
        runtime,
        knowledge_index=KnowledgeIndex(),
        lsp_manager=LspManager(),
    ).run(
        _task_context(workspace),
        workspace,
        {"fact": 1},
        run_context=_run_context(),
    )

    assert result.script_file == result.execution_receipt.source_file
    assert result.execution_receipt.output_files[0].path == "analysis/out.json"
    assert await workspace.aread_text("task-1", "analysis/a.py") == SOURCE
    assert runtime.shutdowns == ["code-task-1"]
    assert len(client.requests) == 7
    assert responses == []
    assert all(
        tool["type"] == "function"
        for request in client.requests
        for tool in request["tools"]
    )
    replay_types = [
        item.get("type")
        for request in client.requests[1:]
        for item in request["input"]
        if isinstance(item, dict)
    ]
    assert "function_call_output" in replay_types


@pytest.mark.anyio
async def test_interactive_visual_repair_end_to_end_uses_text_only_receipts(
    workspace: HostReportingWorkspace,
) -> None:
    responses = [
        _function_response(1, "write_script", {"source": VISUAL_SOURCE}),
        _function_response(2, "run_script", {}),
        _function_response(3, "view_image", {"path": "charts/chart.png"}),
        _function_response(4, "write_script", {"source": REVISED_VISUAL_SOURCE}),
        _function_response(5, "run_script", {}),
        _function_response(6, "view_image", {"path": "charts/chart.png"}),
        _function_response(7, "submit_script", {}),
    ]

    class FakeResponsesClient:
        def __init__(self) -> None:
            self.responses = self
            self.input_tokens = self
            self.requests: list[dict[str, Any]] = []

        def is_closed(self) -> bool:
            return False

        async def create(self, **kwargs: Any) -> Response:
            self.requests.append(kwargs)
            return responses.pop(0)

        async def count(self, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(input_tokens=1)

    class Runtime:
        def __init__(self) -> None:
            self.shutdowns: list[str] = []

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            source = await received.aread_text("task-1", "analysis/chart.py")
            content = b"image-v2" if "image-v2" in source else b"image-v1"
            await received.awrite_bytes("task-1", "charts/chart.png", content)
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    class Reviewer:
        def __init__(self) -> None:
            self.hashes: list[str] = []

        async def review(self, workspace_key: str, path: str, *, detail: str):
            assert workspace_key == workspace.identity.workspace_key
            assert detail == "high"
            output = FileIdentity.model_validate(await workspace.ahash_file("task-1", path))
            self.hashes.append(output.sha256)
            requires_revision = len(self.hashes) == 1
            return ChartVisualInspectionReceipt(
                sourcePath=path,
                sha256=output.sha256,
                inspectionMode="vision",
                visualReviewStatus="passed",
                modelId="vision-test",
                reviewed=True,
                requiresRevision=requires_revision,
                issues=(
                    {
                        "category": "text_overlap",
                        "severity": "critical",
                        "description": "关键标题完全重叠，无法辨认。",
                    },
                )
                if requires_revision
                else (),
                summary="需要修订。" if requires_revision else "图表清晰。",
            )

    client = FakeResponsesClient()
    base_factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        name="reporting-visual-code-agent-e2e",
    )

    def agent_factory(tools: Sequence[Function]):
        agent = base_factory(tools)
        agent.model.async_client = client
        return agent

    runtime = Runtime()
    reviewer = Reviewer()
    registry = ReportingCodingTaskRegistry()
    result = await ReportingCodeGenerationRunner(
        agent_factory,
        runtime,
        ReportingLspProcessManager(),
        registry=registry,
        vision_reviewer=reviewer,
    ).run(
        _visualization_task_context(workspace),
        workspace,
        {},
        run_context=_run_context(),
    )

    assert len(reviewer.hashes) == 2
    assert reviewer.hashes[0] != reviewer.hashes[1]
    assert result.visual_inspection_receipts[0].sha256 == reviewer.hashes[1]
    assert result.visual_inspection_receipts[0].requires_revision is False
    request_history = json.dumps(client.requests, ensure_ascii=False, default=str)
    assert "关键标题完全重叠" in request_history
    assert "image_url" not in request_history
    assert "data:image" not in request_history
    assert responses == []
    assert runtime.shutdowns == ["code-task-1"]
    assert registry.active_count == 0


@pytest.mark.anyio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_visual_reviewer_failure_releases_task_resources(
    cancelled: bool,
    workspace: HostReportingWorkspace,
) -> None:
    class Runtime:
        def __init__(self) -> None:
            self.shutdowns: list[str] = []

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_bytes("task-1", "charts/chart.png", b"image")
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    class Reviewer:
        async def review(self, *_args: object, **_kwargs: object):
            if cancelled:
                raise asyncio.CancelledError
            raise RuntimeError("vision provider failed")

    captured_bindings: list[ReportingCodingTaskBinding] = []

    class ReviewAgent:
        tool_call_limit = 20
        model = SimpleNamespace(parallel_tool_calls=False)

        def __init__(self, tools: Sequence[Function]) -> None:
            self.tools = {tool.name: tool for tool in tools}
            captured_bindings.append(next(iter(tools)).entrypoint.__self__.binding)

        async def arun(self, _prompt: str, **_kwargs: Any) -> object:
            await self.tools["write_script"].entrypoint(source=VISUAL_SOURCE)
            await self.tools["run_script"].entrypoint()
            return await self.tools["view_image"].entrypoint(path="charts/chart.png")

    runtime = Runtime()
    registry = ReportingCodingTaskRegistry()
    runner = ReportingCodeGenerationRunner(
        lambda tools: ReviewAgent(tools),
        runtime,
        ReportingLspProcessManager(),
        registry=registry,
        vision_reviewer=Reviewer(),
    )

    expected_error = asyncio.CancelledError if cancelled else ReportingError
    with pytest.raises(expected_error):
        await runner.run(
            _visualization_task_context(workspace),
            workspace,
            {},
            run_context=_run_context(),
        )

    assert runtime.shutdowns == ["code-task-1"]
    assert registry.active_count == 0
    assert captured_bindings[0].visual_inspection_receipts == {}


@pytest.mark.anyio
async def test_interactive_v1_releases_all_task_resources(
    workspace: HostReportingWorkspace,
) -> None:
    registry = ReportingCodingTaskRegistry()

    class Runtime:
        def __init__(self) -> None:
            self.shutdowns: list[str] = []

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_text("task-1", "analysis/out.json", "{}")
            return SimpleNamespace(status="ok", stdout="", stderr="", traceback=None)

        async def shutdown(self, session_id: str) -> None:
            self.shutdowns.append(session_id)

    runtime = Runtime()

    class SubmitAgent:
        tool_call_limit = 20
        model = SimpleNamespace(parallel_tool_calls=False)

        def __init__(self, tools: Sequence[Function]) -> None:
            self.tools = {tool.name: tool for tool in tools}

        async def arun(self, _prompt: str, **_kwargs: Any) -> object:
            await self.tools["write_script"].entrypoint(source=SOURCE)
            await self.tools["run_script"].entrypoint()
            return await self.tools["submit_script"].entrypoint()

    runner = ReportingCodeGenerationRunner(
        lambda tools: SubmitAgent(tools), runtime, ReportingLspProcessManager(), registry=registry
    )
    result = await runner.run(
        _task_context(workspace), workspace, {}, run_context=_run_context()
    )
    assert result.script_file == result.execution_receipt.source_file
    assert registry.active_count == 0
    assert runtime.shutdowns == ["code-task-1"]
