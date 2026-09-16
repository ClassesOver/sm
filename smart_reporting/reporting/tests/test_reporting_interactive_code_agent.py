from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.function import Function
from openai.types.responses import Response

from smart_reporting.reporting.agent import create_reporting_code_agent_factory
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


def test_code_agent_factory_creates_task_exclusive_mutable_objects() -> None:
    factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        name="reporting-code-agent",
    )
    first = factory([_function("read_script")])
    second = factory([_function("read_script")])
    assert first is not second
    assert first.model is not second.model
    assert first.tools[0] is not second.tools[0]


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
        _custom_response("write_script", "if True print('broken')\n"),
        _function_response(2, "run_script", {}),
        Response.model_validate(
            {
                **_custom_response("write_script", SOURCE).model_dump(),
                "id": "resp-3",
                "output": [
                    {
                        "id": "item-3",
                        "call_id": "call-3",
                        "name": "write_script",
                        "input": SOURCE,
                        "type": "custom_tool_call",
                    }
                ],
            }
        ),
        _function_response(4, "lsp_diagnostics", {}),
        _function_response(5, "search_knowledge", {"query": "脚本规范"}),
        _function_response(6, "run_script", {}),
        _function_response(7, "submit_script", {}),
    ]

    class FakeResponsesClient:
        def __init__(self) -> None:
            self.responses = self
            self.requests: list[dict[str, Any]] = []

        def is_closed(self) -> bool:
            return False

        async def create(self, **kwargs: Any) -> Response:
            self.requests.append(kwargs)
            return responses.pop(0)

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
    assert runtime.shutdowns == ["code-task-1"]
    assert len(client.requests) == 7
    assert responses == []
    replay_types = [
        item.get("type")
        for request in client.requests[1:]
        for item in request["input"]
        if isinstance(item, dict)
    ]
    assert "custom_tool_call_output" in replay_types
    assert "function_call_output" in replay_types


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
