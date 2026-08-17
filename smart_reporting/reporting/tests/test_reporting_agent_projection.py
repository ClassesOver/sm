import asyncio
import json

import pytest
from agno.agent import Agent
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import Function
from agno.tools.function import FunctionCall

from smart_reporting.reporting.agent import (
    ReportFacadeOpenAIChat,
    ReportWorkerOpenAIChat,
    _phase_filtered_report_tools,
    _with_reporting_durable_identities,
    propagate_reporting_tool_errors,
)
from smart_reporting.reporting.phase import (
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY,
    bind_reporting_run_context,
)
from smart_reporting.context_management import ProjectedOpenAIChat


@pytest.mark.parametrize(
    ("task_kind", "expected"),
    [
        (
            "analysis_item",
            ["query_analysis_facts", "query_profile", "complete_analysis_item"],
        ),
        (
            "visualization",
            ["query_analysis_facts", "register_report_charts", "finalize_report_analysis"],
        ),
    ],
)
def test_analysis_task_kind_projection_separates_item_and_visualization_tools(
    task_kind: str,
    expected: list[str],
) -> None:
    context = RunContext(
        run_id=f"run-{task_kind}",
        session_id=f"session-{task_kind}",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
            }
        },
    )
    tools = [
        {"type": "function", "function": {"name": name}}
        for name in (
            "query_analysis_facts",
            "query_profile",
            "complete_analysis_item",
            "register_report_charts",
            "finalize_report_analysis",
        )
    ]

    with bind_reporting_run_context(context):
        projected = _phase_filtered_report_tools(
            [Message(role="user", content='{"phase":"analysis"}')], tools
        )

    assert [item["function"]["name"] for item in projected] == expected


def test_analysis_projection_keeps_compact_profile_receipt_identities() -> None:
    receipt = {
        "receiptId": "profile-read-1",
        "datasetId": "dataset-1",
        "snapshotHash": "a" * 64,
        "query": "variables.area.value_counts_without_nan",
        "purpose": "读取院区分布",
    }
    messages = [
        Message(role="user", content='{"phase":"analysis"}'),
        Message(
            role="tool",
            tool_name="query_profile",
            tool_call_id="call-1",
            content=json.dumps(
                {
                    "ok": True,
                    "value": {"长文本": "不得进入身份投影"},
                    "readReceipt": receipt,
                },
                ensure_ascii=False,
            ),
        ),
        Message(
            role="tool",
            tool_name="query_profile",
            tool_call_id="call-2",
            content=json.dumps({"ok": True, "readReceipt": receipt}),
        ),
    ]

    context = RunContext(
        run_id="run-analysis",
        session_id="session-analysis",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
            }
        },
    )
    with bind_reporting_run_context(context):
        projected = _with_reporting_durable_identities(messages)
    ledger = json.loads(projected[-1].content)

    assert ledger["marker"] == "REPORTING_DURABLE_IDENTITIES"
    assert ledger["profileReadReceipts"] == [
        {
            "receiptId": "profile-read-1",
            "datasetId": "dataset-1",
            "snapshotHash": "a" * 64,
            "querySha256": "0fe0ae47cfd1405711636c91a4661f55b798956f6422b6293859ff868b23ede6",
            "query": "variables.area.value_counts_without_nan",
        }
    ]
    assert "长文本" not in projected[-1].content
    assert "purpose" not in projected[-1].content


def test_section_projection_does_not_add_analysis_receipt_ledger() -> None:
    messages = [Message(role="user", content='{"phase":"section"}')]
    context = RunContext(
        run_id="run-section",
        session_id="session-section",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "section",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "section",
            }
        },
    )

    with bind_reporting_run_context(context):
        assert _with_reporting_durable_identities(messages) is messages


def test_malformed_write_analysis_files_raises_original_json_error() -> None:
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    raw_arguments = '{"toolName":"create_files","arguments":'
    assistant = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-write-1",
                "type": "function",
                "function": {
                    "name": "write_analysis_files",
                    "arguments": raw_arguments,
                },
            }
        ],
    )
    messages = [Message(role="user", content='{"phase":"analysis"}')]
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={},
    )

    with bind_reporting_run_context(run_context), pytest.raises(json.JSONDecodeError) as raised:
        model.get_function_calls_to_run(assistant, messages, functions={})

    assert raised.value.doc == raw_arguments
    assert raised.value.msg == "Expecting value"
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == '{"phase":"analysis"}'


