import asyncio
import hashlib
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent
from agno.exceptions import StopAgentRun
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import Function
from agno.tools.function import FunctionCall
from openai.types.chat.chat_completion_chunk import (
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)

from smart_reporting.context_management import ProjectedOpenAIChat
from smart_reporting.reporting import agent as report_agent_module
from smart_reporting.reporting.agent import (
    ReportFacadeOpenAIChat,
    ReportWorkerOpenAIChat,
    _phase_filtered_report_messages,
    _phase_filtered_report_tools,
    _report_worker_tools_cache_key,
    _with_reporting_durable_identities,
    create_report_worker,
    normalize_reporting_tool_arguments,
    propagate_reporting_tool_errors,
)
from smart_reporting.reporting.instructions import build_report_agent_instructions
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.phase import (
    REPORTING_ANALYSIS_FACT_QUERIES_USED_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY,
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_REGISTERED_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY,
    REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY,
    bind_reporting_run_context,
    reporting_phase_allows_tool,
    reporting_visualization_usage_from_run_context,
)
from smart_reporting.reporting.vision import ReportVisionReviewer
from smart_reporting.reporting.workflow.checkpoint import SectionArtifact
from smart_reporting.settings import AgentSettings
from smart_reporting.workspace import WorkspaceError


def test_report_worker_disables_unused_session_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = AgentSettings.from_environment(
        {
            "OPENAI_API_KEY": "test",
            "AGENT_ENABLE_SESSION_SUMMARIES": "true",
        },
        load_env_file=False,
    )
    monkeypatch.setattr(report_agent_module, "load_sandbox_execution_skills", lambda _: None)
    monkeypatch.setattr(report_agent_module, "load_reporting_skills", lambda _: None)

    worker = create_report_worker(
        settings,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        state_repository=SimpleNamespace(),
    )

    assert worker.add_history_to_context is False
    assert worker.telemetry is False
    assert worker.enable_session_summaries is False
    assert worker.add_session_summary_to_context is False
    assert worker.session_summary_manager is None


def test_report_worker_vllm_transport_preserves_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AgentSettings.from_environment(
        {
            "OPENAI_API_KEY": "test",
            "OPENAI_BASE_URL": "http://self-hosted.example/v1",
            "AGENT_MODEL_VLLM_REASONING": "true",
        },
        load_env_file=False,
    )
    monkeypatch.setattr(report_agent_module, "load_sandbox_execution_skills", lambda _: None)
    monkeypatch.setattr(report_agent_module, "load_reporting_skills", lambda _: None)

    worker = create_report_worker(
        settings,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        state_repository=SimpleNamespace(),
    )

    request_params = worker.model.get_request_params()

    assert "reasoning_effort" not in request_params
    assert request_params["extra_body"] == {
        "enable_thinking": True,
        "thinking_budget": 8192,
        "chat_template_kwargs": {
            "thinking": True,
            "reasoning_effort": "high",
        },
    }


def test_report_vision_reviewer_disables_telemetry() -> None:
    settings = AgentSettings.from_environment(
        {"OPENAI_API_KEY": "test"},
        load_env_file=False,
    )

    reviewer = ReportVisionReviewer(settings, cast(Any, SimpleNamespace()))

    assert reviewer._new_agent().telemetry is False


@pytest.mark.anyio
async def test_report_vision_reviewer_sends_native_image_and_binds_receipt_hash() -> None:
    content = b"\x89PNG\r\n\x1a\nchart-bytes"
    workspace = SimpleNamespace(
        view_image=lambda _thread_id, _path: SimpleNamespace(
            images=[SimpleNamespace(content=content, mime_type="image/png", format="png")]
        )
    )
    agent = SimpleNamespace(arun=AsyncMock())
    agent.arun.return_value = SimpleNamespace(
        content={
            "summary": "图表存在裁切和文字重叠。",
            "requiresRevision": True,
            "issues": [
                {"category": "cropping", "severity": "critical", "description": "标题被裁切"},
                {
                    "category": "text_overlap",
                    "severity": "critical",
                    "description": "坐标轴文字重叠",
                },
            ],
            "warnings": [],
            "suggestions": ["增加边距"],
        }
    )
    settings = AgentSettings.from_environment({"OPENAI_API_KEY": "test"}, load_env_file=False)
    reviewer = ReportVisionReviewer(settings, cast(Any, workspace), agent_factory=lambda: agent)

    receipt = await reviewer.review("thread-1", "analysis/charts/income.png")

    assert receipt["sourcePath"] == "analysis/charts/income.png"
    assert receipt["sha256"] == hashlib.sha256(content).hexdigest()
    assert receipt["modelId"] == settings.report_vision_model
    assert receipt["reviewed"] is True
    assert receipt["requiresRevision"] is True
    assert {item["category"] for item in receipt["issues"]} == {"cropping", "text_overlap"}
    assert len(agent.arun.await_args.kwargs["images"]) == 1
    assert agent.arun.await_args.kwargs["images"][0].content == content


@pytest.mark.anyio
async def test_report_vision_reviewer_fails_closed_when_model_is_unavailable() -> None:
    content = b"\x89PNG\r\n\x1a\nchart-bytes"
    workspace = SimpleNamespace(
        view_image=lambda _thread_id, _path: SimpleNamespace(
            images=[SimpleNamespace(content=content, mime_type="image/png", format="png")]
        )
    )
    agent = SimpleNamespace(arun=AsyncMock(side_effect=RuntimeError("provider secret")))
    settings = AgentSettings.from_environment({"OPENAI_API_KEY": "test"}, load_env_file=False)
    reviewer = ReportVisionReviewer(settings, cast(Any, workspace), agent_factory=lambda: agent)

    with pytest.raises(WorkspaceError, match="视觉审查暂不可用"):
        await reviewer.review("thread-1", "analysis/charts/income.png")


@pytest.mark.parametrize(
    ("configured_timeout", "expected_timeout"),
    [("900", 900), ("120", 120)],
)
def test_report_worker_caps_only_long_model_timeout(
    monkeypatch: pytest.MonkeyPatch,
    configured_timeout: str,
    expected_timeout: int,
) -> None:
    monkeypatch.setattr(report_agent_module, "load_sandbox_execution_skills", lambda _: None)
    monkeypatch.setattr(report_agent_module, "load_reporting_skills", lambda _: None)

    settings = AgentSettings.from_environment(
        {
            "OPENAI_API_KEY": "test",
            "AGENT_MODEL_TIMEOUT_SECONDS": configured_timeout,
        },
        load_env_file=False,
    )
    worker = create_report_worker(
        settings,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        state_repository=SimpleNamespace(),
    )

    assert worker.model.timeout == expected_timeout


