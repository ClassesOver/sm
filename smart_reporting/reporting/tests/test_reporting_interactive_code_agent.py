from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shlex
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import tiktoken
from agno.metrics import MessageMetrics
from agno.models.message import Message
from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.run import RunContext
from agno.tools.function import Function
from loguru import logger
from openai.types.responses import Response

from smart_reporting.reporting.agent import create_reporting_code_agent_factory
from smart_reporting.reporting.bootstrap import _VISUALIZATION_CODE_INSTRUCTIONS
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
from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime, ScriptProcessResult
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceRegistry,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.vision import ReportVisionReviewer
from smart_reporting.reporting.workflow.checkpoint import (
    ChartVisualInspectionIssue,
    ChartVisualInspectionReceipt,
    FileIdentity,
)
from smart_reporting.reporting.workflow.runtime import code_generation
from smart_reporting.reporting.workflow.runtime.base import _ANALYSIS_CODE_INSTRUCTIONS
from smart_reporting.reporting.workflow.runtime.code_generation import (
    VISUALIZATION_BUDGET_GATE_SAFETY_MARGIN,
    CodeGenerationResult,
    ReportingCodeGenerationRunner,
)
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope

SOURCE = "from pathlib import Path\nPath('analysis/out.json').write_text('{}')\n"
FORMATTED_SOURCE = 'from pathlib import Path\n\nPath("analysis/out.json").write_text("{}")\n'
VISUAL_SOURCE = "from pathlib import Path\nPath('charts/chart.png').write_bytes(b'image')\n"
FORMATTED_VISUAL_SOURCE = (
    'from pathlib import Path\n\nPath("charts/chart.png").write_bytes(b"image")\n'
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


def _custom_response(name: str, raw_input: str, index: int = 1) -> Response:
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


def _batch_response(*responses: Response) -> Response:
    return responses[0].model_copy(update={
        "output": [item for response in responses for item in response.output],
    })


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
            return ScriptProcessResult(cell, 1)
        await workspace.awrite_text("task-1", "analysis/out.json", "{}")
        return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0)

    async def shutdown(self, session_id: str) -> None:
        self.shutdowns.append(session_id)


class FakeCodeMode:
    def __init__(self) -> None:
        self.cells: list[tuple[str, str]] = []
        self.shutdowns: list[str | None] = []

    async def arun(self, session_id: str, code: str) -> SimpleNamespace:
        self.cells.append((session_id, code))
        if code.startswith("%%bash"):
            match = re.search(r"> (.+)\nexit \$report_exit", code)
            assert match is not None
            Path(shlex.split(match.group(1))[0]).write_text("0\n", encoding="ascii")
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
        [_function("read_script"), _function("write_script"), _function("run")],
    )

    assert tools[0]["type"] == "function"
    assert tools[1]["type"] == "custom"
    assert tools[1]["name"] == "write_script"
    assert tools[1]["format"]["type"] == "grammar"
    assert tools[1]["format"]["syntax"] == "lark"
    assert "parameters" not in tools[1]
    assert tools[2]["type"] == "custom"


def test_custom_call_round_trip_uses_custom_output() -> None:
    model = _code_responses_model()
    parsed = model._parse_provider_response(
        _custom_response("run", "print('ok')")
    )
    call = parsed.tool_calls[0]

    assert json.loads(call["function"]["arguments"]) == {"code": "print('ok')"}
    assert call["provider_data"] == {
        "reporting_wire_type": "custom",
        "raw_input": "print('ok')",
    }
    replay = model._format_messages(
        _assistant_and_result_messages(call, {"ok": True})
    )
    assert [item["type"] for item in replay[-2:]] == [
        "custom_tool_call",
        "custom_tool_call_output",
    ]


@pytest.mark.parametrize("name,argument", [("run", "code"), ("write_script", "source")])
def test_custom_call_normalizes_provider_data_envelope(name: str, argument: str) -> None:
    model = _code_responses_model()
    source = "# Python\nprint('ok')\n"
    wrapped = json.dumps({"data": source})

    parsed = model._parse_provider_response(
        _custom_response(name, wrapped)
    )
    call = parsed.tool_calls[0]

    assert json.loads(call["function"]["arguments"]) == {argument: source}
    assert call["provider_data"] == {
        "reporting_wire_type": "custom",
        "raw_input": source,
        "provider_input_normalized": "data_envelope",
    }
    replay = model._format_messages(
        _assistant_and_result_messages(call, {"ok": True})
    )
    assert replay[-2]["input"] == source


def test_code_run_raw_protocol_metric_detects_any_normalized_custom_input() -> None:
    model = _code_responses_model()
    tools = [Function(name="write_script")]
    model.configure_code_run(tools, max_model_requests=4)
    model.get_request_params(messages=[], tools=tools)
    source = "# Python\nprint('ok')\n"

    model._parse_provider_response(_custom_response("write_script", source, 1))
    assert model.code_run_raw_protocol_correct() is True

    # 单层 data 信封：兼容解封执行，不记协议违规，单列 envelope 计数。
    model._parse_provider_response(
        _custom_response("write_script", json.dumps({"data": source}), 2)
    )
    assert model.code_run_raw_protocol_correct() is True
    assert model.code_run_envelope_normalized_inputs() == 1


def test_custom_call_preserves_plain_data_mapping_as_source() -> None:
    model = _code_responses_model()
    wrapped = json.dumps({"data": "销售额"})

    parsed = model._parse_provider_response(_custom_response("run", wrapped))

    assert json.loads(parsed.tool_calls[0]["function"]["arguments"]) == {
        "code": wrapped
    }


def test_custom_call_preserves_nested_mapping_as_source() -> None:
    model = _code_responses_model()
    source = "print('ok')\n"
    wrapped = json.dumps({"source": json.dumps({"data": source})})

    parsed = model._parse_provider_response(
        _custom_response("write_script", wrapped)
    )

    assert json.loads(parsed.tool_calls[0]["function"]["arguments"]) == {
        "source": wrapped
    }


def test_custom_call_preserves_non_wrapper_json_expression() -> None:
    model = _code_responses_model()
    expression = '{"first": 1, "second": 2}'

    parsed = model._parse_provider_response(
        _custom_response("run", expression)
    )

    assert json.loads(parsed.tool_calls[0]["function"]["arguments"]) == {
        "code": expression
    }