def test_long_malformed_write_analysis_files_is_not_replaced_by_bounded_receipt() -> None:
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    raw_arguments = '{"operation":"create_file","content":"' + ("x" * 2000)
    assistant = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-write-long-invalid",
                "type": "function",
                "function": {
                    "name": "write_analysis_files",
                    "arguments": raw_arguments,
                },
            }
        ],
    )
    messages = [Message(role="user", content='{"phase":"analysis"}')]

    with pytest.raises(json.JSONDecodeError) as raised:
        model.get_function_calls_to_run(assistant, messages, functions={})

    assert raised.value.doc == raw_arguments
    assert raised.value.msg.startswith("Unterminated string")
    assert len(messages) == 1


def test_write_analysis_files_does_not_autofix_trailing_json_brace() -> None:
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    assistant = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-write-2",
                "type": "function",
                "function": {
                    "name": "write_analysis_files",
                    "arguments": (
                        '{"operation":"create_file","path":"analysis/report.py",'
                        '"content":"pass\\n"}}'
                    ),
                },
            }
        ],
    )
    messages = [Message(role="user", content='{"phase":"analysis"}')]
    run_context = RunContext(
        run_id="run-2",
        session_id="session-2",
        session_state={},
    )

    with bind_reporting_run_context(run_context), pytest.raises(json.JSONDecodeError):
        model.get_function_calls_to_run(assistant, messages, functions={})

    assert len(messages) == 1


def test_reporting_worker_tools_share_raw_malformed_json_failure() -> None:
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    raw_arguments = '{"datasetId":"dataset-1","query":"variables.amount","purpose":"读取金额"}}'
    assistant = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-profile-invalid",
                "type": "function",
                "function": {
                    "name": "query_profile",
                    "arguments": raw_arguments,
                },
            }
        ],
    )
    messages = [Message(role="user", content='{"phase":"analysis"}')]
    run_context = RunContext(
        run_id="run-profile-invalid",
        session_id="session-profile-invalid",
        session_state={},
    )
    functions = {
        "query_profile": Function(
            name="query_profile",
            parameters={
                "type": "object",
                "properties": {
                    "datasetId": {"type": "string"},
                    "query": {"type": "string"},
                    "purpose": {"type": "string"},
                },
                "required": ["datasetId", "query", "purpose"],
                "additionalProperties": False,
            },
            entrypoint=lambda: None,
        )
    }

    with bind_reporting_run_context(run_context), pytest.raises(json.JSONDecodeError) as raised:
        model.get_function_calls_to_run(assistant, messages, functions=functions)

    assert raised.value.doc == raw_arguments
    assert raised.value.msg == "Extra data"
    assert len(messages) == 1


@pytest.mark.anyio
async def test_report_worker_model_error_is_retried_by_agno_agent(monkeypatch) -> None:
    attempts = 0
    transient = RuntimeError("transient worker failure")

    async def fake_aresponse(_self, *args, **kwargs):
        nonlocal attempts
        _ = args, kwargs
        attempts += 1
        if attempts < 3:
            raise transient
        return ModelResponse(content="completed")

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", fake_aresponse)
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    agent = Agent(model=model, retries=2, delay_between_retries=0)

    output = await agent.arun("run reporting worker")

    assert attempts == 3
    assert output.content == "completed"
    assert model.report_run_error() is None


@pytest.mark.anyio
async def test_report_worker_tool_error_is_retried_by_agno_agent(monkeypatch) -> None:
    attempts = 0
    transient = RuntimeError("transient tool failure")
    run_context = RunContext(
        run_id="run-tool-retry",
        session_id="session-tool-retry",
        session_state={},
    )

    async def flaky_tool() -> dict[str, bool]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise transient
        return {"ok": True}

    async def fake_aresponse(model, *args, **kwargs):
        _ = args, kwargs
        function = Function(name="flaky_report_tool", entrypoint=flaky_tool)
        function.tool_hooks = [propagate_reporting_tool_errors]
        function._run_context = run_context
        call = FunctionCall(function=function, arguments={}, call_id=f"call-{attempts + 1}")
        results = []
        async for _event in model.arun_function_calls([call], results):
            pass
        return ModelResponse(content="completed")

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", fake_aresponse)
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    agent = Agent(model=model, retries=2, delay_between_retries=0)

    with bind_reporting_run_context(run_context):
        output = await agent.arun("run reporting tool", run_context=run_context)

    assert attempts == 3
    assert output.content == "completed"
    assert model.report_run_error() is None


@pytest.mark.anyio
async def test_report_worker_keeps_final_original_error_after_agno_retries(monkeypatch) -> None:
    terminal = RuntimeError("terminal worker failure")

    async def fail_aresponse(_self, *args, **kwargs):
        _ = args, kwargs
        raise terminal

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", fail_aresponse)
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    agent = Agent(model=model, retries=1, delay_between_retries=0)

    output = await agent.arun("run reporting worker")

    assert str(output.status) == "RunStatus.error"
    assert model.report_run_error() is terminal