@pytest.mark.parametrize(
    ("task_kind", "expected"),
    [
        (
            "analysis_item",
            [
                "query_analysis_context",
                "query_analysis_facts",
                "query_profile",
                "complete_analysis_item",
            ],
        ),
        (
            "visualization",
            [
                "get_skill_instructions",
                "get_skill_reference",
                "query_analysis_context",
                "query_analysis_facts",
                "inspect_chart",
                "register_report_charts",
                "finalize_report_analysis",
            ],
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
            "finish_task",
            "get_skill_instructions",
            "get_skill_reference",
            "get_skill_script",
            "query_analysis_context",
            "query_analysis_facts",
            "query_profile",
            "complete_analysis_item",
            "inspect_chart",
            "register_report_charts",
            "finalize_report_analysis",
        )
    ]

    with bind_reporting_run_context(context):
        projected = _phase_filtered_report_tools(
            [Message(role="user", content='{"phase":"analysis"}')], tools
        )

    assert [item["function"]["name"] for item in projected] == expected


def test_visualization_recovery_projection_removes_exploration_tools() -> None:
    context = RunContext(
        run_id="run-visualization-recovery",
        session_id="session-visualization-recovery",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
                REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY: True,
            }
        },
    )
    tools = [
        {"type": "function", "function": {"name": name}}
        for name in (
            "query_analysis_facts",
            "read_file",
            "read_tool_output",
            "get_skill_reference",
            "write_analysis_files",
            "terminal",
            "register_report_charts",
            "finalize_report_analysis",
        )
    ]

    with bind_reporting_run_context(context):
        projected = _phase_filtered_report_tools(
            [Message(role="user", content='{"phase":"analysis"}')], tools
        )

    assert [item["function"]["name"] for item in projected] == [
        "write_analysis_files",
        "terminal",
        "register_report_charts",
        "finalize_report_analysis",
    ]


def test_visualization_exploration_tools_are_hidden_after_their_subbudget() -> None:
    context = RunContext(
        run_id="run-visualization-exploration-limit",
        session_id="session-visualization-exploration-limit",
        session_state={
            REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY: {
                "visualization-exploration:run-visualization-exploration-limit": {
                    "toolCounts": {"query_analysis_facts": 4, "read_file": 12}
                }
            }
        },
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-exploration",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
            }
        },
    )

    with bind_reporting_run_context(context):
        assert reporting_phase_allows_tool(
            "analysis", "query_analysis_facts", task_kind="visualization"
        )
        assert reporting_phase_allows_tool("analysis", "read_file", task_kind="visualization")
        assert reporting_phase_allows_tool("analysis", "terminal", task_kind="visualization")
        projected = _phase_filtered_report_tools(
            [],
            [
                {"type": "function", "function": {"name": "query_analysis_facts"}},
                {"type": "function", "function": {"name": "read_file"}},
                {"type": "function", "function": {"name": "terminal"}},
            ],
        )

    assert [item["function"]["name"] for item in projected] == ["terminal"]


def test_analysis_item_hides_facts_tool_after_its_subbudget() -> None:
    context = RunContext(
        run_id="run-analysis-facts-limit",
        session_id="session-analysis-facts-limit",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "analysis-facts-limit",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
                REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY: 2,
                REPORTING_ANALYSIS_FACT_QUERIES_USED_DEPENDENCY_KEY: 2,
            }
        },
    )

    with bind_reporting_run_context(context):
        projected = _phase_filtered_report_tools(
            [],
            [
                {"type": "function", "function": {"name": "query_analysis_facts"}},
                {"type": "function", "function": {"name": "complete_analysis_item"}},
            ],
        )

    assert [item["function"]["name"] for item in projected] == ["complete_analysis_item"]


def test_analysis_recovery_projection_keeps_only_completion() -> None:
    context = RunContext(
        run_id="run-analysis-recovery",
        session_id="session-analysis-recovery",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
                REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY: True,
            }
        },
    )
    tools = [
        {"type": "function", "function": {"name": name}}
        for name in (
            "query_analysis_facts",
            "query_profile",
            "write_analysis_files",
            "complete_analysis_item",
        )
    ]

    with bind_reporting_run_context(context):
        projected = _phase_filtered_report_tools([], tools)

    assert [item["function"]["name"] for item in projected] == ["complete_analysis_item"]


@pytest.mark.parametrize(
    ("phase", "task_kind", "keeps_skills"),
    [
        ("analysis", "analysis_item", False),
        ("analysis", "visualization", True),
        ("section", "section", False),
    ],
)
def test_report_worker_keeps_skill_prompt_only_for_visualization(
    phase: str,
    task_kind: str,
    keeps_skills: bool,
) -> None:
    context = RunContext(
        run_id=f"run-{task_kind}",
        session_id=f"session-{task_kind}",
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: phase,
                REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
            }
        },
    )
    messages = [
        Message(
            role="system",
            content=("固定系统指令\n<skills_system>按需读取 Skill</skills_system>\nReporting 指令"),
        ),
        Message(role="user", content=json.dumps({"phase": phase})),
    ]

    with bind_reporting_run_context(context):
        projected = _phase_filtered_report_messages(messages)

    content = projected[0].content
    assert isinstance(content, str)
    assert ("<skills_system>" in content) is keeps_skills
    assert "固定系统指令" in content
    assert "Reporting 指令" in content


def test_section_projection_hides_internal_finish_task() -> None:
    context = RunContext(
        run_id="run-section",
        session_id="session-section",
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "section",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "section",
            }
        },
    )
    tools = [
        {"type": "function", "function": {"name": name}}
        for name in ("finish_task", "read_file", "render_report_section")
    ]

    with bind_reporting_run_context(context):
        projected = _phase_filtered_report_tools(
            [Message(role="user", content='{"phase":"section"}')], tools
        )

    assert [item["function"]["name"] for item in projected] == [
        "read_file",
        "render_report_section",
    ]


def test_report_worker_tool_cache_key_separates_task_kinds_for_same_user() -> None:
    def context(task_kind: str) -> RunContext:
        return RunContext(
            run_id=f"run-{task_kind}",
            session_id=f"session-{task_kind}",
            user_id="user-1",
            dependencies={
                REPORTING_TASK_DEPENDENCY: {
                    REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                    REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
                }
            },
        )

    assert _report_worker_tools_cache_key(
        context("analysis_item")
    ) != _report_worker_tools_cache_key(context("visualization"))