def test_custom_output_stays_custom_with_previous_response_id() -> None:
    model = ReportingCodeOpenAIResponses(
        id="gpt-5-test",
        api_key="test-key",
        base_url="http://localhost",
        store=True,
    )
    call = model._parse_provider_response(
        _custom_response("run", "print('ok')")
    ).tool_calls[0]
    messages = _assistant_and_result_messages(call, {"ok": True})
    messages[0].provider_data = {"response_id": "resp-previous"}

    assert model._format_messages(messages) == [
        {
            "type": "custom_tool_call_output",
            "call_id": "call-1",
            "output": '{"ok":true}',
        }
    ]


@pytest.mark.parametrize(
    ("item", "message"),
    [
        (
            {
                "id": "item-1",
                "call_id": "call-1",
                "name": "unknown_tool",
                "input": "payload",
                "type": "custom_tool_call",
            },
            "unknown name",
        ),
        (
            {
                "id": "item-1",
                "call_id": "call-1",
                "name": "run",
                "input": "",
                "type": "custom_tool_call",
            },
            "empty input",
        ),
        (
            {
                "call_id": "call-1",
                "name": "run",
                "input": "print(1)",
                "type": "custom_tool_call",
            },
            "missing id",
        ),
        (
            {
                "id": "item-1",
                "name": "run",
                "input": "print(1)",
                "type": "custom_tool_call",
            },
            "missing call_id",
        ),
    ],
)
def test_custom_protocol_rejects_invalid_provider_custom_call(
    item: dict[str, Any], message: str
) -> None:
    response = SimpleNamespace(error=None, output=[item])

    with pytest.raises(ReportingError) as caught:
        _code_responses_model()._parse_provider_response(response)

    assert caught.value.code == "report_code_custom_tool_protocol_error", message
    assert caught.value.details == {"retryable": False}


def _synthetic_custom_call_for_replay(
    *,
    item_id: str = "item-1",
    call_id: str = "call-1",
    name: str = "run",
    raw_input: str = "print('ok')",
) -> dict[str, Any]:
    argument = "source" if name == "write_script" else "code"
    return {
        "id": item_id,
        "call_id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(
                {argument: raw_input}, ensure_ascii=False, separators=(",", ":")
            ),
        },
        "provider_data": {
            "reporting_wire_type": "custom",
            "raw_input": raw_input,
        },
    }


@pytest.mark.parametrize(
    "messages",
    [
        [
            Message(
                role="assistant",
                tool_calls=[_synthetic_custom_call_for_replay()],
            ),
            Message(
                role="tool",
                content="ok",
                tool_call_id="call-1",
                tool_name="run",
            ),
            Message(
                role="assistant",
                tool_calls=[
                    _synthetic_custom_call_for_replay(
                        item_id="item-2", call_id="call-1"
                    )
                ],
            ),
            Message(
                role="tool",
                content="ok",
                tool_call_id="call-1",
                tool_name="run",
            ),
        ],
        _assistant_and_result_messages(
            {
                **_synthetic_custom_call_for_replay(),
                "provider_data": {
                    "reporting_wire_type": "custom",
                    "raw_input": "forged",
                },
            },
            {"ok": True},
        ),
        _assistant_and_result_messages(
            {
                **_synthetic_custom_call_for_replay(),
                "function": {
                    "name": "run",
                    "arguments": '{"code":"forged"}',
                },
            },
            {"ok": True},
        ),
        [
            Message(
                role="assistant", tool_calls=[_synthetic_custom_call_for_replay()]
            ),
            Message(
                role="tool",
                content="ok",
                tool_call_id="call-wrong",
                tool_name="run",
            ),
        ],
        [
            Message(
                role="assistant", tool_calls=[_synthetic_custom_call_for_replay()]
            ),
            Message(
                role="tool",
                content="ok",
                tool_call_id="call-1",
                tool_name="write_script",
            ),
        ],
        _assistant_and_result_messages(
            {
                "id": "item-1",
                "call_id": "call-1",
                "type": "function",
                "function": {"name": "run_script", "arguments": "{}"},
            },
            {"ok": True},
        )[:-1]
        + [
            Message(
                role="tool",
                content="ok",
                tool_call_id="call-1",
                tool_name="run",
            )
        ],
        _assistant_and_result_messages(_synthetic_custom_call_for_replay(), {"ok": True})
        + [
            Message(
                role="tool",
                content="duplicate",
                tool_call_id="call-1",
                tool_name="run",
            )
        ],
        [
            Message(
                role="assistant", tool_calls=[_synthetic_custom_call_for_replay()]
            )
        ],
    ],
    ids=[
        "duplicate-call-identity",
        "forged-raw-input",
        "decoded-argument-mismatch",
        "wrong-result-id",
        "wrong-result-name",
        "freeform-result-on-function-call",
        "duplicate-result",
        "missing-result",
    ],
)
def test_custom_replay_rejects_invalid_history(messages: list[Message]) -> None:
    with pytest.raises(ReportingError) as caught:
        _code_responses_model()._format_messages(messages)

    assert caught.value.code == "report_code_custom_tool_protocol_error"
    assert caught.value.details == {"retryable": False}


def test_custom_protocol_preserves_mixed_batch_order_and_replay() -> None:
    model = _code_responses_model()
    response = _batch_response(
        _function_response(1, "read_script", {}),
        _custom_response("write_script", SOURCE, 2),
        _function_response(3, "run_script", {}),
        _custom_response("run", "print(1)", 4),
    )
    parsed = model._parse_provider_response(response)
    assert [call["function"]["name"] for call in parsed.tool_calls] == [
        "read_script", "write_script", "run_script", "run",
    ]
    assert parsed.extra["tool_call_ids"] == ["call-1", "call-2", "call-3", "call-4"]
    messages = [Message(role="assistant", tool_calls=parsed.tool_calls)]
    messages.extend(
        _assistant_and_result_messages(call, {"ok": True})[1]
        for call in parsed.tool_calls
    )
    replay = model._format_messages(messages)
    calls = [item for item in replay if item.get("type") in {"function_call", "custom_tool_call"}]
    results = [item for item in replay if item.get("type", "").endswith("_output")]
    assert [item["type"] for item in calls] == [
        "function_call", "custom_tool_call", "function_call", "custom_tool_call",
    ]
    assert [item["type"] for item in results] == [
        "function_call_output", "custom_tool_call_output",
        "function_call_output", "custom_tool_call_output",
    ]
    assert [item["call_id"] for item in calls] == [item["call_id"] for item in results]
    assert calls[1]["input"] == SOURCE
    assert calls[3]["input"] == "print(1)"


