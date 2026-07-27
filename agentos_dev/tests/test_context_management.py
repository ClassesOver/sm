import hashlib
import json
from types import SimpleNamespace

import pytest
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.summary import SessionSummary
from agno.session.team import TeamSession

from agentos_dev.context_management import (
    COMPRESSIBLE_HISTORY_TOOLS,
    HISTORY_CONTEXT_DESCRIPTION,
    MAX_SUMMARY_TOKENS,
    SKILL_PRUNE_MIN_CHARS,
    CodingContextProjector,
    ContextBudgetController,
    ProtectedCompressionManager,
    RollingSessionSummaryManager,
    RollingSummaryResponse,
    ToolCompressionResponse,
    _parse_rolling_summary,
    build_budgeted_history_context,
    build_history_context,
    clear_terminal_reasoning,
    clear_terminal_session_reasoning,
    projected_coding_model,
)


def test_coding_process_outputs_are_compressible_history():
    assert {"exec_command", "poll_process", "write_stdin", "stop_process"}.issubset(
        COMPRESSIBLE_HISTORY_TOOLS
    )


def test_projected_coding_model_enables_parallel_calls_without_mutating_base_model():
    base = OpenAIChat(
        id="coding-model",
        request_params={"temperature": 0},
        extra_body={"enable_thinking": True},
    )

    projected = projected_coding_model(base)

    assert projected is not base
    assert projected.id == base.id
    assert projected.extra_body == base.extra_body
    assert projected.request_params == {
        "temperature": 0,
        "parallel_tool_calls": True,
    }
    assert base.request_params == {"temperature": 0}
    assert projected.get_request_params()["parallel_tool_calls"] is True


class CountingModel:
    id = "test-model"
    supports_native_structured_outputs = False
    supports_json_schema_outputs = False

    def count_tokens(self, messages, tools=None, output_schema=None):
        return sum(len(str(message.content)) for message in messages)


class SummaryModel(CountingModel):
    supports_native_structured_outputs = True

    def __init__(self, parsed=None, content=None, error=None):
        self.parsed = parsed
        self.content = content
        self.error = error
        self.requests = []

    def response(self, messages, response_format=None, **kwargs):
        self.requests.append(messages)
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.content, parsed=self.parsed)

    async def aresponse(self, messages, response_format=None, **kwargs):
        return self.response(messages, response_format=response_format, **kwargs)


class BrokenCountingModel(CountingModel):
    def count_tokens(self, messages, tools=None, output_schema=None):
        raise RuntimeError("tokenizer unavailable")


def run(*messages, run_id="run-1"):
    return SimpleNamespace(
        run_id=run_id,
        messages=list(messages),
        status="completed",
    )


def test_history_context_excludes_old_odoo_results_and_host_context():
    session = SimpleNamespace(
        runs=[
            run(
                Message(
                    role="user",
                    content="打开员工页面\n\n<additional context>snapshotId=stale</additional context>",
                ),
                Message(
                    role="tool", tool_name="odoo.open_record", content='{"snapshotId":"stale"}'
                ),
                Message(role="assistant", content="已打开页面"),
                Message(role="assistant", content='旧绑定 token="secret-token"'),
                run_id="run-1",
            )
        ],
        summary=None,
    )

    value = build_history_context(session, CountingModel(), history_token_budget=1024)

    assert value is not None
    assert value.description == HISTORY_CONTEXT_DESCRIPTION
    assert "stale" not in value.value
    assert "打开员工页面" in value.value
    assert "已打开页面" in value.value
    assert "odoo.open_record" not in value.value
    assert "secret-token" not in value.value
    assert session.runs[0].messages[1].content == '{"snapshotId":"stale"}'


