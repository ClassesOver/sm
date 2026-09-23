"""同一 run 内压缩后重新 arun：压缩窗口、摘要载荷与有界重连。"""

import json
from types import SimpleNamespace

import pytest
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from openai.types.responses import Response

from smart_reporting.reporting.agent import create_reporting_code_agent_factory
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_code_agent_trajectories import _ResponsesClient
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    ToolkitRuntime,
    _batch_response,
    _custom_response,
    _function_response,
    _message_response,
    _run_context,
    _task_context,
    workspace,  # noqa: F401
)
from smart_reporting.reporting.workflow.runtime import code_generation
from smart_reporting.reporting.workflow.runtime.code_generation import ReportingCodeGenerationRunner


def _with_usage(response: Response, input_tokens: int) -> Response:
    payload = response.model_dump()
    payload["usage"] = {
        "input_tokens": input_tokens,
        "output_tokens": 5,
        "total_tokens": input_tokens + 5,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    }
    return Response.model_validate(payload)


def _make_agent_factory(client: _ResponsesClient, name: str, agents: list):
    factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test", api_key="test"), name=name
    )

    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        agents.append(agent)
        return agent

    return make_agent


def _request_input_text(request: dict) -> str:
    return json.dumps(request["input"], ensure_ascii=False)


def _user_message_text(request: dict) -> str:
    chunks: list[str] = []
    for item in request["input"]:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            chunks.extend(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
    return "\n".join(chunks)


@pytest.fixture
def low_compaction_threshold(monkeypatch):
    monkeypatch.setattr(code_generation, "RUN_COMPACTION_INPUT_TOKEN_THRESHOLD", 100)


@pytest.mark.anyio
async def test_in_run_compaction_reconnects_with_fresh_window_and_summary(
    workspace, low_compaction_threshold, monkeypatch  # noqa: F811
):
    first = _batch_response(
        _custom_response("write_script", SOURCE, 1),
        _function_response(2, "run_script", {}),
    )
    client = _ResponsesClient([
        _with_usage(first, 150),
        _with_usage(_message_response("已完成"), 150),
        _with_usage(_function_response(3, "submit_script", {}), 10),
    ])
    agents = []

    async def forbidden_continue(*args, **kwargs):
        pytest.fail("压缩重连不得调用 acontinue_run 回放完整旧历史")

    monkeypatch.setattr(Agent, "acontinue_run", forbidden_continue)
    metrics = []
    result = await ReportingCodeGenerationRunner(
        _make_agent_factory(client, "run-compaction", agents),
        ToolkitRuntime(),
        ReportingLspProcessManager(),
        compact_continuation=True,
        coding_metrics_recorder=metrics.append,
    ).run(_task_context(workspace), workspace, {}, run_context=_run_context())

    assert result.execution_receipt.source_file.path == "analysis/a.py"
    assert len(agents) == 1
    # 预算与逐请求指标在同一模型实例上连续累计。
    assert agents[0].model.code_run_tool_count() == 3
    assert metrics[0]["modelRequests"] == 3
    assert metrics[0]["compactContinuationApplied"] is True
    # 验收字段：压缩窗口与前后 token。
    assert metrics[0]["compactionTriggered"] is True
    assert metrics[0]["compactionWindowId"] == 1
    assert metrics[0]["compactionBeforeTokens"] == 150
    assert metrics[0]["compactionAfterTokens"] == 10
    assert metrics[0]["retainedCallCount"] == 2
    assert metrics[0]["truncatedCallCount"] == 0
    # 新窗口请求不回放任何旧工具调用，只携带任务边界与压缩摘要。
    assert len(client.requests) == 3
    last_input = client.requests[-1]["input"]
    assert not any(
        item.get("type") in {"function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output"}
        for item in last_input
    )
    text = _user_message_text(client.requests[-1])
    assert '"compaction"' in text
    assert '"windowId":1' in text
    assert '"sourceSha256"' in text
    assert '"summarizedToolCalls"' in text


@pytest.mark.anyio
async def test_compaction_reconnect_is_bounded_and_reports_failure_fields(
    workspace, low_compaction_threshold, monkeypatch  # noqa: F811
):
    first = _batch_response(
        _custom_response("write_script", SOURCE, 1),
        _function_response(2, "run_script", {}),
    )
    client = _ResponsesClient([
        _with_usage(first, 150),
        _with_usage(_message_response("还未提交"), 150),
        _with_usage(_message_response("继续说明但不调用工具"), 150),
        _with_usage(_message_response("仍不提交"), 150),
    ])
    agents = []

    async def forbidden_continue(*args, **kwargs):
        pytest.fail("压缩重连不得调用 acontinue_run 回放完整旧历史")

    monkeypatch.setattr(Agent, "acontinue_run", forbidden_continue)
    metrics = []
    with pytest.raises(ReportingError, match="report_code_generation_no_submission") as caught:
        await ReportingCodeGenerationRunner(
            _make_agent_factory(client, "run-compaction-bound", agents),
            ToolkitRuntime(),
            ReportingLspProcessManager(),
            compact_continuation=True,
            coding_metrics_recorder=metrics.append,
        ).run(_task_context(workspace), workspace, {}, run_context=_run_context())

    # 压缩重连有界：最多 MAX_RUN_COMPACTION_CONTINUATIONS 个压缩窗口后停止。
    assert len(client.requests) == 4
    assert metrics[0]["compactionTriggered"] is True
    assert metrics[0]["compactionWindowId"] == code_generation.MAX_RUN_COMPACTION_CONTINUATIONS
    assert metrics[0]["retainedCallCount"] == 2
    details = caught.value.details
    assert details["compactionTriggered"] is True
    assert details["compactionWindowId"] == code_generation.MAX_RUN_COMPACTION_CONTINUATIONS
    assert details["compactionBeforeTokens"] == 150
    assert details["compactionAfterTokens"] == 150
    assert details["retainedCallCount"] == 2
    assert details["truncatedCallCount"] == 0


@pytest.mark.anyio
async def test_without_compaction_signal_single_continuation_and_no_summary(
    workspace, monkeypatch  # noqa: F811
):
    first = _batch_response(
        _custom_response("write_script", SOURCE, 1),
        _function_response(2, "run_script", {}),
    )
    client = _ResponsesClient([
        first,
        _message_response("已完成"),
        _function_response(3, "submit_script", {}),
    ])
    agents = []
    metrics = []
    result = await ReportingCodeGenerationRunner(
        _make_agent_factory(client, "run-compaction-idle", agents),
        ToolkitRuntime(),
        ReportingLspProcessManager(),
        compact_continuation=True,
        coding_metrics_recorder=metrics.append,
    ).run(_task_context(workspace), workspace, {}, run_context=_run_context())

    assert result.execution_receipt.source_file.path == "analysis/a.py"
    assert metrics[0]["compactContinuationApplied"] is True
    assert metrics[0]["compactionTriggered"] is False
    assert metrics[0]["compactionWindowId"] == 0
    assert metrics[0]["compactionBeforeTokens"] == "unknown"
    assert metrics[0]["compactionAfterTokens"] == "unknown"
    assert metrics[0]["retainedCallCount"] == 0
    assert metrics[0]["truncatedCallCount"] == 0
    assert len(client.requests) == 3
    assert '"compaction"' not in _user_message_text(client.requests[-1])


@pytest.mark.anyio
async def test_compaction_reconnect_disabled_by_default(
    workspace, low_compaction_threshold  # noqa: F811
):
    first = _batch_response(
        _custom_response("write_script", SOURCE, 1),
        _function_response(2, "run_script", {}),
    )
    client = _ResponsesClient([
        _with_usage(first, 150),
        _with_usage(_message_response("已完成"), 150),
        _with_usage(_function_response(3, "submit_script", {}), 10),
    ])
    agents = []
    metrics = []
    result = await ReportingCodeGenerationRunner(
        _make_agent_factory(client, "run-compaction-default", agents),
        ToolkitRuntime(),
        ReportingLspProcessManager(),
        coding_metrics_recorder=metrics.append,
    ).run(_task_context(workspace), workspace, {}, run_context=_run_context())

    assert result.execution_receipt.source_file.path == "analysis/a.py"
    # 默认路径不变：即使请求输入超阈值，也不做压缩重连，仍走原生回放。
    assert metrics[0]["compactContinuationEnabled"] is False
    assert metrics[0]["compactionTriggered"] is False
    assert metrics[0]["compactionWindowId"] == 0
    assert metrics[0]["compactionBeforeTokens"] == "unknown"
    assert metrics[0]["compactionAfterTokens"] == "unknown"
    assert metrics[0]["retainedCallCount"] == 0
    assert metrics[0]["truncatedCallCount"] == 0
    last_input = client.requests[-1]["input"]
    assert any(
        item.get("type") in {"function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output"}
        for item in last_input
    )


@pytest.mark.anyio
async def test_failure_without_compaction_keeps_unknown_usage(workspace):  # noqa: F811
    first = _batch_response(
        _custom_response("write_script", SOURCE, 1),
        _function_response(2, "run_script", {}),
    )
    client = _ResponsesClient([
        first,
        _message_response("已完成"),
        _message_response("还是没有提交"),
    ])
    agents = []
    with pytest.raises(ReportingError, match="report_code_generation_no_submission") as caught:
        await ReportingCodeGenerationRunner(
            _make_agent_factory(client, "run-compaction-unknown", agents),
            ToolkitRuntime(),
            ReportingLspProcessManager(),
            compact_continuation=True,
        ).run(_task_context(workspace), workspace, {}, run_context=_run_context())

    details = caught.value.details
    assert details["compactionTriggered"] is False
    assert details["compactionWindowId"] == 0
    assert details["compactionBeforeTokens"] == "unknown"
    assert details["compactionAfterTokens"] == "unknown"
    assert details["retainedCallCount"] == 0
    assert details["truncatedCallCount"] == 0


@pytest.mark.anyio
async def test_compaction_reconnect_respects_request_budget_before_reconnect(
    workspace, low_compaction_threshold, monkeypatch  # noqa: F811
):
    # 请求预算在压缩重连前耗尽时必须干净收尾（no_submission + 验收字段），
    # 不能等到 arun 内部才抛出 report_code_model_request_limit。
    # tool_limit=5 → request_limit = max(4, 5+1) = 6：窗口 0 消耗 5 次请求（4 工具），
    # 窗口 1 后请求数恰好到达 6，重连前预算检查必须命中。
    monkeypatch.setattr(code_generation, "ANALYSIS_TOOL_CALL_LIMIT", 5)
    client = _ResponsesClient([
        _with_usage(_custom_response("write_script", SOURCE, 1), 150),
        _with_usage(_function_response(2, "run_script", {}), 150),
        _with_usage(_function_response(3, "read_script", {}), 150),
        _with_usage(_function_response(4, "run_script", {}), 150),
        _with_usage(_message_response("还未提交"), 150),
        _with_usage(_message_response("继续说明"), 150),
        _with_usage(_message_response("这个响应不应被消费"), 150),
    ])
    agents = []
    runtime = ToolkitRuntime()
    runtime.next_cell = SimpleNamespace(status="error", stdout="", stderr="boom", traceback=None)

    async def forbidden_continue(*args, **kwargs):
        pytest.fail("压缩重连不得调用 acontinue_run 回放完整旧历史")

    monkeypatch.setattr(Agent, "acontinue_run", forbidden_continue)
    metrics = []
    with pytest.raises(ReportingError, match="report_code_generation_no_submission") as caught:
        await ReportingCodeGenerationRunner(
            _make_agent_factory(client, "run-compaction-budget", agents),
            runtime,
            ReportingLspProcessManager(),
            compact_continuation=True,
            coding_metrics_recorder=metrics.append,
        ).run(_task_context(workspace), workspace, {}, run_context=_run_context())

    # 窗口 1 后请求数达到 request_limit=6，重连前干净收尾；第 7 个响应未被消费。
    assert len(client.requests) == 6
    assert metrics[0]["compactionTriggered"] is True
    assert metrics[0]["compactionWindowId"] == 1
    details = caught.value.details
    assert details["compactionTriggered"] is True
    assert details["compactionWindowId"] == 1
    assert details["compactionBeforeTokens"] == 150
    assert details["retainedCallCount"] == 4
    assert client.pending


def test_observed_truncated_calls_sums_across_entries():
    assert code_generation._observed_truncated_calls([
        {"truncated_calls": 2},
        {"truncated_calls": 0},
        {"truncatedCallCount": 3},
        {"truncated_calls": "unknown"},
        None,
        "not-a-mapping",
    ]) == 5