@pytest.mark.parametrize("identity", ["id", "call_id"])
def test_custom_protocol_rejects_duplicate_batch_identity(identity: str) -> None:
    first = _custom_response("write_script", SOURCE, 1)
    second = _function_response(2, "run_script", {})
    second.output[0] = second.output[0].model_copy(update={
        identity: getattr(first.output[0], identity),
    })
    with pytest.raises(ReportingError, match="身份重复"):
        _code_responses_model()._parse_provider_response(_batch_response(first, second))


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

    assert params["parallel_tool_calls"] is True
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

    assert params["parallel_tool_calls"] is True
    assert params["tool_choice"] == "auto"


def test_code_request_projection_records_final_prefix_fingerprints() -> None:
    model = _code_responses_model()
    model._code_request_metrics = [{"status": "started", "requestParams": {}}]
    model.get_request_params(
        messages=[
            Message(role="system", content="stable-system"),
            Message(role="user", content="dynamic-task"),
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "result",
                "schema": {"type": "object", "properties": {}},
                "strict": True,
            },
        },
        tools=[_function("run_script")],
    )
    expected = {
        "model": "test-model",
        "reasoningEffort": "unknown",
        "reasoningSummary": "unknown",
        "enableThinking": "unknown",
        "enableThinkingLocation": "omitted",
        "maxOutputTokens": "unknown",
        "parallelToolCalls": True,
        "toolChoice": "auto",
        "extraBodyKeys": [],
        "systemPrefixSha256": "7891eaae9e4d51e08d65af72db059d118bb2837ae8b74ee99d9eaa819ffaa302",
        "systemPrefixBytes": 48,
        "toolDeclarationsSha256": "0bd6752f120b0cb8dd6344012ad8c49ce33b00abb12eed1490fb8f73f5aee281",
        "toolDeclarationsBytes": 115,
        "schemaSha256": "0da85c7fc4faab0c8ebac1ff63adca7210346c9f993c536ef956b39b0061549a",
        "schemaBytes": 95,
    }
    assert model._code_last_request_params == expected
    assert model.code_run_request_metrics()[0]["requestParams"] == expected


def test_code_request_projection_uses_previous_response_wire_messages() -> None:
    model = ReportingCodeOpenAIResponses(
        id="gpt-5-test",
        api_key="test-key",
        base_url="http://localhost",
        store=True,
    )
    messages = [
        Message(role="system", content="prior-system"),
        Message(
            role="assistant",
            content="prior-answer",
            provider_data={"response_id": "resp-previous"},
        ),
        Message(role="user", content="continue"),
    ]
    model._code_request_metrics = [{"status": "started", "requestParams": {}}]

    params = model.get_request_params(messages=messages, tools=[])

    assert params["previous_response_id"] == "resp-previous"
    assert model._format_messages(messages) == [
        {"role": "user", "content": "continue"}
    ]
    assert model._code_last_request_params["systemPrefixSha256"] == "unknown"
    assert model._code_last_request_params["systemPrefixBytes"] == "unknown"
    assert model.code_run_request_metrics()[0]["requestParams"] == (
        model._code_last_request_params
    )


def test_empty_request_fingerprint_is_unknown() -> None:
    assert ReportingCodeOpenAIResponses._request_fingerprint({}) == (
        "unknown",
        "unknown",
    )


@pytest.mark.anyio
async def test_code_model_response_emits_request_progress_with_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def provider_invoke(
        _model: OpenAIResponses, _messages: list[Message], *_args: Any, **_kwargs: Any
    ) -> SimpleNamespace:
        return SimpleNamespace(
            output=[],
            error=None,
            response_usage=MessageMetrics(
                input_tokens=120,
                output_tokens=50,
                total_tokens=170,
                reasoning_tokens=30,
                cache_read_tokens=80,
                time_to_first_token=0.25,
            ),
        )

    monkeypatch.setattr(OpenAIResponses, "ainvoke", provider_invoke)
    model = _code_responses_model()
    model.configure_code_run([_function("run_script")], max_model_requests=4)
    monkeypatch.setattr(model, "_project", lambda messages, _args, _kwargs: messages)
    records: list[dict[str, object]] = []
    sink_id = logger.add(
        lambda message: records.append(dict(message.record["extra"])),
        filter=lambda record: record["extra"].get("reporting_progress")
        == "code_model_request",
    )
    try:
        await model.ainvoke([])
        await model.ainvoke([])
    finally:
        logger.remove(sink_id)

    assert [
        {
            "reporting_progress": item["reporting_progress"],
            "model_id": item["model_id"],
            "request_index": item["request_index"],
            "request_limit": item["request_limit"],
            "status": item["status"],
            **(
                {
                    "input_tokens": item["input_tokens"],
                    "output_tokens": item["output_tokens"],
                    "reasoning_tokens": item["reasoning_tokens"],
                    "visible_output_tokens": item["visible_output_tokens"],
                    "cache_read_tokens": item["cache_read_tokens"],
                    "time_to_first_token_seconds": item["time_to_first_token_seconds"],
                }
                if item["status"] == "completed"
                else {}
            ),
        }
        for item in records
    ] == [
        {
            "reporting_progress": "code_model_request",
            "model_id": "test-model",
            "request_index": 1,
            "request_limit": 4,
            "status": "started",
        },
        {
            "reporting_progress": "code_model_request",
            "model_id": "test-model",
            "request_index": 1,
            "request_limit": 4,
            "status": "completed",
            "input_tokens": 120,
            "output_tokens": 50,
            "reasoning_tokens": 30,
            "visible_output_tokens": 20,
            "cache_read_tokens": 80,
            "time_to_first_token_seconds": 0.25,
        },
        {
            "reporting_progress": "code_model_request",
            "model_id": "test-model",
            "request_index": 2,
            "request_limit": 4,
            "status": "started",
        },
        {
            "reporting_progress": "code_model_request",
            "model_id": "test-model",
            "request_index": 2,
            "request_limit": 4,
            "status": "completed",
            "input_tokens": 120,
            "output_tokens": 50,
            "reasoning_tokens": 30,
            "visible_output_tokens": 20,
            "cache_read_tokens": 80,
            "time_to_first_token_seconds": 0.25,
        },
    ]