def test_team_history_context_excludes_delegated_member_runs():
    session = TeamSession(
        session_id="thread-1",
        team_id="hrp-assistant-team",
        runs=[
            TeamRunOutput(
                run_id="team-run",
                session_id="thread-1",
                team_id="hrp-assistant-team",
                status=RunStatus.completed,
                messages=[
                    Message(role="user", content="生成本月报表"),
                    Message(role="assistant", content="报表已生成"),
                ],
            ),
            RunOutput(
                run_id="member-run",
                parent_run_id="team-run",
                session_id="thread-1",
                agent_id="report-agent",
                status=RunStatus.completed,
                messages=[Message(role="assistant", content="成员内部重复结果")],
            ),
        ],
    )

    value = build_history_context(session, CountingModel(), history_token_budget=1024)

    assert value is not None
    assert "生成本月报表" in value.value
    assert "报表已生成" in value.value
    assert "成员内部重复结果" not in value.value


def test_history_context_uses_summary_and_budget_fallback():
    messages = [Message(role="user", content="旧问题" + "x" * 100)]
    session = SimpleNamespace(
        runs=[run(*messages, run_id="run-1")],
        summary=SimpleNamespace(summary="滚动摘要"),
    )

    value = build_history_context(session, CountingModel(), history_token_budget=4)

    assert value is not None
    assert "滚动摘要" in value.value
    assert "旧问题" not in value.value


def test_history_context_reports_budget_usage_without_business_data():
    session = SimpleNamespace(
        runs=[run(Message(role="user", content="最近问题"), run_id="run-1")],
        summary=SimpleNamespace(summary="滚动摘要"),
    )
    status = {}

    value = build_history_context(
        session,
        CountingModel(),
        history_token_budget=1024,
        status=status,
    )

    assert value is not None
    assert status["historyTokenBudget"] == 1024
    assert status["historyTokensUsed"] > 0
    assert status["historyTokensRemaining"] < 1024
    assert status["summaryIncluded"] is True
    assert status["tokenCountReliable"] is True
    assert "最近问题" not in str(status)


def test_token_count_failure_only_keeps_the_latest_complete_run():
    session = SimpleNamespace(
        runs=[
            run(Message(role="user", content="第一轮"), run_id="run-1"),
            run(Message(role="user", content="第二轮"), run_id="run-2"),
        ],
        summary=SimpleNamespace(summary="滚动摘要"),
    )

    value = build_history_context(session, BrokenCountingModel(), history_token_budget=1024)

    assert value is not None
    assert "滚动摘要" in value.value
    assert "第二轮" in value.value
    assert "第一轮" not in value.value


def test_protected_compression_only_selects_historical_analysis_results():
    manager = ProtectedCompressionManager(model=CountingModel(), compress_tool_results_limit=1)
    historical_analysis = Message(
        role="tool",
        tool_name="report_analyze_dataset",
        content='{"ok":true,"sha256":"abc"}',
    )
    historical_analysis.from_history = True
    current_analysis = Message(
        role="tool",
        tool_name="report_analyze_dataset",
        content='{"ok":true,"sha256":"current"}',
    )
    odoo_result = Message(role="tool", tool_name="odoo.open_record", content='{"token":"secret"}')
    odoo_result.from_history = True
    render_result = Message(
        role="tool",
        tool_name="report_render_markdown",
        content='{"pdfPath":"报表/结果.pdf"}',
    )
    render_result.from_history = True
    process_result = Message(
        role="tool",
        tool_name="sandbox_process_poll",
        content='{"status":"completed","exitCode":0,"output":"large"}',
    )
    process_result.from_history = True

    assert manager.should_compress([historical_analysis]) is True
    assert manager.should_compress([current_analysis]) is False
    assert manager.should_compress([odoo_result]) is False
    assert manager.should_compress([render_result]) is False
    assert manager.should_compress([process_result]) is True


def test_compression_tokenizer_failure_does_not_fail_main_run():
    manager = ProtectedCompressionManager(model=CountingModel(), compress_token_limit=1)
    analysis = Message(role="tool", tool_name="sandbox_exec", content="large output")
    analysis.from_history = True

    assert manager.should_compress([analysis], model=BrokenCountingModel()) is False