def test_report_worker_tool_cache_key_separates_concurrent_analysis_tasks() -> None:
    def context(task_id: str) -> RunContext:
        return RunContext(
            run_id=f"internal-{task_id}",
            session_id=f"session-{task_id}",
            user_id="user-1",
            dependencies={
                REPORTING_TASK_DEPENDENCY: {
                    "externalRunId": task_id,
                    REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                    REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
                }
            },
        )

    assert _report_worker_tools_cache_key(context("analysis-1")) != (
        _report_worker_tools_cache_key(context("analysis-2"))
    )


@pytest.mark.parametrize("task_kind", ["analysis_item", "visualization"])
def test_report_worker_instructions_exclude_generic_coding_tools(task_kind: str) -> None:
    context = RunContext(
        run_id=f"run-{task_kind}",
        session_id=f"session-{task_kind}",
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
            }
        },
    )

    instructions = "\n".join(build_report_agent_instructions(context))

    assert "当前实际提供的工具 schema" in instructions
    assert "update_plan" not in instructions
    assert "replace_text" not in instructions
    assert "git_status" not in instructions
    if task_kind == "visualization":
        assert "只调用 write_analysis_files" in instructions
        assert "analyses[].evidenceFiles[].path" in instructions
        assert "不得构造 analysis/evidence" in instructions
        assert '禁止假设 facts["analyses"]' in instructions
        assert "visualizationWorkspace" in instructions
        assert "analysisCitationIds" in instructions
        assert "不得用 read_file、terminal 或目录探测寻找 citationId" in instructions
        assert "仅可执行 python3 <scriptPath>" in instructions
        assert "聚合回执使用完整窗口" in instructions
        assert "outputTruncated=false 时禁止再次读取" in instructions


def test_deterministic_visualization_instructions_forbid_inspect_chart() -> None:
    context = RunContext(
        run_id="run-visualization-deterministic",
        session_id="session-visualization-deterministic",
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
                "reportingVisualInspectionMode": "deterministic",
            }
        },
    )

    instructions = "\n".join(build_report_agent_instructions(context))

    assert "禁止调用 inspect_chart" in instructions
    assert "每张最终图表必须先调用 inspect_chart" not in instructions


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
async def test_render_report_section_real_json_arrays_reach_tuple_contract() -> None:
    received: tuple[Any, Any] | None = None

    async def render_report_section(
        blocks: list[dict[str, Any]],
        claims: list[dict[str, Any]],
    ) -> dict[str, bool]:
        nonlocal received
        artifact = SectionArtifact.model_validate(
            {"sectionCode": "section_003", "blocks": blocks, "claims": claims}
        )
        received = (artifact.blocks, artifact.claims)
        return {"ok": True}

    function = Function(name="render_report_section", entrypoint=render_report_section)
    function.tool_hooks = [
        propagate_reporting_tool_errors,
        normalize_reporting_tool_arguments,
    ]
    run_context = RunContext(run_id="run-section-json", session_id="session-section-json")
    function._run_context = run_context
    raw_arguments = json.dumps(
        {
            "blocks": [
                {
                    "blockId": "block-1",
                    "markdown": "收入增长 8.2%。",
                    "citationIds": ["citation-1"],
                    "claimIds": ["claim-1"],
                }
            ],
            "claims": [
                {
                    "claimId": "claim-1",
                    "metricCode": "income",
                    "value": "8.2%",
                    "periodBasis": "2025年",
                    "managementQuestion": "收入增长如何？",
                    "currentPeriod": "2025年",
                    "citationIds": ["citation-1"],
                }
            ],
        }
    )
    assistant = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-section-json",
                "type": "function",
                "function": {"name": function.name, "arguments": raw_arguments},
            }
        ],
    )
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")

    with bind_reporting_run_context(run_context):
        calls = model.get_function_calls_to_run(
            assistant,
            [Message(role="user", content='{"phase":"section"}')],
            functions={function.name: function},
        )
        results: list[Message] = []
        async for _event in model.arun_function_calls(calls, results):
            pass

    assert received is not None
    assert isinstance(received[0], tuple)
    assert isinstance(received[1], tuple)
    assert results[-1].content == "{'ok': True}"


@pytest.mark.anyio
async def test_render_report_section_stringified_blocks_are_rejected() -> None:
    executed = False

    async def render_report_section(
        blocks: list[dict[str, Any]],
        claims: list[dict[str, Any]],
    ) -> dict[str, bool]:
        nonlocal executed
        SectionArtifact.model_validate(
            {"sectionCode": "section_003", "blocks": blocks, "claims": claims}
        )
        executed = True
        return {"ok": True}

    function = Function(name="render_report_section", entrypoint=render_report_section)
    function.tool_hooks = [
        propagate_reporting_tool_errors,
        normalize_reporting_tool_arguments,
    ]
    run_context = RunContext(run_id="run-section-string", session_id="session-section-string")
    function._run_context = run_context
    assistant = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-section-string",
                "type": "function",
                "function": {
                    "name": function.name,
                    "arguments": json.dumps(
                        {
                            "blocks": '[{"blockId":"block-1"}]',
                            "claims": [{"claimId": "claim-1", "value": "8.2%"}],
                        }
                    ),
                },
            }
        ],
    )
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")

    with bind_reporting_run_context(run_context):
        calls = model.get_function_calls_to_run(
            assistant,
            [Message(role="user", content='{"phase":"section"}')],
            functions={function.name: function},
        )
        results: list[Message] = []
        async for _event in model.arun_function_calls(calls, results):
            pass

    assert executed is False
    assert "'code': 'report_tool_arguments_invalid'" in results[-1].content


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
async def test_report_worker_no_progress_stops_before_remaining_batch_calls() -> None:
    run_context = RunContext(
        run_id="run-tool-no-progress",
        session_id="session-tool-no-progress",
        session_state={},
    )
    remaining_calls = 0

    async def render_report_section(blocks: list[dict[str, Any]]) -> dict[str, bool]:
        _ = blocks
        return {"ok": True}

    async def remaining_tool() -> dict[str, bool]:
        nonlocal remaining_calls
        remaining_calls += 1
        return {"ok": True}

    invalid = Function(name="render_report_section", entrypoint=render_report_section)
    invalid.tool_hooks = [
        propagate_reporting_tool_errors,
        normalize_reporting_tool_arguments,
    ]
    invalid._run_context = run_context
    invalid_arguments: dict[str, Any] = {}
    for _ in range(2):
        failure = await normalize_reporting_tool_arguments(
            run_context,
            invalid.name,
            invalid.entrypoint,
            invalid_arguments,
        )
        assert failure["code"] == "report_tool_arguments_invalid"

    remaining = Function(name="remaining_tool", entrypoint=remaining_tool)
    remaining._run_context = run_context
    function_calls = [
        FunctionCall(
            function=invalid,
            arguments=invalid_arguments,
            call_id="call-invalid-third",
        ),
        FunctionCall(function=remaining, arguments={}, call_id="call-remaining"),
    ]
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")

    with bind_reporting_run_context(run_context):
        async for _event in model.arun_function_calls(function_calls, []):
            pass
        terminal = report_agent_module._take_reporting_tool_run_error()

    assert isinstance(terminal, ReportingError)
    assert terminal.code == "report_tool_arguments_invalid"
    assert terminal.details["terminalReason"] == "tool_no_progress"
    assert remaining_calls == 0