@pytest.mark.anyio
async def test_code_model_keeps_bounded_request_metrics_for_task_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        (
            SimpleNamespace(
                response_usage=MessageMetrics(
                    input_tokens=120,
                    output_tokens=50,
                    reasoning_tokens=30,
                    cache_read_tokens=80,
                ),
                tool_calls=[
                    {
                        "id": "item-1",
                        "call_id": "call-1",
                        "type": "function",
                        "function": {"name": "write_script", "arguments": "{}"},
                    }
                ],
            ),
            SimpleNamespace(response_usage=None, tool_calls=[]),
        )
    )

    async def provider_invoke(
        _model: OpenAIResponses, _messages: list[Message], *_args: Any, **_kwargs: Any
    ) -> SimpleNamespace:
        return next(responses)

    monkeypatch.setattr(OpenAIResponses, "ainvoke", provider_invoke)
    model = _code_responses_model()
    model.configure_code_run([_function("write_script")], max_model_requests=4)
    monkeypatch.setattr(model, "_project", lambda messages, _args, _kwargs: messages)

    await model.ainvoke([])
    await model.ainvoke([])

    metrics = model.code_run_request_metrics()
    assert len(metrics) == 2
    assert metrics[0] == {
        "requestIndex": 1,
        "providerRequestId": "unknown",
        "durationMs": metrics[0]["durationMs"],
        "inputTokens": 120,
        "outputTokens": 50,
        "reasoningTokens": 30,
        "visibleOutputTokens": 20,
        "cacheReadTokens": 80,
        "timeToFirstTokenSeconds": "unknown",
        "toolNames": ["write_script"],
        "toolCalls": [{"id": "call-1", "name": "write_script"}],
        "toolCallCount": 1,
        "requestParams": {},
        "status": "completed",
    }
    assert isinstance(metrics[0]["durationMs"], int)
    assert metrics[0]["durationMs"] >= 0
    assert metrics[1] == {
        "requestIndex": 2,
        "providerRequestId": "unknown",
        "durationMs": metrics[1]["durationMs"],
        "inputTokens": "unknown",
        "outputTokens": "unknown",
        "reasoningTokens": "unknown",
        "visibleOutputTokens": "unknown",
        "cacheReadTokens": "unknown",
        "timeToFirstTokenSeconds": "unknown",
        "toolNames": [],
        "toolCalls": [],
        "toolCallCount": 0,
        "requestParams": {},
        "status": "completed",
    }


@pytest.mark.anyio
async def test_code_model_keeps_started_metric_when_provider_request_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()

    async def provider_invoke(
        _model: OpenAIResponses, _messages: list[Message], *_args: Any, **_kwargs: Any
    ) -> SimpleNamespace:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(OpenAIResponses, "ainvoke", provider_invoke)
    model = _code_responses_model()
    model.configure_code_run([_function("write_script")], max_model_requests=4)
    monkeypatch.setattr(model, "_project", lambda messages, _args, _kwargs: messages)

    request = asyncio.create_task(model.ainvoke([]))
    await entered.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request

    assert model.code_run_request_metrics() == [
        {
            "requestIndex": 1,
            "providerRequestId": "unknown",
            "durationMs": "unknown",
            "inputTokens": "unknown",
            "outputTokens": "unknown",
            "reasoningTokens": "unknown",
            "visibleOutputTokens": "unknown",
            "cacheReadTokens": "unknown",
            "timeToFirstTokenSeconds": "unknown",
            "toolNames": [],
            "toolCalls": [],
            "toolCallCount": 0,
            "requestParams": {},
            "status": "started",
        }
    ]


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
            [], Message(role="assistant", content=""), None, [_function("run")]
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
        "```run\nprint('must not run')\n```",
        (
            '<｜DSML｜tool_calls>\n<｜DSML｜invoke name="run">\n'
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
    process = await runtime.execute_script_process(
        "task-1", workspace, "analysis/a.py", matplotlib_agg=False
    )
    assert process.exit_code == 0
    assert code_mode.cells[-1][1].startswith("%%bash\n")
    assert "exec(compile(" not in code_mode.cells[-1][1]
    assert "analysis/a.py" in code_mode.cells[-1][1]
    assert "__REPORT_EXIT__" not in code_mode.cells[-1][1]
    assert list((workspace.identity.root / ".reporting-exits").iterdir()) == []


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
    reviewed = _visual_receipt(output).model_copy(
        update={
            "issues": (
                ChartVisualInspectionIssue(
                    category="missing_units",
                    severity="warning",
                    description="纵轴单位可以更明确。",
                ),
            ),
            "summary": "图表可交付，但仍有非阻断优化项。",
            "warnings": ("单位说明可优化。",),
            "suggestions": ("补充纵轴单位。",),
        }
    )
    reviewer.review.return_value = reviewed

    result = await toolkit.view_image("charts/chart.png", detail="original")

    assert result == {
        "ok": True,
        "receipt": {
            "sourcePath": output.path,
            "sha256": output.sha256,
            "visualReviewStatus": "passed",
            "reviewed": True,
            "requiresRevision": False,
            "warningCount": 1,
            "message": "非阻断问题已记录，无需修改。",
        },
        "freshReviewCount": 1,
    }
    assert binding.visual_inspection_receipts == {"charts/chart.png": reviewed}
    assert toolkit.visual_review_duration_ms >= 0
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
    reviewed = _visual_receipt(output).model_copy(
        update={
            "issues": (
                ChartVisualInspectionIssue(
                    category="missing_units",
                    severity="warning",
                    description="缓存中的 warning 不得返回模型。",
                ),
            ),
            "warnings": ("缓存 warning 文本",),
            "suggestions": ("缓存 suggestion 文本",),
        }
    )
    binding.visual_inspection_receipts[output.path] = reviewed
    reviewer.review.return_value = reviewed

    result = await toolkit.view_image(output.path)

    assert result["receipt"] == {
        "sourcePath": output.path,
        "sha256": output.sha256,
        "visualReviewStatus": "passed",
        "reviewed": True,
        "requiresRevision": False,
        "warningCount": 1,
        "message": "非阻断问题已记录，无需修改。",
    }
    reviewer.review.assert_not_awaited()


@pytest.mark.anyio
async def test_view_image_returns_only_critical_repair_context(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    reviewer = AsyncMock(spec=ReportVisionReviewer)
    binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, runtime, reviewer
    )
    reviewed = _visual_receipt(output, requires_revision=True).model_copy(
        update={
            "issues": (
                ChartVisualInspectionIssue(
                    category="text_overlap",
                    severity="critical",
                    description="体检中心标签与数值完全重叠。",
                ),
                ChartVisualInspectionIssue(
                    category="missing_units",
                    severity="warning",
                    description="纵轴单位可以更明确。",
                ),
            ),
            "summary": "包含 critical 和 warning。",
            "warnings": ("非阻断 warning 文本",),
            "suggestions": ("可能只对应 warning 的全局建议",),
        }
    )
    reviewer.review.return_value = reviewed

    result = await toolkit.view_image(output.path)

    assert result == {
        "ok": True,
        "receipt": {
            "sourcePath": output.path,
            "sha256": output.sha256,
            "visualReviewStatus": "passed",
            "reviewed": True,
            "requiresRevision": True,
            "criticalIssues": [
                {
                    "category": "text_overlap",
                    "severity": "critical",
                    "description": "体检中心标签与数值完全重叠。",
                }
            ],
        },
        "freshReviewCount": 1,
    }
    assert binding.visual_inspection_receipts[output.path] == reviewed
    assert "纵轴单位" not in str(result)
    assert "全局建议" not in str(result)


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
    assert toolkit.terminal_failure is not None
    assert toolkit.terminal_failure.details["retryable"] is False
    assert not toolkit.binding.visual_inspection_receipts


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["write", "restart"])
async def test_visual_review_state_is_retained_until_next_execution(
    operation: str,
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    binding, toolkit, output = await _prepared_visualization_toolkit(workspace, runtime)
    binding.visual_inspection_receipts[output.path] = _visual_receipt(output)
    assert binding.execution_receipt is not None
    toolkit.submitted_receipt = binding.execution_receipt

    receipt = binding.execution_receipt
    if operation == "write":
        await toolkit.write_script(VISUAL_SOURCE)
        assert binding.execution_receipt is None
        assert toolkit.submitted_receipt is None
    else:
        # 重启只重置探索内核；脚本回执基于文件哈希，未改动的产物无需重跑重审。
        await toolkit.restart_code_mode()
        assert binding.execution_receipt is receipt
        assert toolkit.submitted_receipt is receipt

    assert binding.visual_inspection_receipts == {output.path: _visual_receipt(output)}


@pytest.mark.anyio
async def test_successful_visual_rerun_reuses_review_for_unchanged_output(
    workspace: HostReportingWorkspace,
) -> None:
    class Runtime(ToolkitRuntime):
        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_text("task-1", "charts/chart.png", "image")
            return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0)

    reviewer = AsyncMock(spec=ReportVisionReviewer)
    binding, toolkit, output = await _prepared_visualization_toolkit(
        workspace, Runtime(), reviewer
    )
    reviewed = _visual_receipt(output)
    binding.visual_inspection_receipts[output.path] = reviewed

    await toolkit.write_script("print('updated source')\n")
    run = await toolkit.run_script()
    view = await toolkit.view_image(output.path)

    assert run["ok"] is True
    assert binding.visual_inspection_receipts == {output.path: reviewed}
    assert view["receipt"]["sha256"] == output.sha256
    reviewer.review.assert_not_awaited()


