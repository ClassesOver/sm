from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agno.models.message import Message
from agno.tools.function import Function
from openai.types.responses import Response

from smart_reporting.reporting.code_agent.context import (
    ReportingCodingTaskContext,
    ReportingCodingTaskRegistry,
)
from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceRegistry,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope


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


def test_mixed_protocol_formats_only_large_text_tools_as_custom() -> None:
    model = _code_responses_model()
    tools = model._format_tool_params([], [_function("read_script"), _function("write_script")])
    assert tools[0]["type"] == "function"
    assert tools[1] == {
        "type": "custom",
        "name": "write_script",
        "description": "write_script",
        "format": {"type": "text"},
    }


def test_custom_call_round_trip_uses_custom_output() -> None:
    model = _code_responses_model()
    parsed = model._parse_provider_response(_custom_response("execute_code", "print('ok')"))
    assert parsed.tool_calls is not None
    call = parsed.tool_calls[0]
    assert json.loads(call["function"]["arguments"]) == {"code": "print('ok')"}
    assert call["provider_data"]["reporting_wire_type"] == "custom"
    replay = model._format_messages(_assistant_and_result_messages(call, {"ok": True}))
    assert [item["type"] for item in replay[-2:]] == [
        "custom_tool_call",
        "custom_tool_call_output",
    ]


def test_custom_output_stays_custom_with_previous_response_id() -> None:
    model = ReportingCodeOpenAIResponses(
        id="gpt-5-test",
        api_key="test-key",
        base_url="http://localhost",
        store=True,
        parallel_tool_calls=False,
    )
    parsed = model._parse_provider_response(_custom_response("execute_code", "print('ok')"))
    assert parsed.tool_calls is not None
    messages = _assistant_and_result_messages(parsed.tool_calls[0], {"ok": True})
    messages[0].provider_data = {"response_id": "resp-previous"}

    replay = model._format_messages(messages)

    assert replay == [
        {
            "type": "custom_tool_call_output",
            "call_id": "call-1",
            "output": '{"ok":true}',
        }
    ]


def test_custom_replay_rejects_result_with_wrong_call_id_and_no_tool_name() -> None:
    model = _code_responses_model()
    parsed = model._parse_provider_response(_custom_response("execute_code", "print('ok')"))
    assert parsed.tool_calls is not None
    messages = _assistant_and_result_messages(parsed.tool_calls[0], {"ok": True})
    messages[1].tool_call_id = "wrong-id"
    messages[1].tool_name = None

    with pytest.raises(ReportingError) as caught:
        model._format_messages(messages)

    assert caught.value.code == "report_code_custom_tool_protocol_error"


@pytest.mark.parametrize(
    ("name", "provider_data"),
    [
        ("read_script", {"reporting_wire_type": "custom", "raw_input": "x"}),
        ("execute_code", {"reporting_wire_type": "custom"}),
        ("execute_code", {"reporting_wire_type": "custom", "raw_input": 1}),
    ],
)
def test_custom_replay_rejects_forged_or_incomplete_metadata(
    name: str, provider_data: dict[str, Any]
) -> None:
    call = {
        "id": "item-1",
        "call_id": "call-1",
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
        "provider_data": provider_data,
    }

    with pytest.raises(ReportingError) as caught:
        _code_responses_model()._format_messages(_assistant_and_result_messages(call, {"ok": True}))

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


def test_code_requests_force_serial_auto_tool_calls() -> None:
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


def test_custom_protocol_rejects_streaming_and_unknown_names() -> None:
    assistant = Message(role="assistant", content="")
    with pytest.raises(ReportingError, match="非流式"):
        _code_responses_model().invoke_stream([], assistant, None, [_function("write_script")])
    with pytest.raises(ReportingError) as caught:
        _code_responses_model()._parse_provider_response(_custom_response("unknown", "x"))
    assert caught.value.code == "report_code_custom_tool_protocol_error"


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