@pytest.mark.anyio
async def test_report_worker_no_progress_does_not_retry_agent_model(monkeypatch) -> None:
    model_requests = 0
    run_context = RunContext(
        run_id="run-tool-no-progress-agent",
        session_id="session-tool-no-progress-agent",
        session_state={},
    )

    async def render_report_section(blocks: list[dict[str, Any]]) -> dict[str, bool]:
        _ = blocks
        return {"ok": True}

    invalid_arguments: dict[str, Any] = {}
    for _ in range(2):
        failure = await normalize_reporting_tool_arguments(
            run_context,
            "render_report_section",
            render_report_section,
            invalid_arguments,
        )
        assert failure["code"] == "report_tool_arguments_invalid"

    async def fake_aresponse(model, *args, **kwargs):
        nonlocal model_requests
        _ = args, kwargs
        model_requests += 1
        function = Function(name="render_report_section", entrypoint=render_report_section)
        function.tool_hooks = [
            propagate_reporting_tool_errors,
            normalize_reporting_tool_arguments,
        ]
        function._run_context = run_context
        call = FunctionCall(function=function, arguments={}, call_id="call-terminal")
        async for _event in model.arun_function_calls([call], []):
            pass
        return ModelResponse(content="stopped")

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", fake_aresponse)
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    agent = Agent(model=model, retries=2, delay_between_retries=0)

    with bind_reporting_run_context(run_context):
        output = await agent.arun("run reporting tool", run_context=run_context)

    assert model_requests == 1
    assert output.content == "stopped"
    error = model.report_run_error()
    assert isinstance(error, ReportingError)
    assert error.code == "report_tool_arguments_invalid"
    assert error.details["terminalReason"] == "tool_no_progress"


@pytest.mark.anyio
async def test_report_worker_stream_no_progress_records_original_error(monkeypatch) -> None:
    model_requests = 0
    run_context = RunContext(
        run_id="run-tool-no-progress-stream",
        session_id="session-tool-no-progress-stream",
        session_state={},
    )

    async def render_report_section(blocks: list[dict[str, Any]]) -> dict[str, bool]:
        _ = blocks
        return {"ok": True}

    invalid_arguments: dict[str, Any] = {}
    for _ in range(2):
        failure = await normalize_reporting_tool_arguments(
            run_context,
            "render_report_section",
            render_report_section,
            invalid_arguments,
        )
        assert failure["code"] == "report_tool_arguments_invalid"

    async def fake_aresponse_stream(model, *args, **kwargs):
        nonlocal model_requests
        _ = args, kwargs
        model_requests += 1
        function = Function(name="render_report_section", entrypoint=render_report_section)
        function.tool_hooks = [
            propagate_reporting_tool_errors,
            normalize_reporting_tool_arguments,
        ]
        function._run_context = run_context
        call = FunctionCall(function=function, arguments={}, call_id="call-terminal-stream")
        async for event in model.arun_function_calls([call], []):
            yield event
        yield ModelResponse(content="stopped")

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse_stream", fake_aresponse_stream)
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")

    with bind_reporting_run_context(run_context):
        responses = [
            response
            async for response in model.aresponse_stream(
                [Message(role="user", content='{"phase":"section"}')]
            )
        ]

    assert model_requests == 1
    assert responses[-1].content == "stopped"
    error = model.report_run_error()
    assert isinstance(error, ReportingError)
    assert error.code == "report_tool_arguments_invalid"
    assert error.details["terminalReason"] == "tool_no_progress"


@pytest.mark.anyio
async def test_report_worker_agent_stops_before_analysis_tool_budget_overflow(monkeypatch) -> None:
    calls = 0
    run_context = RunContext(
        run_id="run-analysis-budget",
        session_id="session-analysis-budget",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "analysis-task-001",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
            }
        },
    )

    async def successful_query() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    async def fake_aresponse(model, *args, **kwargs):
        _ = args, kwargs
        for index in range(3):
            function = Function(name="query_profile", entrypoint=successful_query)
            function.tool_hooks = [
                propagate_reporting_tool_errors,
                normalize_reporting_tool_arguments,
            ]
            function._run_context = run_context
            call = FunctionCall(function=function, arguments={}, call_id=f"call-query-{index}")
            results = []
            async for _event in model.arun_function_calls([call], results):
                pass
        return ModelResponse(content="budget was not enforced")

    monkeypatch.setattr(report_agent_module, "_REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_LIMIT", 2)
    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", fake_aresponse)
    model = ReportWorkerOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    agent = Agent(model=model, retries=0)

    with bind_reporting_run_context(run_context):
        output = await agent.arun(
            "run reporting analysis item",
            run_context=run_context,
        )

    assert calls == 2
    assert str(output.status) == "RunStatus.error"
    error = model.report_run_error()
    assert isinstance(error, ReportingError)
    assert error.code == "report_analysis_tool_budget_exhausted"