@pytest.mark.anyio
async def test_visual_rerun_does_not_reuse_review_requiring_revision(
    workspace: HostReportingWorkspace,
) -> None:
    class Runtime(ToolkitRuntime):
        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_text("task-1", "charts/chart.png", "image")
            return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0)

    binding, toolkit, output = await _prepared_visualization_toolkit(workspace, Runtime())
    binding.visual_inspection_receipts[output.path] = _visual_receipt(
        output, requires_revision=True
    )

    run = await toolkit.run_script()

    assert run["ok"] is True
    assert binding.visual_inspection_receipts == {}


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
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("print('ok')", 'print("ok")\n'),
        ("print('a')\r\nprint('b')\r", 'print("a")\nprint("b")\n'),
    ],
)
async def test_write_script_normalizes_repairable_freeform_text(
    binding: ReportingCodingTaskBinding,
    runtime: ToolkitRuntime,
    source: str,
    expected: str,
) -> None:
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())

    result = await toolkit.write_script(source)

    assert result["ok"] is True
    assert await binding.workspace.aread_text(
        binding.context.task_id, binding.context.script_path
    ) == expected


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
    await toolkit.write_script(_valid_source())
    binding.execution_receipt = _receipt()
    await _write_output(binding.workspace, "analysis/out.json")
    runtime.next_cell = _failed_cell("ValueError: bad")
    result = await toolkit.run_script()
    assert result["ok"] is False
    assert binding.execution_receipt is None
    assert not await binding.workspace.apath_exists("task", "analysis/out.json")


@pytest.mark.anyio
async def test_invalid_source_run_preserves_previous_declared_output(
    binding: ReportingCodingTaskBinding,
    runtime: ToolkitRuntime,
) -> None:
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script("if True print('broken')\n")
    await binding.workspace.awrite_text("task", "analysis/out.json", '{"old":true}')

    result = await toolkit.run_script()

    assert result["code"] == "report_code_source_invalid"
    assert await binding.workspace.aread_text("task", "analysis/out.json") == '{"old":true}'


@pytest.mark.anyio
async def test_runner_uses_one_multitool_run_and_returns_submission(
    workspace: HostReportingWorkspace,
) -> None:
    created = []

    class Runtime:
        shutdowns: list[str] = []

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_text("task-1", "analysis/out.json", "{}")
            return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0)

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
    assert created[0].tool_call_limit == 30
    assert created[0].model.parallel_tool_calls is False