def test_coding_context_controller_keeps_below_budget_history_uncompressed():
    controller = ContextBudgetController(model=CountingModel(), context_token_budget=200_000)
    old = Message(
        role="tool",
        tool_name="terminal",
        tool_args={"command": "pytest"},
        content=json.dumps({"status": "completed", "outputHandle": "opaque", "output": "x" * 1000}),
    )
    recent = Message(role="tool", tool_name="read_file", content='{"content":"latest"}')
    messages = [
        Message(role="assistant", content="first"),
        old,
        Message(role="assistant", content="second"),
        recent,
        Message(role="assistant", content="third"),
    ]

    prepared = controller.prepare_context(messages)

    assert old.compressed_content is None
    assert prepared[1].compressed_content is None
    assert prepared[3].compressed_content is None
    assert controller.context_token_limit == 96 * 1024
    assert controller.input_token_budget == 64 * 1024


def test_coding_context_projection_keeps_append_only_provider_prefix_stable():
    create_args = json.dumps({"path": "report.md", "content": "x" * 2000})
    messages = [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-create",
                    "type": "function",
                    "function": {"name": "create_file", "arguments": create_args},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="create_file",
            tool_call_id="call-create",
            content='{"ok":true}',
        ),
        Message(role="assistant", content="继续检查"),
    ]

    first = CodingContextProjector.project(messages)
    second = CodingContextProjector.project(
        [*messages, Message(role="assistant", content="准备下一步")]
    )

    def provider_value(message):
        return (
            message.role,
            message.get_content(use_compressed_content=True),
            message.tool_call_id,
            message.tool_calls,
        )

    assert [provider_value(message) for message in first] == [
        provider_value(message) for message in second[: len(first)]
    ]

    messages[1].compressed_content = ContextBudgetController._coding_receipt(messages[1])
    rebased_first = CodingContextProjector.project(messages)
    rebased_second = CodingContextProjector.project(
        [*messages, Message(role="assistant", content="压缩后继续")]
    )

    assert [provider_value(message) for message in rebased_first] == [
        provider_value(message) for message in rebased_second[: len(rebased_first)]
    ]


def test_coding_context_controller_defers_skill_pruning_until_budget_rebase():
    body = "x" * (SKILL_PRUNE_MIN_CHARS + 1)
    old = skill_result(body)
    messages = [old, *[Message(role="assistant", content=str(i)) for i in range(10)]]
    controller = ContextBudgetController(model=CountingModel(), context_token_budget=200_000)

    stable = controller.prepare_context(messages)

    assert stable[0].compressed_content is None
    assert old.compressed_content is None

    constrained = ContextBudgetController(model=CountingModel(), context_token_budget=32_769)
    rebased = constrained.prepare_context(messages)

    assert json.loads(rebased[0].compressed_content)["marker"] == "SKILL_PRUNED"
    assert old.compressed_content is None


def test_coding_context_controller_emits_structured_checkpoint_when_over_budget():
    controller = ContextBudgetController(model=CountingModel(), context_token_budget=32_769)
    messages = [
        Message(role="assistant", content="first"),
        Message(role="tool", tool_name="terminal", content='{"output":"large"}'),
        Message(
            role="tool",
            tool_name="patch",
            content='{"mutation_sequence":3,"files":[{"path":"app.py"}]}',
        ),
        Message(
            role="tool",
            tool_name="process",
            content='{"processes":[{"execution_id":"serve","status":"running"}]}',
        ),
        skill_result("rules", path="guide.md", tool_name="get_skill_reference"),
        Message(role="assistant", content="second"),
        Message(role="assistant", content="third"),
    ]

    prepared = controller.prepare_context(messages)

    checkpoint = json.loads(prepared[1].compressed_content)
    assert checkpoint["marker"] == "CODING_CHECKPOINT"
    assert checkpoint["changedFiles"] == ["app.py"]
    assert checkpoint["mutation"] == 3
    assert checkpoint["activeProcesses"] == [{"executionId": "serve", "status": "running"}]
    assert checkpoint["skillReceipts"][0]["path"] == "guide.md"
    assert checkpoint["toolReceipts"][0]["tool"] == "terminal"