@pytest.mark.anyio
async def test_report_facade_returns_exact_workflow_start_error_without_model(monkeypatch) -> None:
    async def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("工作流错误不得交给模型重新解释")

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", unexpected_model_call)
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    messages = [
        Message(role="user", content="生成瑞金医院运营报告"),
        Message(
            role="tool",
            tool_name="report_workflow_start",
            tool_call_id="call-report-start",
            tool_call_error=True,
            content="report_analysis_tool_budget_exhausted: 当前分析项已达到成功工具调用上限。",
        ),
    ]

    response = await model.ainvoke(messages)

    assert response.content == (
        "报表工作流执行失败：report_analysis_tool_budget_exhausted: "
        "当前分析项已达到成功工具调用上限。"
    )
    assert not response.tool_calls

    streamed = [item async for item in model.ainvoke_stream(messages)]
    assert [item.content for item in streamed] == [response.content]
    assert not streamed[0].tool_calls


@pytest.mark.anyio
async def test_report_facade_returns_completed_downloads_as_markdown_without_model(
    monkeypatch,
) -> None:
    async def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("完成回执不得交给模型重新改写")

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", unexpected_model_call)
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    payload = {
        "ok": True,
        "status": "completed",
        "report": {
            "reportId": "report-1",
            "revision": 1,
            "pdf": {"downloadUrl": "http://reports.example.com/reports/v1/download/raw"},
            "word": {"downloadUrl": "http://reports.example.com/reports/v1/download/raw/word"},
            "html": {"previewUrl": "http://reports.example.com/reports/v1/download/raw/html"},
        },
    }
    messages = [
        Message(role="user", content="生成运营报告"),
        Message(
            role="tool",
            tool_name="report_workflow_start",
            tool_call_id="call-report-start",
            content=json.dumps(payload, ensure_ascii=False),
        ),
    ]

    response = await model.ainvoke(messages)

    assert response.content == (
        "## 报表已生成\n\n"
        "- 报告编号：`report-1`\n"
        "- 修订版本：Revision 1\n\n"
        "### 文件下载\n\n"
        "- [下载 PDF 报告](http://reports.example.com/reports/v1/download/raw)\n"
        "- [下载 Word 报告](http://reports.example.com/reports/v1/download/raw/word)\n"
        "- [预览 HTML 报告](http://reports.example.com/reports/v1/download/raw/html)"
    )
    assert not response.tool_calls


@pytest.mark.anyio
async def test_report_facade_rejects_invalid_html_delivery_url_without_model(
    monkeypatch,
) -> None:
    async def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("无效 HTML 回执不得交给模型包装成链接")

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", unexpected_model_call)
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    payload = {
        "ok": True,
        "status": "completed",
        "report": {
            "reportId": "report-1",
            "revision": 1,
            "pdf": {"downloadUrl": "http://reports.example.com/reports/v1/download/raw"},
            "word": {"downloadUrl": "http://reports.example.com/reports/v1/download/raw/word"},
            "html": {"previewUrl": "http://bad host/reports/v1/download/raw/html"},
        },
    }
    messages = [
        Message(role="user", content="生成运营报告"),
        Message(
            role="tool",
            tool_name="report_workflow_start",
            tool_call_id="call-report-start",
            content=json.dumps(payload, ensure_ascii=False),
        ),
    ]

    response = await model.ainvoke(messages)

    assert response.content == (
        "## 报告发布未完成\n\n未生成有效的 PDF、Word 和 HTML 交付链接，请重试报表发布。"
    )
    assert not response.tool_calls


@pytest.mark.anyio
@pytest.mark.parametrize(
    "html_url",
    [
        "http://reports.example.com/path with space",
        "http://user name@reports.example.com/reports/v1/download/raw/html",
        "http://reports.example.com/reports/v1/download/raw/html\x7f",
    ],
)
async def test_report_facade_rejects_malformed_html_delivery_urls_without_model(
    monkeypatch, html_url: str
) -> None:
    async def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("格式错误的 HTML 回执不得交给模型包装成链接")

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", unexpected_model_call)
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    payload = {
        "ok": True,
        "status": "completed",
        "report": {
            "reportId": "report-1",
            "revision": 1,
            "pdf": {"downloadUrl": "http://reports.example.com/reports/v1/download/raw"},
            "word": {"downloadUrl": "http://reports.example.com/reports/v1/download/raw/word"},
            "html": {"previewUrl": html_url},
        },
    }
    messages = [
        Message(role="user", content="生成运营报告"),
        Message(
            role="tool",
            tool_name="report_workflow_start",
            tool_call_id="call-report-start",
            content=json.dumps(payload, ensure_ascii=False),
        ),
    ]

    response = await model.ainvoke(messages)

    assert response.content == (
        "## 报告发布未完成\n\n未生成有效的 PDF、Word 和 HTML 交付链接，请重试报表发布。"
    )
    assert not response.tool_calls

    streamed = [item async for item in model.ainvoke_stream(messages)]
    assert [item.content for item in streamed] == [response.content]
    assert not streamed[0].tool_calls


@pytest.mark.anyio
async def test_report_facade_rejects_relative_workspace_downloads_without_model(
    monkeypatch,
) -> None:
    async def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("无效下载回执不得交给模型包装成相对链接")

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", unexpected_model_call)
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    payload = {
        "ok": True,
        "status": "completed",
        "report": {
            "reportId": "report-1",
            "revision": 1,
            "path": "报表/智能分析/report-1/revision-1/report.pdf",
            "word": {"path": "报表/智能分析/report-1/revision-1/report.docx"},
        },
    }
    messages = [
        Message(role="user", content="生成运营报告"),
        Message(
            role="tool",
            tool_name="report_workflow_start",
            tool_call_id="call-report-start",
            content=json.dumps(payload, ensure_ascii=False),
        ),
    ]

    response = await model.ainvoke(messages)

    assert response.content == (
        "## 报告发布未完成\n\n未生成有效的 PDF、Word 和 HTML 交付链接，请重试报表发布。"
    )
    assert "报表/智能分析" not in str(response.content)
    assert not response.tool_calls


@pytest.mark.anyio
async def test_report_facade_removes_tool_call_preamble(monkeypatch) -> None:
    async def model_call(*_args, **_kwargs):
        return ModelResponse(
            content="I'll start the report workflow.",
            tool_calls=[
                {
                    "id": "call-report-start",
                    "type": "function",
                    "function": {"name": "report_workflow_start", "arguments": "{}"},
                }
            ],
        )

    monkeypatch.setattr(report_agent_module.ReportingOpenAIChat, "ainvoke", model_call)
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")

    response = await model.ainvoke([Message(role="user", content="生成运营报告")])

    assert response.content is None
    assert response.tool_calls