def test_runner_binds_full_host_task_context_to_trace_metadata(
    workspace: HostReportingWorkspace,
    monkeypatch,
) -> None:
    traced_metadata = []

    class TraceMetadata:
        def __init__(self, metadata: dict[str, Any]) -> None:
            self.metadata = metadata

        def __enter__(self) -> None:
            traced_metadata.append(self.metadata)

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        code_generation,
        "using_metadata",
        lambda metadata: TraceMetadata(metadata),
    )

    with ReportingCodeGenerationRunner._trace_task_context(_task_context(workspace)):
        pass

    assert traced_metadata == [
        {
            "reportingCodingTaskContext": {
                "task_id": "task-1",
                "task_kind": "analysis",
                "code_mode_session_id": "code-task-1",
                "workspace_key": workspace.identity.workspace_key,
                "workspace_root": str(workspace.identity.root),
                "script_path": "analysis/a.py",
                "authorized_read_paths": [],
                "authorized_write_paths": ["analysis/a.py", "analysis/out.json"],
                "declared_output_paths": ["analysis/out.json"],
                "max_source_bytes": 128 * 1024,
            }
        }
    ]


def test_runner_projects_only_model_visible_task_fields(
    workspace: HostReportingWorkspace,
) -> None:
    context = _task_context(workspace)

    payload = ReportingCodeGenerationRunner._model_task_payload(context)

    assert payload == {
        "task_kind": "analysis",
        "script_path": "analysis/a.py",
        "authorized_read_paths": [],
        "authorized_write_paths": ["analysis/a.py", "analysis/out.json"],
        "declared_output_paths": ["analysis/out.json"],
        "max_source_bytes": 128 * 1024,
    }
    assert context.task_id == "task-1"
    assert context.code_mode_session_id == "code-task-1"
    assert context.workspace_key == workspace.identity.workspace_key
    assert context.workspace_root == workspace.identity.root


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
            return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0)

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
    assert caught.value.details["retryable"] is False
    assert caught.value.details["terminationReason"] == "model_ended_without_submission"
    assert caught.value.details["lastFailure"] is None
    assert caught.value.details["completedToolCalls"] == 0
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
    assert first.model.parallel_tool_calls is True
    assert first.tools[0] is not second.tools[0]
    instructions = "\n".join(str(item) for item in first.instructions)
    assert "REPORTING_CODE_DELIVERY_STATE.nextTools" in instructions
    assert "当前工具声明" in instructions
    assert "首轮思考聚焦实现、边界条件与正确性" in instructions
    assert "不重复推导已给事实" in instructions
    assert "对 run_script 返回的图片输出调用 view_image 审查，全部通过后再 submit_script" in instructions
    assert "建议把当前待审图片一次性批量传入 view_image 的 `paths` 数组" in instructions
    assert "custom input" not in instructions
    assert "JSON 包装" not in instructions
    assert "Markdown 围栏" not in instructions
    assert "source 参数" not in instructions
    assert "code 参数" not in instructions


def test_code_agent_factory_projects_only_task_specific_common_instructions() -> None:
    model = OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost")
    analysis = create_reporting_code_agent_factory(
        model=model,
        name="analysis-code-agent",
        task_kind="analysis",
    )([_function("write_script")])
    visualization = create_reporting_code_agent_factory(
        model=model,
        name="visualization-code-agent",
        task_kind="visualization",
    )([_function("write_script")])

    analysis_instructions = "\n".join(str(item) for item in analysis.instructions)
    visualization_instructions = "\n".join(
        str(item) for item in visualization.instructions
    )
    assert "view_image" not in analysis_instructions
    assert "中文图表字体" not in analysis_instructions
    assert "期间计算" in analysis_instructions
    assert "view_image" in visualization_instructions
    assert "中文图表字体" in visualization_instructions
    assert "期间计算" not in visualization_instructions
    assert analysis.__dict__["_reporting_instruction_components"] == {
        "common": tuple(analysis.instructions),
        "stage": (),
    }


def test_task_specific_code_instructions_delegate_wire_protocol_and_fit_budget() -> None:
    model = OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost")
    agents = {
        "analysis": create_reporting_code_agent_factory(
            model=model,
            name="analysis-code-agent",
            task_kind="analysis",
            instructions=_ANALYSIS_CODE_INSTRUCTIONS,
        )([]),
        "visualization": create_reporting_code_agent_factory(
            model=model,
            name="visualization-code-agent",
            task_kind="visualization",
            instructions=_VISUALIZATION_CODE_INSTRUCTIONS,
        )([]),
    }
    budgets = {
        "analysis": {"bytes": 3_100, "cl100k_tokens": 940},
        # 2026-09-24：可视化公共指令追加反探索占位要求（真实运行 attempt-1
        # 占位脚本导致 declared_output_missing 重试循环的证据驱动改动），
        # 预算从 4_500/1_400 上调。
        # 2026-09-24：追加 view_image 批量审查提示与反占位要求后，
        # 可视化公共指令预算再次上调。
        # 2026-09-24：view_image 提示追加自动分批说明后微调至 1_520 tokens。
        # 2026-09-24：追加 facts/supplement 数据形状契约后上调至 5_100/1_600。
        # 2026-09-24：追加禁止通用 resolve() 后上调至 5_300/1_650。
        # 2026-09-24：追加禁止通用 helper / f-string / os.path.join 构造路径后上调至 5_600/1_750。
        "visualization": {"bytes": 5_600, "cl100k_tokens": 1_750},
    }
    tokenizer = tiktoken.get_encoding("cl100k_base")

    for task_kind, agent in agents.items():
        instructions = "\n".join(str(item) for item in agent.instructions)
        assert len(instructions.encode("utf-8")) <= budgets[task_kind]["bytes"]
        assert len(tokenizer.encode(instructions)) <= budgets[task_kind]["cl100k_tokens"]
        assert "REPORTING_CODE_DELIVERY_STATE.nextTools" in instructions
        assert "脚本不存在时" not in instructions
        assert "JSON 信封" not in instructions
        assert "Markdown 围栏" not in instructions
        if task_kind == "visualization":
            # 数据形状规则只作用于未物化 chartInputs 的回退图，不能无条件导向原始 facts。
            assert "chartInputs" in instructions
            assert "数据形状契约" not in instructions
            assert "行对象数组" in instructions
            assert "columns+rows" in instructions
            assert "禁止编写通用 resolve()" in instructions
        assert instructions.count("cwd") == 1
        assert instructions.count("__file__") == 1


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
                return ScriptProcessResult(_failed_cell("SyntaxError: invalid syntax"), 1)
            exists = await received.apath_exists("task-1", "analysis/out.json")
            await received.awrite_text(
                "task-1", "analysis/out.json", "{}", overwrite=exists
            )
            return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0)

        async def shutdown(self, _session_id):
            return None

    runtime = Runtime()
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script("if True print('broken')\n")
    assert (await toolkit.run_script())["ok"] is False
    await toolkit.write_script(SOURCE)
    assert (await toolkit.run("print('probe')"))["ok"] is True
    assert (await toolkit.run_script())["ok"] is True
    submitted = await toolkit.submit_script()
    assert submitted["ok"] is True
    receipt = ExecutionReceipt.model_validate(submitted["executionReceipt"])
    assert receipt.source_file == binding.execution_receipt.source_file
    assert receipt.output_files == binding.execution_receipt.output_files