def test_coding_context_controller_uses_fallback_count_when_tokenizer_fails():
    controller = ContextBudgetController(model=BrokenCountingModel(), context_token_budget=32_769)
    messages = [
        Message(role="assistant", content="old " + "x" * 100),
        Message(role="assistant", content="second"),
        Message(role="assistant", content="third"),
    ]

    assert controller.should_compress(messages) is True

    prepared = controller.prepare_context(messages)

    assert json.loads(prepared[0].compressed_content)["marker"] == "CODING_CHECKPOINT"
    assert messages[0].compressed_content is None


def test_coding_context_projector_compacts_consumed_tool_pair_without_mutating_raw():
    large_content = "x" * 5000
    create_args = json.dumps({"path": "report.md", "content": large_content})
    latest_args = json.dumps({"command": "python verify.py"})
    messages = [
        Message(
            role="assistant",
            content="create",
            tool_calls=[
                {
                    "id": "call-create",
                    "type": "function",
                    "function": {"name": "create_file", "arguments": create_args},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="create_file",
            tool_call_id="call-create",
            tool_args={"path": "report.md", "content": large_content},
            content=json.dumps(
                {
                    "ok": True,
                    "files": [{"path": "report.md", "sha256": "a" * 64}],
                    "mutation_sequence": 1,
                }
            ),
        ),
        Message(
            role="assistant",
            content="verify",
            tool_calls=[
                {
                    "id": "call-latest",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": latest_args},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="terminal",
            tool_call_id="call-latest",
            tool_args={"command": "python verify.py"},
            content=json.dumps({"status": "completed", "output": "ok"}),
        ),
        Message(role="assistant", content="continue"),
    ]
    receipt = ContextBudgetController._coding_receipt(messages[1])
    messages[1].compressed_content = receipt

    projected = CodingContextProjector.project(messages)

    assert messages[0].tool_calls[0]["function"]["arguments"] == create_args
    assert messages[1].compressed_content == receipt
    compact_args = json.loads(projected[0].tool_calls[0]["function"]["arguments"])
    assert compact_args["path"] == "report.md"
    assert "CONTEXT_PRUNED" in compact_args["content"]
    assert large_content not in projected[0].tool_calls[0]["function"]["arguments"]
    assert json.loads(projected[1].compressed_content)["marker"] == "CODING_TOOL_RECEIPT"
    assert projected[0].tool_calls[0]["id"] == projected[1].tool_call_id == "call-create"
    assert projected[2].tool_calls[0]["function"]["arguments"] == latest_args
    assert projected[3].compressed_content is None


def test_coding_context_projector_keeps_recent_read_facts_after_another_tool_call():
    facts = '{"path":"summary.json","content":"AUTHORITATIVE_FACTS"}'
    messages = [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-read",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"summary.json"}',
                    },
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="read_file",
            tool_call_id="call-read",
            content=facts,
        ),
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-tree",
                    "type": "function",
                    "function": {"name": "tree", "arguments": '{"path":""}'},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="tree",
            tool_call_id="call-tree",
            content='{"files":["summary.json"]}',
        ),
    ]

    projected = CodingContextProjector.project(messages)

    assert projected[1].content == facts
    assert projected[1].compressed_content is None
    assert projected[3].compressed_content is None
    assert messages[1].content == facts
    assert messages[1].compressed_content is None


def test_coding_context_projector_keeps_uncompressed_latest_mutation_arguments():
    first_content = "first" * 1000
    latest_content = "latest" * 1000
    first_args = json.dumps({"path": "analysis.py", "content": first_content})
    latest_args = json.dumps(
        {
            "path": "analysis.py",
            "content": latest_content,
            "expected_sha256": "a" * 64,
        }
    )
    messages = [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-create",
                    "type": "function",
                    "function": {"name": "create_file", "arguments": first_args},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="create_file",
            tool_call_id="call-create",
            content='{"ok":true}',
        ),
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-overwrite",
                    "type": "function",
                    "function": {"name": "overwrite_file", "arguments": latest_args},
                }
            ],
        ),
        Message(
            role="tool",
            tool_name="overwrite_file",
            tool_call_id="call-overwrite",
            content='{"ok":true}',
        ),
        Message(role="assistant", content="continue"),
    ]
    messages[1].compressed_content = ContextBudgetController._coding_receipt(messages[1])

    projected = CodingContextProjector.project(messages)

    assert "CONTEXT_PRUNED" in projected[0].tool_calls[0]["function"]["arguments"]
    assert projected[2].tool_calls[0]["function"]["arguments"] == latest_args
    assert messages[0].tool_calls[0]["function"]["arguments"] == first_args
    assert messages[2].tool_calls[0]["function"]["arguments"] == latest_args