@pytest.mark.anyio
async def test_report_facade_removes_streamed_tool_call_preamble(monkeypatch) -> None:
    async def model_stream(*_args, **_kwargs):
        yield ModelResponse(content="I'll start the report workflow.")
        yield ModelResponse(
            tool_calls=[
                ChoiceDeltaToolCall(
                    index=0,
                    id="call-report-start",
                    type="function",
                    function=ChoiceDeltaToolCallFunction(
                        name="report_workflow_start",
                        arguments="{}",
                    ),
                )
            ]
        )

    monkeypatch.setattr(report_agent_module.ReportingOpenAIChat, "ainvoke_stream", model_stream)
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")

    responses = [
        response
        async for response in model.ainvoke_stream([Message(role="user", content="生成运营报告")])
    ]

    assert [response.content for response in responses] == [None, None]
    assert responses[1].tool_calls


def test_report_facade_removes_sync_streamed_tool_call_preamble(monkeypatch) -> None:
    def model_stream(*_args, **_kwargs):
        yield ModelResponse(content="I'll start the report workflow.")
        yield ModelResponse(
            tool_calls=[
                ChoiceDeltaToolCall(
                    index=0,
                    id="call-report-start",
                    type="function",
                    function=ChoiceDeltaToolCallFunction(
                        name="report_workflow_start",
                        arguments="{}",
                    ),
                )
            ]
        )

    monkeypatch.setattr(report_agent_module.ReportingOpenAIChat, "invoke_stream", model_stream)
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")

    responses = list(model.invoke_stream([Message(role="user", content="生成运营报告")]))

    assert [response.content for response in responses] == [None, None]
    assert responses[1].tool_calls


@pytest.mark.anyio
async def test_report_facade_preserves_plain_async_stream_content(monkeypatch) -> None:
    async def model_stream(*_args, **_kwargs):
        yield ModelResponse(content="首个响应块")
        yield ModelResponse(content="第二个响应块")

    monkeypatch.setattr(report_agent_module.ReportingOpenAIChat, "ainvoke_stream", model_stream)
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")
    responses = [
        response
        async for response in model.ainvoke_stream([Message(role="user", content="普通聊天")])
    ]

    assert [response.content for response in responses] == ["首个响应块", "第二个响应块"]


def test_report_facade_preserves_plain_sync_stream_content(monkeypatch) -> None:
    def model_stream(*_args, **_kwargs):
        yield ModelResponse(content="首个同步响应块")
        yield ModelResponse(content="第二个同步响应块")

    monkeypatch.setattr(report_agent_module.ReportingOpenAIChat, "invoke_stream", model_stream)
    model = ReportFacadeOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")

    responses = list(model.invoke_stream([Message(role="user", content="普通聊天")]))

    assert [response.content for response in responses] == [
        "首个同步响应块",
        "第二个同步响应块",
    ]


@pytest.mark.anyio
async def test_complete_analysis_item_is_exempt_from_analysis_tool_budget(monkeypatch) -> None:
    run_context = RunContext(
        run_id="run-analysis-complete",
        session_id="session-analysis-complete",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "analysis-task-002",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
            }
        },
    )
    monkeypatch.setattr(report_agent_module, "_REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_LIMIT", 1)

    first = await normalize_reporting_tool_arguments(
        run_context,
        "query_profile",
        lambda: {"ok": True},
        {},
    )
    completed = await normalize_reporting_tool_arguments(
        run_context,
        "complete_analysis_item",
        lambda: {"ok": True, "status": "accepted"},
        {},
    )

    assert first == {"ok": True}
    assert completed == {"ok": True, "status": "accepted"}


@pytest.mark.anyio
async def test_analysis_fact_query_subbudget_stops_before_third_call() -> None:
    run_context = RunContext(
        run_id="run-analysis-fact-budget",
        session_id="session-analysis-fact-budget",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "analysis-fact-budget",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
                REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY: 2,
            }
        },
    )
    calls = 0

    def facts() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    assert await normalize_reporting_tool_arguments(
        run_context, "query_analysis_facts", facts, {}
    ) == {"ok": True}
    assert await normalize_reporting_tool_arguments(
        run_context, "query_analysis_facts", facts, {}
    ) == {"ok": True}
    with pytest.raises(StopAgentRun, match="report_analysis_fact_query_budget_exhausted"):
        await normalize_reporting_tool_arguments(run_context, "query_analysis_facts", facts, {})

    assert calls == 2


@pytest.mark.anyio
async def test_analysis_recovery_rejects_old_tool_schema_before_execution() -> None:
    run_context = RunContext(
        run_id="run-analysis-recovery-closed",
        session_id="session-analysis-recovery-closed",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "analysis-recovery-closed",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "analysis_item",
                REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY: True,
            }
        },
    )
    called = False

    def old_schema_tool() -> dict[str, bool]:
        nonlocal called
        called = True
        return {"ok": True}

    with pytest.raises(StopAgentRun, match="report_analysis_recovery_closed"):
        await normalize_reporting_tool_arguments(run_context, "query_profile", old_schema_tool, {})

    assert called is False


@pytest.mark.anyio
async def test_analysis_tool_budget_counts_only_success_and_isolates_tasks(monkeypatch) -> None:
    shared_state: dict[str, object] = {}

    def context(run_id: str, external_run_id: str, task_kind: str = "analysis_item") -> RunContext:
        return RunContext(
            run_id=run_id,
            session_id="shared-session",
            session_state=shared_state,
            dependencies={
                REPORTING_TASK_DEPENDENCY: {
                    "externalRunId": external_run_id,
                    REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                    REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
                }
            },
        )

    monkeypatch.setattr(report_agent_module, "_REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_LIMIT", 1)
    first_task = context("run-analysis-1", "analysis-task-1")

    failed = await normalize_reporting_tool_arguments(
        first_task,
        "query_profile",
        lambda: {"ok": False, "code": "profile_query_invalid"},
        {},
    )
    succeeded = await normalize_reporting_tool_arguments(
        first_task,
        "query_profile",
        lambda: {"ok": True},
        {},
    )
    with pytest.raises(StopAgentRun, match="report_analysis_tool_budget_exhausted"):
        await normalize_reporting_tool_arguments(
            first_task,
            "query_profile",
            lambda: {"ok": True},
            {},
        )
    second_task = await normalize_reporting_tool_arguments(
        context("run-analysis-2", "analysis-task-2"),
        "query_profile",
        lambda: {"ok": True},
        {},
    )
    with pytest.raises(StopAgentRun, match="report_analysis_tool_budget_exhausted"):
        await normalize_reporting_tool_arguments(
            first_task,
            "query_profile",
            lambda: {"ok": True},
            {},
        )
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT", 1)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT", 1)
    visualization_context = context("run-visualization", "visualization-task", "visualization")
    visualization = await normalize_reporting_tool_arguments(
        visualization_context,
        "query_analysis_facts",
        lambda: {"ok": True},
        {},
    )
    with pytest.raises(StopAgentRun, match="report_visualization_tool_budget_exhausted"):
        await normalize_reporting_tool_arguments(
            visualization_context,
            "read_file",
            lambda: {"ok": True},
            {},
        )

    assert failed == {"ok": False, "code": "profile_query_invalid"}
    assert succeeded == {"ok": True}
    assert second_task == {"ok": True}
    assert visualization == {"ok": True}