@pytest.mark.anyio
@pytest.mark.parametrize("batched", [False, True])
async def test_interactive_v1_end_to_end_responses_loop(
    workspace: HostReportingWorkspace,
    batched: bool,
) -> None:
    broken_source = FORMATTED_SOURCE.replace('write_text("{}")', 'write_text("{}"')
    repair_patch = (
        "*** Begin Edit\n"
        f"*** SHA256: {hashlib.sha256(broken_source.encode()).hexdigest()}\n"
        "<<<<<<< SEARCH\n"
        'write_text("{}"\n'
        "=======\n"
        'write_text("{}")\n'
        ">>>>>>> REPLACE\n"
        "*** End Edit"
    )
    responses = [
        _custom_response("write_script", broken_source, 1),
        _function_response(2, "run_script", {}),
        _custom_response("run", "print('probe')", 3),
        _custom_response("edit_script", repair_patch, 4),
        _function_response(5, "lsp_diagnostics", {}),
        _function_response(6, "search_knowledge", {"query": "脚本规范"}),
        _function_response(7, "run_script", {}),
        _function_response(8, "submit_script", {}),
    ]
    if batched:
        responses = [
            _batch_response(
                *responses[:2],
                _custom_response("run", "print('must not run')", 9),
            ),
            _batch_response(*responses[2:6]),
                _batch_response(
                    *responses[6:],
                    _custom_response("run", "print('must not run')", 10),
                ),
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

        async def execute(self, session_id, received, code, **kwargs):
            assert session_id == "code-task-1"
            assert received is workspace
            assert code == "print('probe')"
            assert kwargs == {"matplotlib_agg": False}
            return SimpleNamespace(
                status="ok", stdout="probe\n", stderr="", traceback=None
            )

        async def execute_script_process(self, _session_id, received, _path, **_kwargs):
            await received.awrite_text("task-1", "analysis/out.json", "{}")
            return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0)

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
            assert text == FORMATTED_SOURCE
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
    assert await workspace.aread_text("task-1", "analysis/a.py") == FORMATTED_SOURCE
    assert runtime.shutdowns == ["code-task-1"]
    assert len(client.requests) == (3 if batched else 8)
    assert responses == []
    request_tools = [tool for request in client.requests for tool in request["tools"]]
    assert {tool["type"] for tool in request_tools} == {"custom", "function"}
    assert not any(
        tool["type"] == "function" and tool["name"] in {"write_script", "run"}
        for tool in request_tools
    )
    replay_types = [
        item.get("type")
        for request in client.requests[1:]
        for item in request["input"]
        if isinstance(item, dict)
    ]
    assert "custom_tool_call_output" in replay_types
    assert "function_call_output" in replay_types


@pytest.mark.anyio
async def test_interactive_visual_repair_end_to_end_uses_text_only_receipts(
    workspace: HostReportingWorkspace,
) -> None:
    visual_patch = (
        "*** Begin Edit\n"
        f"*** SHA256: {hashlib.sha256(FORMATTED_VISUAL_SOURCE.encode()).hexdigest()}\n"
        "<<<<<<< SEARCH\n"
        'b"image"\n'
        "=======\n"
        'b"image-v2"\n'
        ">>>>>>> REPLACE\n"
        "*** End Edit"
    )
    responses = [
        _custom_response("write_script", VISUAL_SOURCE, 1),
        _function_response(2, "run_script", {}),
        _function_response(3, "view_image", {"path": "charts/chart.png"}),
        _custom_response("edit_script", visual_patch, 4),
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
            return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0)

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
                    {
                        "category": "missing_units",
                        "severity": "warning",
                        "description": "wire warning 不得进入后续模型输入。",
                    },
                )
                if requires_revision
                else (),
                summary=(
                    "wire summary 不得进入后续模型输入。"
                    if requires_revision
                    else "图表清晰。"
                ),
                warnings=("wire warnings 不得进入后续模型输入。",)
                if requires_revision
                else (),
                suggestions=("wire suggestion 不得进入后续模型输入。",)
                if requires_revision
                else (),
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
    coding_metrics: list[dict[str, Any]] = []
    result = await ReportingCodeGenerationRunner(
        agent_factory,
        runtime,
        ReportingLspProcessManager(),
        registry=registry,
        vision_reviewer=reviewer,
        coding_metrics_recorder=coding_metrics.append,
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
    assert coding_metrics[0]["firstRepairSuccess"] is True
    request_history = json.dumps(client.requests, ensure_ascii=False, default=str)
    assert "关键标题完全重叠" in request_history
    assert "wire warning" not in request_history
    assert "wire summary" not in request_history
    assert "wire suggestion" not in request_history
    assert "image_url" not in request_history
    assert "data:image" not in request_history
    request_tools = [tool for request in client.requests for tool in request["tools"]]
    assert any(tool["type"] == "custom" and tool["name"] == "write_script" for tool in request_tools)
    assert any(tool["type"] == "custom" and tool["name"] == "edit_script" for tool in request_tools)
    assert not any(
        tool["type"] == "function" and tool["name"] == "write_script"
        for tool in request_tools
    )
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
            return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0)

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
            return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr="", traceback=None), 0)

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



def _visualization_model_with_budget(
    toolkit: ReportingCodeModeToolkit,
    tool_call_limit: int,
    used_tool_calls: int,
) -> ReportingCodeOpenAIResponses:
    model = ReportingCodeOpenAIResponses(
        id="gate-test", api_key="test-key", base_url="http://localhost"
    )
    model.configure_code_run(
        toolkit.tool_functions,
        max_model_requests=10,
        delivery_state_reader=toolkit.delivery_state,
        tool_call_limit=tool_call_limit,
        visual_budget_gate_safety_margin=VISUALIZATION_BUDGET_GATE_SAFETY_MARGIN,
    )
    model._code_budget.tool_calls = used_tool_calls
    model._code_request_metrics = [{"status": "started", "requestParams": {}}]
    return model