def test_coding_tool_receipt_preserves_bounded_continuation_state():
    message = Message(
        role="tool",
        tool_name="overwrite_file",
        tool_args={"path": "analysis.py", "content": "x" * 5000},
        content=json.dumps(
            {
                "ok": True,
                "execution_id": "execution-1",
                "mutation_sequence": 7,
                "files": [
                    {
                        "operation": "update",
                        "path": "analysis.py",
                        "size": 5000,
                        "sha256": "b" * 64,
                    }
                ],
            }
        ),
    )

    receipt = json.loads(ContextBudgetController._coding_receipt(message))

    assert receipt["state"] == {
        "execution_id": "execution-1",
        "mutation_sequence": 7,
        "files": [
            {
                "operation": "update",
                "path": "analysis.py",
                "size": 5000,
                "sha256": "b" * 64,
            }
        ],
    }
    assert receipt["arguments"] == {
        "keys": ["content", "path"],
        "sha256": hashlib.sha256(
            json.dumps(
                {"content": "x" * 5000, "path": "analysis.py"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }


def skill_result(
    body: str,
    *,
    tool_name: str = "get_skill_instructions",
    path: str | None = None,
    execute: bool = False,
) -> Message:
    args = {"skill_name": "review"}
    payload = {"skill_name": "review"}
    if tool_name == "get_skill_instructions":
        payload["instructions"] = body
    elif tool_name == "get_skill_reference":
        args["reference_path"] = path
        payload.update(reference_path=path, content=body)
    else:
        args.update(script_path=path, execute=execute)
        payload.update(script_path=path, content=body)
    message = Message(
        role="tool",
        tool_name=tool_name,
        tool_args=args,
        content=json.dumps(payload),
    )
    return message


def test_skill_compression_prunes_only_old_large_content_and_preserves_raw_result():
    manager = ProtectedCompressionManager(model=CountingModel(), compress_tool_results_limit=100)
    boundary = skill_result("x" * SKILL_PRUNE_MIN_CHARS)
    old = skill_result(
        "y" * (SKILL_PRUNE_MIN_CHARS + 1),
        tool_name="get_skill_reference",
        path="guide.md",
    )
    messages = [boundary, old, *[Message(role="assistant", content=str(i)) for i in range(10)]]
    original = old.content

    assert manager.should_compress(messages) is True
    manager.compress(messages)

    assert boundary.compressed_content is None
    assert old.content == original
    marker = json.loads(old.compressed_content)
    assert marker == {
        "chars": SKILL_PRUNE_MIN_CHARS + 1,
        "marker": "SKILL_PRUNED",
        "path": "guide.md",
        "reload": {"reference_path": "guide.md", "skill_name": "review"},
        "sha256": hashlib.sha256(("y" * 5001).encode()).hexdigest(),
        "skill": "review",
        "tool": "get_skill_reference",
    }


def test_skill_compression_prunes_duplicate_but_keeps_latest_and_exempts_executed_script():
    manager = ProtectedCompressionManager(model=CountingModel(), compress_tool_results_limit=100)
    first = skill_result("first")
    latest = skill_result("latest")
    executed = skill_result(
        "script output",
        tool_name="get_skill_script",
        path="check.py",
        execute=True,
    )
    messages = [first, Message(role="assistant", content="continue"), latest, executed]

    manager.compress(messages)

    assert json.loads(first.compressed_content)["marker"] == "SKILL_PRUNED"
    assert latest.compressed_content is None
    assert executed.compressed_content is None


@pytest.mark.anyio
async def test_compression_preserves_coding_process_continuation_metadata():
    manager = ProtectedCompressionManager(
        model=SummaryModel(parsed=ToolCompressionResponse(summary="服务仍在运行")),
        compress_tool_results_limit=1,
    )
    process_result = Message(
        role="tool",
        tool_name="exec_command",
        content=json.dumps(
            {
                "status": "running",
                "session_id": 7,
                "timeout_seconds": 3600,
                "outcome": "running",
                "output": "x" * 3000,
            }
        ),
    )

    candidate = await manager.compress_history_message(process_result)

    assert candidate.compressed_content is not None
    compressed = json.loads(candidate.compressed_content)
    assert compressed["exact"]["$.session_id"] == 7
    assert compressed["exact"]["$.timeout_seconds"] == 3600
    assert compressed["exact"]["$.outcome"] == "running"
    assert "xxx" not in candidate.compressed_content


@pytest.mark.anyio
async def test_budgeted_history_compresses_analysis_without_changing_raw_content():
    compression_model = SummaryModel(
        ToolCompressionResponse(summary="共 15 人", key_findings=["已生成 报表/结果.csv"])
    )
    manager = ProtectedCompressionManager(model=compression_model, compress_tool_results_limit=1)
    analysis = Message(
        role="tool",
        tool_name="report_analyze_dataset",
        content=json.dumps(
            {
                "ok": True,
                "status": "completed",
                "output": {"path": "报表/结果.csv", "sha256": "abc"},
                "rows": list(range(1000)),
            },
            ensure_ascii=False,
        ),
    )
    session = SimpleNamespace(
        runs=[run(Message(role="user", content="分析员工"), analysis)],
        summary=None,
        session_data={},
    )

    value, changed = await build_budgeted_history_context(
        session,
        CountingModel(),
        history_token_budget=4096,
        compression_manager=manager,
    )

    assert changed is True
    assert json.loads(analysis.content)["rows"][-1] == 999
    assert analysis.compressed_content is not None
    assert "共 15 人" in analysis.compressed_content
    assert "报表/结果.csv" in analysis.compressed_content
    assert "abc" in analysis.compressed_content
    assert value is not None
    assert "rows" not in value.value
    assert "JSON" in str(compression_model.requests[0][0].content)


@pytest.mark.anyio
async def test_compression_failure_does_not_inject_uncompressed_analysis_result():
    manager = ProtectedCompressionManager(
        model=SummaryModel(error=RuntimeError("provider unavailable")),
        compress_tool_results_limit=1,
    )
    analysis = Message(
        role="tool",
        tool_name="sandbox_exec",
        content="sensitive raw output" * 1000,
    )
    session = SimpleNamespace(
        runs=[run(Message(role="user", content="继续分析"), analysis)],
        summary=None,
        session_data={},
    )

    value, changed = await build_budgeted_history_context(
        session,
        CountingModel(),
        history_token_budget=4096,
        compression_manager=manager,
    )

    assert changed is False
    assert analysis.compressed_content is None
    assert value is None


@pytest.mark.anyio
async def test_compression_rejects_summary_with_old_odoo_binding():
    manager = ProtectedCompressionManager(
        model=SummaryModel(
            parsed=ToolCompressionResponse(
                summary='沿用 snapshotId="stale"',
                key_findings=[],
            )
        ),
        compress_tool_results_limit=1,
    )
    analysis = Message(
        role="tool",
        tool_name="report_analyze_dataset",
        content="analysis output" * 200,
    )

    candidate = await manager.compress_history_message(analysis)

    assert candidate.compressed_content is None


@pytest.mark.anyio
async def test_rolling_summary_uses_previous_summary_and_only_new_messages():
    response = RollingSummaryResponse(
        goal="生成员工报表",
        decisions=["输出 PDF"],
        artifacts=["报表/员工.md"],
        completed=["完成数据分析"],
        pending=["渲染 PDF"],
    )
    model = SummaryModel(parsed=response)
    manager = RollingSessionSummaryManager(model=model)
    first = run(
        Message(role="user", content="旧请求"),
        Message(role="assistant", content="旧回答"),
        run_id="run-1",
    )
    second = run(
        Message(role="user", content="继续生成 PDF"),
        Message(role="tool", tool_name="odoo.open_record", content='{"snapshotId":"secret"}'),
        Message(role="assistant", content='旧绑定 token="secret-token"'),
        Message(role="assistant", content="已准备 Markdown"),
        run_id="run-2",
    )
    session = SimpleNamespace(
        runs=[first, second],
        summary=SessionSummary(summary='{"goal":"旧目标"}'),
        session_data={
            "agentos_rolling_summary": {
                "version": 1,
                "lastSourceRunId": "run-1",
                "sourceDigest": manager.source_digest([first]),
            }
        },
    )

    result = await manager.acreate_session_summary(session)

    assert result is session.summary
    assert "JSON" in str(model.requests[0][0].content)
    request = str(model.requests[0][-1].content)
    assert "旧目标" in request
    assert "继续生成 PDF" in request
    assert "已准备 Markdown" in request
    assert "旧请求" not in request
    assert "snapshotId" not in request
    assert "secret-token" not in request
    metadata = session.session_data["agentos_rolling_summary"]
    assert metadata["version"] == 2
    assert metadata["lastSourceRunId"] == "run-2"


def test_rolling_summary_accepts_structured_dict():
    response = SimpleNamespace(
        parsed={
            "goal": "生成员工报表",
            "decisions": ["输出 PDF"],
            "artifacts": [],
            "completed": [],
            "pending": [],
        },
        content=None,
    )

    result = _parse_rolling_summary(response)

    assert result is not None
    assert result.goal == "生成员工报表"


def test_rolling_summary_accepts_complete_json_fence():
    content = """```json
{"goal":"生成员工报表","decisions":[],"artifacts":[],"completed":[],"pending":[]}
```"""

    result = _parse_rolling_summary(SimpleNamespace(parsed=None, content=content))

    assert result is not None
    assert result.goal == "生成员工报表"


@pytest.mark.parametrize(
    "content",
    [
        '摘要如下：{"goal":"目标"}',
        '{"goal":"目标","unexpected":true}',
    ],
)
def test_rolling_summary_rejects_prose_and_unknown_fields(content):
    response = SimpleNamespace(parsed=None, content=content)

    assert _parse_rolling_summary(response) is None


@pytest.mark.anyio
async def test_rolling_summary_rebuilds_after_history_replacement():
    response = RollingSummaryResponse(
        goal="重建目标",
        decisions=[],
        artifacts=[],
        completed=[],
        pending=[],
    )
    model = SummaryModel(parsed=response)
    manager = RollingSessionSummaryManager(model=model)
    first = run(Message(role="user", content="被替换的新内容"), run_id="run-1")
    session = SimpleNamespace(
        runs=[first],
        summary=SessionSummary(summary='{"goal":"失效摘要"}'),
        session_data={
            "agentos_rolling_summary": {
                "version": 4,
                "lastSourceRunId": "run-1",
                "sourceDigest": "stale-digest",
            }
        },
    )

    await manager.acreate_session_summary(session)

    request = str(model.requests[0][-1].content)
    assert "失效摘要" not in request
    assert "被替换的新内容" in request
    assert session.session_data["agentos_rolling_summary"]["version"] == 1


@pytest.mark.anyio
async def test_rolling_summary_rebuilds_when_previous_summary_contains_old_binding():
    model = SummaryModel(
        parsed=RollingSummaryResponse(
            goal="安全目标",
            decisions=[],
            artifacts=[],
            completed=[],
            pending=[],
        )
    )
    manager = RollingSessionSummaryManager(model=model)
    first = run(Message(role="user", content="重新总结"), run_id="run-1")
    session = SimpleNamespace(
        runs=[first],
        summary=SessionSummary(summary='{"goal":"snapshotId=stale"}'),
        session_data={
            "agentos_rolling_summary": {
                "version": 4,
                "lastSourceRunId": "run-1",
                "sourceDigest": manager.source_digest([first]),
            }
        },
    )

    await manager.acreate_session_summary(session)

    request = str(model.requests[0][-1].content)
    assert "snapshotId" not in request
    assert session.session_data["agentos_rolling_summary"]["version"] == 1


@pytest.mark.anyio
async def test_rolling_summary_failure_keeps_previous_version():
    model = SummaryModel(error=RuntimeError("provider unavailable"))
    manager = RollingSessionSummaryManager(model=model)
    first = run(Message(role="user", content="旧请求"), run_id="run-1")
    second = run(Message(role="user", content="新请求"), run_id="run-2")
    previous = SessionSummary(summary='{"goal":"保留目标"}')
    metadata = {
        "version": 2,
        "lastSourceRunId": "run-1",
        "sourceDigest": manager.source_digest([first]),
    }
    session = SimpleNamespace(
        runs=[first, second],
        summary=previous,
        session_data={"agentos_rolling_summary": metadata.copy()},
    )

    result = await manager.acreate_session_summary(session)

    assert result is previous
    assert session.summary is previous
    assert session.session_data["agentos_rolling_summary"] == metadata


def test_summary_budget_constant_is_below_history_budget():
    assert MAX_SUMMARY_TOKENS == 4096


def test_terminal_reasoning_is_removed_before_persistence():
    message = Message(
        role="assistant",
        content="最终答复",
        reasoning_content="raw reasoning",
        redacted_reasoning_content="encrypted reasoning",
        provider_data={"reasoning_content": "provider reasoning", "request_id": "req-1"},
    )
    output = SimpleNamespace(
        reasoning_content="run reasoning",
        reasoning_messages=[message],
        reasoning_steps=[{"reasoning": "step reasoning"}],
        model_provider_data={"thinking": "provider thinking", "request_id": "req-1"},
        messages=[message],
    )

    clear_terminal_reasoning(output)

    assert output.reasoning_content is None
    assert output.reasoning_messages is None
    assert output.reasoning_steps is None
    assert output.model_provider_data == {"request_id": "req-1"}
    assert message.reasoning_content is None
    assert message.redacted_reasoning_content is None
    assert message.provider_data == {"request_id": "req-1"}


def test_session_persistence_clears_terminal_but_keeps_paused_reasoning():
    completed = SimpleNamespace(status="completed", reasoning_content="terminal", messages=[])
    paused = SimpleNamespace(status="paused", reasoning_content="resume state", messages=[])
    session = SimpleNamespace(runs=[completed, paused])

    clear_terminal_session_reasoning(session)

    assert completed.reasoning_content is None
    assert paused.reasoning_content == "resume state"