@pytest.mark.anyio
async def test_visualization_total_budget_counts_failed_and_successful_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_context = RunContext(
        run_id="run-visualization-total-budget",
        session_id="session-visualization-total-budget",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-total-budget-task",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
            }
        },
    )
    calls = 0

    def result(ok: bool) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"ok": ok, **({} if ok else {"code": "workspace_error"})}

    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT", 2)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT", 2)

    failed = await normalize_reporting_tool_arguments(
        run_context,
        "read_file",
        lambda: result(False),
        {},
    )
    succeeded = await normalize_reporting_tool_arguments(
        run_context,
        "query_analysis_facts",
        lambda: result(True),
        {},
    )
    with pytest.raises(StopAgentRun, match="report_visualization_tool_budget_exhausted"):
        await normalize_reporting_tool_arguments(
            run_context,
            "read_file",
            lambda: result(True),
            {},
        )

    assert failed == {"ok": False, "code": "workspace_error"}
    assert succeeded == {"ok": True}
    assert calls == 2


@pytest.mark.anyio
async def test_visualization_registration_is_reserved_outside_tool_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_context = RunContext(
        run_id="run-visualization-register-budget",
        session_id="session-visualization-register-budget",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-register-budget-task",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
            }
        },
    )
    registered = False

    def register() -> dict[str, bool]:
        nonlocal registered
        registered = True
        return {"ok": True}

    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT", 1)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT", 1)

    await normalize_reporting_tool_arguments(
        run_context,
        "read_file",
        lambda: {"ok": True},
        {},
    )
    result = await normalize_reporting_tool_arguments(
        run_context,
        "register_report_charts",
        register,
        {},
    )
    with pytest.raises(StopAgentRun, match="report_chart_registration_closed"):
        await normalize_reporting_tool_arguments(
            run_context,
            "read_file",
            lambda: {"ok": True},
            {},
        )

    assert result == {"ok": True}
    assert registered is True
    assert (
        reporting_visualization_usage_from_run_context(run_context)["visualizationToolCalls"] == 1
    )


@pytest.mark.anyio
async def test_visualization_fact_exploration_subbudget_returns_receipt_and_keeps_run_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_context = RunContext(
        run_id="run-visualization-fact-subbudget",
        session_id="session-visualization-fact-subbudget",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-fact-subbudget-task",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
            }
        },
    )
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT", 20)

    for _ in range(4):
        result = await normalize_reporting_tool_arguments(
            run_context,
            "query_analysis_facts",
            lambda: {"ok": True},
            {},
        )
        assert result == {"ok": True}

    rejected = await normalize_reporting_tool_arguments(
        run_context,
        "query_analysis_facts",
        lambda: {"ok": True},
        {},
    )
    assert rejected["details"]["phaseState"] == "production_only"
    assert "register_report_charts" in rejected["details"]["allowedTerminalTools"]
    assert "finalize_report_analysis" in rejected["details"]["allowedTerminalTools"]
    terminal = await normalize_reporting_tool_arguments(
        run_context,
        "terminal",
        lambda: {"ok": True},
        {},
    )

    assert rejected["code"] == "report_visualization_exploration_budget_exhausted"
    assert terminal == {"ok": True}
    assert reporting_visualization_usage_from_run_context(run_context) == {
        "visualizationReadUnitsUsed": 0,
        "visualizationFactQueriesUsed": 4,
        "visualizationToolCalls": 6,
        "visualizationScriptFailures": 0,
        "visualizationAttemptSuccessfulToolCalls": 5,
        "visualizationAttemptRejectedToolCalls": 1,
    }


@pytest.mark.anyio
async def test_visualization_argument_errors_consume_total_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_context = RunContext(
        run_id="run-visualization-argument-budget",
        session_id="session-visualization-argument-budget",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-argument-budget-task",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
            }
        },
    )
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT", 1)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT", 1)

    failure = await normalize_reporting_tool_arguments(
        run_context,
        "read_file",
        lambda required_path: {"ok": True, "path": required_path},
        {},
    )
    with pytest.raises(StopAgentRun, match="report_visualization_tool_budget_exhausted"):
        await normalize_reporting_tool_arguments(
            run_context,
            "read_file",
            lambda: {"ok": True},
            {},
        )

    assert failure["code"] == "report_tool_arguments_invalid"


@pytest.mark.anyio
async def test_visualization_third_script_failure_stops_current_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_context = RunContext(
        run_id="run-visualization-script-failures",
        session_id="session-visualization-script-failures",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-script-failure-task",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
            }
        },
    )
    calls = 0

    def failed_script() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "ok": False,
            "status": "completed",
            "code": "execution_output_error",
            "details": {"failureCode": "python_traceback"},
        }

    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_SCRIPT_FAILURE_LIMIT", 3)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT", 10)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT", 10)

    for _ in range(2):
        result = await normalize_reporting_tool_arguments(
            run_context,
            "terminal",
            failed_script,
            {},
        )
        assert result["code"] == "execution_output_error"
    with pytest.raises(
        StopAgentRun,
        match="report_visualization_script_failure_limit_exhausted",
    ):
        await normalize_reporting_tool_arguments(
            run_context,
            "terminal",
            failed_script,
            {},
        )

    assert calls == 3