async def _reviewed_toolkit_with_draft(
    workspace: HostReportingWorkspace, runtime: ToolkitRuntime
) -> ReportingCodeModeToolkit:
    """图片已审查、交付状态额外放行 edit_script：唯一可成功的动作就是提交。"""

    from smart_reporting.reporting.code_agent.toolkit import _RejectedDraft

    binding, toolkit, output = await _prepared_visualization_toolkit(workspace, runtime)
    binding.visual_inspection_receipts[output.path] = _visual_receipt(output)
    toolkit._rejected_draft = _RejectedDraft("d" * 64, "x = 1\n", None)
    await toolkit.refresh_delivery_state()
    assert toolkit.delivery_state()["nextTools"] == ["submit_script", "edit_script"]
    return toolkit


@pytest.mark.anyio
async def test_visual_budget_gate_forces_submit_when_outputs_present_and_budget_low(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    toolkit = await _reviewed_toolkit_with_draft(workspace, runtime)
    tool_limit = 10
    model = _visualization_model_with_budget(toolkit, tool_limit, tool_limit - 1)

    params = model.get_request_params(
        messages=[Message(role="user", content="go")],
        tools=toolkit.tool_functions,
    )

    assert [tool["name"] for tool in params["tools"]] == ["submit_script"]
    warnings = model.code_run_request_metrics()[-1].get("warnings", [])
    assert any(
        warning["code"] == "report_code_visual_budget_gate_forced_submit"
        for warning in warnings
    )
    details = warnings[0]["details"]
    assert details["remainingToolCalls"] == 1
    assert isinstance(details["viewImageRounds"], int)


@pytest.mark.anyio
async def test_visual_budget_gate_keeps_review_chain_while_images_unreviewed(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    _binding, toolkit, _output = await _prepared_visualization_toolkit(workspace, runtime)
    await toolkit.refresh_delivery_state()
    tool_limit = 10
    model = _visualization_model_with_budget(toolkit, tool_limit, tool_limit - 2)

    params = model.get_request_params(
        messages=[Message(role="user", content="go")],
        tools=toolkit.tool_functions,
    )

    # 未审查图片时强制 submit_script 必然失败；剩余预算仍够审查后提交。
    assert [tool["name"] for tool in params["tools"]] == ["submit_script", "view_image"]
    assert not model.code_run_request_metrics()[-1].get("warnings")


@pytest.mark.anyio
async def test_visual_budget_gate_does_not_trigger_when_outputs_missing(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    binding = ReportingCodingTaskBinding(_visualization_task_context(workspace), workspace)
    await binding.workspace.awrite_text("task-1", "analysis/chart.py", VISUAL_SOURCE)
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.refresh_delivery_state()
    tool_limit = 10
    model = _visualization_model_with_budget(toolkit, tool_limit, tool_limit - 1)

    params = model.get_request_params(
        messages=[Message(role="user", content="go")],
        tools=toolkit.tool_functions,
    )

    assert any(tool["name"] == "edit_script" for tool in params["tools"])
    assert any(tool["name"] == "run_script" for tool in params["tools"])
    assert not model.code_run_request_metrics()[-1].get("warnings")


@pytest.mark.anyio
async def test_visual_budget_gate_does_not_trigger_for_analysis(
    binding: ReportingCodingTaskBinding,
    runtime: ToolkitRuntime,
) -> None:
    toolkit = ReportingCodeModeToolkit(binding, runtime, ReportingLspProcessManager())
    await toolkit.write_script(SOURCE)
    assert (await toolkit.run_script())["ok"] is True
    state = toolkit.delivery_state()
    state["taskKind"] = "analysis"
    state["nextTools"] = ["edit_script", "submit_script"]
    state["execution"] = {"runId": "analysis-run", "valid": True}
    tool_limit = 10
    model = ReportingCodeOpenAIResponses(
        id="gate-test", api_key="test-key", base_url="http://localhost"
    )
    model.configure_code_run(
        toolkit.tool_functions,
        max_model_requests=10,
        delivery_state_reader=lambda: state,
        tool_call_limit=tool_limit,
        visual_budget_gate_safety_margin=VISUALIZATION_BUDGET_GATE_SAFETY_MARGIN,
    )
    model._code_budget.tool_calls = tool_limit - 1
    model._code_request_metrics = [{"status": "started", "requestParams": {}}]

    params = model.get_request_params(
        messages=[Message(role="user", content="go")],
        tools=toolkit.tool_functions,
    )

    assert {tool["name"] for tool in params["tools"]} == {"edit_script", "submit_script"}
    assert not model.code_run_request_metrics()[-1].get("warnings")


@pytest.mark.anyio
async def test_visual_budget_gate_records_event_in_request_metrics(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    toolkit = await _reviewed_toolkit_with_draft(workspace, runtime)
    tool_limit = 10
    model = _visualization_model_with_budget(toolkit, tool_limit, tool_limit - 2)

    params = model.get_request_params(
        messages=[Message(role="user", content="go")],
        tools=toolkit.tool_functions,
    )

    assert [tool["name"] for tool in params["tools"]] == ["submit_script"]
    metric = model.code_run_request_metrics()[-1]
    assert metric.get("warnings") == [
        {
            "code": "report_code_visual_budget_gate_forced_submit",
            "details": {"remainingToolCalls": 2, "viewImageRounds": 0},
        }
    ]


@pytest.mark.anyio
async def test_visual_budget_gate_does_not_trigger_when_budget_above_margin(
    workspace: HostReportingWorkspace,
    runtime: ToolkitRuntime,
) -> None:
    _binding, toolkit, _output = await _prepared_visualization_toolkit(workspace, runtime)
    await toolkit.refresh_delivery_state()
    tool_limit = 10
    model = _visualization_model_with_budget(toolkit, tool_limit, tool_limit - 3)

    params = model.get_request_params(
        messages=[Message(role="user", content="go")],
        tools=toolkit.tool_functions,
    )

    assert {tool["name"] for tool in params["tools"]} == {"view_image", "submit_script"}
    assert not model.code_run_request_metrics()[-1].get("warnings")
