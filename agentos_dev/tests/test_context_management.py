import json
from types import SimpleNamespace

import pytest
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.summary import SessionSummary
from agno.session.team import TeamSession

from agentos_dev.context_management import (
    COMPRESSIBLE_HISTORY_TOOLS,
    HISTORY_CONTEXT_DESCRIPTION,
    MAX_SUMMARY_TOKENS,
    ProtectedCompressionManager,
    RollingSessionSummaryManager,
    RollingSummaryResponse,
    ToolCompressionResponse,
    build_budgeted_history_context,
    build_history_context,
    clear_terminal_reasoning,
    clear_terminal_session_reasoning,
)


def test_coding_process_outputs_are_compressible_history():
    assert {"exec_command", "poll_process", "write_stdin"}.issubset(COMPRESSIBLE_HISTORY_TOOLS)


class CountingModel:
    id = "test-model"
    supports_native_structured_outputs = False
    supports_json_schema_outputs = False

    def count_tokens(self, messages, tools=None, output_schema=None):
        return sum(len(str(message.content)) for message in messages)


class SummaryModel(CountingModel):
    supports_native_structured_outputs = True

    def __init__(self, parsed=None, error=None):
        self.parsed = parsed
        self.error = error
        self.requests = []

    def response(self, messages, response_format=None, **kwargs):
        self.requests.append(messages)
        if self.error:
            raise self.error
        return SimpleNamespace(content=None, parsed=self.parsed)

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