@pytest.mark.anyio
async def test_visualization_nonzero_terminal_exit_consumes_script_failure_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_context = RunContext(
        run_id="run-visualization-terminal-exit",
        session_id="session-visualization-terminal-exit",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-terminal-exit-task",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
            }
        },
    )
    calls = 0

    def failed_script() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"status": "failed", "exit_code": 1, "output": "Traceback"}

    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_SCRIPT_FAILURE_LIMIT", 3)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT", 10)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT", 10)

    for _ in range(2):
        result = await normalize_reporting_tool_arguments(
            run_context,
            "terminal",
            failed_script,
            {},
        )
        assert result["exit_code"] == 1
    with pytest.raises(
        StopAgentRun,
        match="report_visualization_script_failure_limit_exhausted",
    ):
        await normalize_reporting_tool_arguments(
            run_context,
            "terminal",
            failed_script,
            {},
        )

    assert calls == 3


@pytest.mark.anyio
async def test_visualization_exit_zero_self_check_errors_consume_script_failure_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_context = RunContext(
        run_id="run-visualization-self-check-failures",
        session_id="session-visualization-self-check-failures",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-self-check-failure-task",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
            }
        },
    )
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_SCRIPT_FAILURE_LIMIT", 1)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT", 10)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT", 10)

    with pytest.raises(
        StopAgentRun,
        match="report_visualization_script_failure_limit_exhausted",
    ):
        await normalize_reporting_tool_arguments(
            run_context,
            "terminal",
            lambda: {
                "status": "completed",
                "exit_code": 0,
                "output": "chart_income.png: ERROR 'int' object is not subscriptable\n",
            },
            {},
        )


@pytest.mark.anyio
async def test_visualization_retry_restores_cumulative_budget_from_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_context = RunContext(
        run_id="run-visualization-retry-budget",
        session_id="session-visualization-retry-budget",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-retry-budget-task",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
                REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY: 3,
                REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY: 2,
            }
        },
    )
    calls = 0

    def failed_script() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "ok": False,
            "code": "execution_output_error",
            "details": {"failureCode": "python_traceback"},
        }

    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_SCRIPT_FAILURE_LIMIT", 3)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT", 10)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT", 4)

    with pytest.raises(
        StopAgentRun,
        match="report_visualization_script_failure_limit_exhausted",
    ):
        await normalize_reporting_tool_arguments(
            run_context,
            "terminal",
            failed_script,
            {},
        )

    assert calls == 1


@pytest.mark.anyio
async def test_visualization_retry_total_budget_cannot_be_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_context = RunContext(
        run_id="run-visualization-retry-total-budget",
        session_id="session-visualization-retry-total-budget",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-retry-total-budget-task",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
                REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY: 3,
                REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY: 0,
            }
        },
    )
    calls = 0

    def succeeded() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT", 10)
    monkeypatch.setattr(report_agent_module, "_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT", 4)

    result = await normalize_reporting_tool_arguments(
        run_context,
        "read_file",
        succeeded,
        {},
    )
    with pytest.raises(StopAgentRun, match="report_visualization_tool_budget_exhausted"):
        await normalize_reporting_tool_arguments(
            run_context,
            "read_file",
            succeeded,
            {},
        )

    assert result == {"ok": True}
    assert calls == 1


@pytest.mark.anyio
async def test_visualization_registration_closes_self_check_tools_but_allows_finalize() -> None:
    run_context = RunContext(
        run_id="run-visualization",
        session_id="session-visualization",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-task",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
            }
        },
    )
    executed = False

    registered = await normalize_reporting_tool_arguments(
        run_context,
        "register_report_charts",
        lambda: {"ok": True, "status": "completed", "charts": [{"chartId": "income"}]},
        {},
    )

    def unexpected_tool_call() -> dict[str, bool]:
        nonlocal executed
        executed = True
        return {"ok": True}

    with pytest.raises(StopAgentRun, match="report_chart_registration_closed"):
        await normalize_reporting_tool_arguments(
            run_context,
            "terminal",
            unexpected_tool_call,
            {},
        )
    finalized = await normalize_reporting_tool_arguments(
        run_context,
        "finalize_report_analysis",
        lambda: {"ok": True, "status": "accepted", "taskFinished": True},
        {},
    )

    assert registered["ok"] is True
    assert executed is False
    assert finalized["taskFinished"] is True


@pytest.mark.anyio
async def test_visualization_retry_uses_durable_registration_dependency_to_block_tools() -> None:
    run_context = RunContext(
        run_id="run-visualization-retry",
        session_id="session-visualization-retry",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                "externalRunId": "visualization-task-retry",
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization",
                REPORTING_VISUALIZATION_REGISTERED_DEPENDENCY_KEY: True,
            }
        },
    )
    executed = False

    def unexpected_tool_call() -> dict[str, bool]:
        nonlocal executed
        executed = True
        return {"ok": True}

    with pytest.raises(StopAgentRun, match="report_chart_registration_closed"):
        await normalize_reporting_tool_arguments(
            run_context,
            "read_file",
            unexpected_tool_call,
            {},
        )

    assert executed is False


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


@pytest.mark.parametrize(
    ("phase", "task_kind", "expected_max_tokens"),
    [
        ("analysis", "analysis_item", 16_384),
        ("analysis", "visualization", 32_768),
        ("section", "section", 16_384),
    ],
)
def test_reporting_worker_applies_phase_output_token_limits(
    phase: str,
    task_kind: str,
    expected_max_tokens: int,
) -> None:
    model = ReportWorkerOpenAIChat(
        id="deepseek-v4-flash-0731",
        api_key="test",
        max_tokens=196_608,
    )
    context = RunContext(
        run_id=f"run-{task_kind}",
        session_id=f"session-{task_kind}",
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: phase,
                REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
            }
        },
    )

    with bind_reporting_run_context(context):
        request_model = model._phase_request_model(
            [Message(role="user", content=json.dumps({"phase": phase}))]
        )

    assert request_model.max_tokens == expected_max_tokens
    assert model.max_tokens == 196_608


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


def test_report_agent_exposes_verified_download_links_or_workspace_paths() -> None:
    worker = Agent(
        id="report-facade-artifact-contract-test",
        model=ProjectedOpenAIChat(id="report-facade-artifact-contract-test", api_key="test"),
        telemetry=False,
    )
    facade = report_agent_module.create_report_agent(worker, cast(Any, SimpleNamespace()))
    instructions = "\n".join(cast(list[str], facade.instructions))

    assert facade.id == "smart-reporting"
    assert facade.telemetry is False
    assert "`pdf.downloadUrl` 和 `word.downloadUrl`" in instructions
    assert "PDF 使用 `path`，Word 使用 `word.path`" in instructions
    assert "不得虚构返回中不存在的字段" in instructions