def test_report_section_requests_disable_thinking_without_mutating_worker() -> None:
    model = ReportWorkerOpenAIChat(
        id="deepseek-v4-flash-0731",
        api_key="test",
        reasoning_effort="high",
        extra_body={"enable_thinking": True, "thinking_budget": 8192},
    )

    analysis_context = RunContext(
        run_id="run-analysis",
        session_id="session-analysis",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
                REPORTING_THINKING_EFFORT_DEPENDENCY_KEY: "high",
            }
        },
    )
    section_context = RunContext(
        run_id="run-section",
        session_id="session-section",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "section",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "section",
                REPORTING_THINKING_EFFORT_DEPENDENCY_KEY: "off",
            }
        },
    )
    with bind_reporting_run_context(analysis_context):
        analysis_model = model._phase_request_model([])
    with bind_reporting_run_context(section_context):
        section_model = model._phase_request_model([])

    assert analysis_model is not model
    assert analysis_model.extra_body == {
        "enable_thinking": True,
        "thinking_budget": 8192,
    }
    assert analysis_model.reasoning_effort == "high"
    assert section_model is not model
    assert section_model.extra_body == {"enable_thinking": False}
    assert section_model.reasoning_effort is None
    assert model.extra_body == {"enable_thinking": True, "thinking_budget": 8192}
    assert model.reasoning_effort == "high"


@pytest.mark.anyio
async def test_concurrent_reporting_requests_keep_off_high_max_profiles_isolated() -> None:
    model = ReportWorkerOpenAIChat(
        id="deepseek-v4-flash-0731",
        api_key="test",
        reasoning_effort="high",
        extra_body={"enable_thinking": True, "thinking_budget": 8192},
    )

    async def request(phase: str, task_kind: str, effort: str):
        context = RunContext(
            run_id=f"run-{effort}",
            session_id=f"session-{effort}",
            session_state={},
            dependencies={
                REPORTING_TASK_DEPENDENCY: {
                    REPORTING_PHASE_DEPENDENCY_KEY: phase,
                    REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
                    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY: effort,
                }
            },
        )
        with bind_reporting_run_context(context):
            await asyncio.sleep(0)
            return model._phase_request_model(
                [Message(role="user", content=json.dumps({"phase": phase}))]
            )

    off_model, high_model, max_model = await asyncio.gather(
        request("section", "section", "off"),
        request("analysis", "analysis_item", "high"),
        request("analysis", "visualization", "max"),
    )

    assert len({id(off_model), id(high_model), id(max_model), id(model)}) == 4
    assert off_model.extra_body == {"enable_thinking": False}
    assert off_model.reasoning_effort is None
    assert high_model.extra_body == {"enable_thinking": True, "thinking_budget": 8192}
    assert high_model.reasoning_effort == "high"
    assert max_model.extra_body == {"enable_thinking": True, "thinking_budget": 8192}
    assert max_model.reasoning_effort == "max"
    assert model.extra_body == {"enable_thinking": True, "thinking_budget": 8192}
    assert model.reasoning_effort == "high"


def test_reporting_facade_tools_use_same_strict_json_boundary() -> None:
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    assistant = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-workflow-invalid",
                "type": "function",
                "function": {
                    "name": "report_workflow_start",
                    "arguments": "{}}",
                },
            }
        ],
    )
    messages = [Message(role="user", content="生成运营报告")]
    functions = {
        "report_workflow_start": Function(
            name="report_workflow_start",
            parameters={"type": "object", "properties": {}, "required": []},
            entrypoint=lambda: None,
        )
    }

    calls = model.get_function_calls_to_run(assistant, messages, functions=functions)

    assert calls == []
    receipt = json.loads(messages[-1].content)
    assert receipt["code"] == "report_tool_arguments_json_invalid"
    assert receipt["schemaHint"] == {
        "argumentsType": "object",
        "allowedFields": [],
        "requiredFields": [],
    }
    assert receipt["details"]["jsonErrorMessage"] == "Extra data"


def test_reporting_model_replays_reasoning_only_for_tool_call_turns() -> None:
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    tool_turn = Message(
        role="assistant",
        content="",
        reasoning_content="内部工具规划",
        tool_calls=[
            {
                "id": "call-profile-1",
                "type": "function",
                "function": {"name": "query_profile", "arguments": "{}"},
            }
        ],
    )
    plain_turn = Message(
        role="assistant",
        content="结论",
        reasoning_content="不应回传的普通轮次推理",
    )

    assert model._format_message(tool_turn)["reasoning_content"] == "内部工具规划"
    assert "reasoning_content" not in model._format_message(plain_turn)
