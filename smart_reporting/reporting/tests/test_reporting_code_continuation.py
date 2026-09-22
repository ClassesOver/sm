"""使用真实 Agno Agent 和原生继续接口验证有界补交付。"""

import asyncio
import json

import pytest
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

from smart_reporting.reporting.agent import create_reporting_code_agent_factory
from smart_reporting.reporting.code_agent.budget import CodeBudget
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_code_agent_trajectories import _ResponsesClient
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    ToolkitRuntime,
    _batch_response,
    _custom_response,
    _failed_cell,
    _function_response,
    _message_response,
    _run_context,
    _task_context,
    workspace,  # noqa: F401
)
from smart_reporting.reporting.workflow.runtime import code_generation
from smart_reporting.reporting.workflow.runtime.code_generation import ReportingCodeGenerationRunner


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_seed_runs_before_provider_without_fabricated_tool_messages(workspace, outcome):  # noqa: F811
    await workspace.awrite_text("task-1", "analysis/a.py", SOURCE)
    client = _ResponsesClient(
        [_function_response(1, "submit_script", {})] if outcome == "success"
        else [_message_response("未修复"), _message_response("未修复")]
    )
    factory = create_reporting_code_agent_factory(model=OpenAIChat(id="test", api_key="test"), name="seed-test")
    agents = []
    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        agents.append(agent)
        return agent

    class SeedRuntime(ToolkitRuntime):
        async def execute_script_process(self, *args, **kwargs):
            if outcome == "cancelled":
                raise asyncio.CancelledError()
            return await super().execute_script_process(*args, **kwargs)

    runtime = SeedRuntime()
    if outcome == "failure":
        runtime.next_cell = _failed_cell('  File "analysis/a.py", line 1\nValueError: seed')
    metrics, artifacts = [], []
    runner = ReportingCodeGenerationRunner(
        make_agent, runtime, ReportingLspProcessManager(),
        coding_metrics_recorder=metrics.append, failure_artifact_recorder=artifacts.append,
    )
    if outcome == "success":
        result = await runner.run(_task_context(workspace), workspace, {}, run_context=_run_context())
        assert result.execution_receipt.source_file.path == "analysis/a.py"
        assert metrics[0]["firstRunSuccess"] is True
        assert len(client.requests) == 1
        assert agents[0].tool_call_limit == 29
    else:
        with pytest.raises(asyncio.CancelledError if outcome == "cancelled" else ReportingError):
            await runner.run(_task_context(workspace), workspace, {}, run_context=_run_context())
        assert metrics[0]["firstRunSuccess"] == ("unknown" if outcome == "cancelled" else False)
    assert runtime.shutdowns == ["code-task-1"]
    if outcome == "cancelled":
        assert client.requests == []
    else:
        first = client.requests[0]
        assert {tool["name"] for tool in first["tools"]} == (
            {"submit_script"} if outcome == "success" else {"read_script", "edit_script", "run_script"}
        )
        assert not any(item.get("type") in {"function_call", "function_call_output"} for item in first["input"])
        assert metrics[0]["toolCounts"]["run_script"] == 1
    if outcome == "failure":
        assert artifacts[0]["source"] == SOURCE
        assert "sourceSha256" in json.dumps(first["input"])
        assert "allowedEditRegion" in json.dumps(first["input"])
        assert agents[0].tool_call_limit == 29


@pytest.mark.anyio
async def test_seed_execution_counts_toward_exhausted_task_budget(workspace, monkeypatch):  # noqa: F811
    monkeypatch.setattr(code_generation, "ANALYSIS_TOOL_CALL_LIMIT", 3)
    await workspace.awrite_text("task-1", "analysis/a.py", SOURCE)
    client = _ResponsesClient([
        _batch_response(_function_response(1, "read_script", {}), _function_response(2, "read_script", {})),
        _message_response("未提交"),
    ])
    factory = create_reporting_code_agent_factory(model=OpenAIChat(id="test", api_key="test"), name="seed-budget")
    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        return agent
    runtime = ToolkitRuntime()
    runtime.next_cell = _failed_cell("ValueError: seed")
    with pytest.raises(ReportingError) as caught:
        await ReportingCodeGenerationRunner(make_agent, runtime, ReportingLspProcessManager()).run(
            _task_context(workspace), workspace, {}, run_context=_run_context())
    assert caught.value.details["terminationReason"] == "tool_call_limit_reached"
    assert caught.value.details["toolResultCount"] == 3
    assert caught.value.details["providerToolResultCount"] == 2
    assert caught.value.details["hostToolResultCount"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("ending", ["submit", "text_again", "already_submitted"])
async def test_native_continuation_keeps_execution_and_request_budget(workspace, ending):  # noqa: F811
    first = _batch_response(_custom_response("write_script", SOURCE, 1),
                            _function_response(2, "run_script", {}))
    responses = [first]
    if ending != "already_submitted":
        responses.append(_message_response("已完成"))
    responses.append(_function_response(3, "submit_script", {}) if ending != "text_again"
                     else _message_response("还是没有提交"))
    client = _ResponsesClient(responses)
    factory = create_reporting_code_agent_factory(model=OpenAIChat(id="test", api_key="test"), name="continue-test")
    agents = []
    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        agents.append(agent)
        return agent
    class CountingRuntime(ToolkitRuntime):
        runs = 0

        async def execute_script_process(self, *args, **kwargs):
            self.runs += 1
            return await super().execute_script_process(*args, **kwargs)

    runtime = CountingRuntime()
    metrics = []
    runner = ReportingCodeGenerationRunner(make_agent, runtime, ReportingLspProcessManager(),
                                         model_metrics_recorder=lambda out, count: metrics.append((out, count)))
    if ending == "text_again":
        with pytest.raises(ReportingError, match="report_code_generation_no_submission"):
            await runner.run(_task_context(workspace), workspace, {}, run_context=_run_context())
    else:
        result = await runner.run(_task_context(workspace), workspace, {}, run_context=_run_context())
        assert result.execution_receipt.source_file.path == "analysis/a.py"
    assert len(client.requests) == (2 if ending == "already_submitted" else 3)
    assert not client.pending
    assert sum(count for _, count in metrics) == len(client.requests)
    assert agents[0].model.code_run_request_count() == len(client.requests)
    if ending != "already_submitted":
        assert agents[0].tool_call_limit == 28
        replay = client.requests[-1]["input"]
        assert sum(item.get("type") == "custom_tool_call" for item in replay) == 1
        assert sum(item.get("type") == "function_call_output" for item in replay) == 1
    assert runtime.shutdowns == ["code-task-1"]
    assert runtime.runs == 1


@pytest.mark.anyio
async def test_compact_continuation_rebuilds_agent_without_provider_history(workspace, monkeypatch):  # noqa: F811
    first = _batch_response(
        _custom_response("write_script", SOURCE, 1),
        _function_response(2, "run_script", {}),
    )
    client = _ResponsesClient([
        first,
        _message_response("已完成"),
        _function_response(3, "submit_script", {}),
    ])
    factory = create_reporting_code_agent_factory(
        model=OpenAIChat(id="test", api_key="test"), name="compact-continue-test"
    )
    agents = []

    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        agents.append(agent)
        return agent

    from agno.agent import Agent

    async def forbidden_continue(*args, **kwargs):
        pytest.fail("compact continuation 不得复用 Agno provider history")

    monkeypatch.setattr(Agent, "acontinue_run", forbidden_continue)
    result = await ReportingCodeGenerationRunner(
        make_agent,
        ToolkitRuntime(),
        ReportingLspProcessManager(),
        compact_continuation=True,
    ).run(_task_context(workspace), workspace, {}, run_context=_run_context())

    assert result.execution_receipt.source_file.path == "analysis/a.py"
    assert len(agents) == 2
    assert len(client.requests) == 3
    assert not any(
        item.get("type") == "function_call_output" for item in client.requests[-1]["input"]
    )


@pytest.mark.parametrize("requests,tools", [(4, 0), (0, 3)])
def test_continuation_cannot_claim_exhausted_budget(requests, tools):
    budget = CodeBudget(request_limit=4, reserve=1, requests=requests, tool_calls=tools)
    assert budget.claim_continuation(3) is None


def test_continuation_claim_is_one_time_and_preserves_counts():
    budget = CodeBudget(request_limit=4, reserve=1, requests=2, tool_calls=2)
    assert budget.claim_continuation(3) == 1
    assert budget.claim_continuation(3) is None
    assert budget.requests == 2
    assert budget.tool_calls == 2


@pytest.mark.anyio
@pytest.mark.parametrize("status", [RunStatus.cancelled, RunStatus.paused, RunStatus.error])
async def test_unfinished_or_failed_runs_are_not_continued(workspace, status, monkeypatch):  # noqa: F811
    factory = create_reporting_code_agent_factory(model=OpenAIChat(id="test", api_key="test"), name="stop-test")
    async def arun(self, *args, **kwargs):
        return RunOutput(status=status)
    async def forbidden_continue(*args, **kwargs):
        pytest.fail("非正常结束的 run 不得继续")
    from agno.agent import Agent
    monkeypatch.setattr(Agent, "arun", arun)
    monkeypatch.setattr(Agent, "acontinue_run", forbidden_continue)
    with pytest.raises(ReportingError, match="report_code_generation_no_submission"):
        await ReportingCodeGenerationRunner(factory, ToolkitRuntime(), ReportingLspProcessManager()).run(
            _task_context(workspace), workspace, {}, run_context=_run_context())


@pytest.mark.anyio
async def test_continuation_batch_cannot_exceed_original_tool_limit(workspace, monkeypatch):  # noqa: F811
    monkeypatch.setattr(code_generation, "ANALYSIS_TOOL_CALL_LIMIT", 3)
    client = _ResponsesClient([
        _batch_response(_custom_response("write_script", SOURCE, 1), _function_response(2, "run_script", {})),
        _message_response("完成"),
        _batch_response(_function_response(3, "read_script", {}), _function_response(4, "read_script", {})),
        _message_response("工具额度耗尽"),
    ])
    factory = create_reporting_code_agent_factory(model=OpenAIChat(id="test", api_key="test"), name="limit-test")
    agents = []
    def make_agent(tools):
        agent = factory(tools)
        agent.model.async_client = client
        agents.append(agent)
        return agent
    runtime = ToolkitRuntime()
    runtime.next_cell = _failed_cell("ValueError: repair required")
    with pytest.raises(ReportingError, match="report_code_generation_no_submission") as caught:
        await ReportingCodeGenerationRunner(make_agent, runtime, ReportingLspProcessManager()).run(
            _task_context(workspace), workspace, {}, run_context=_run_context())
    assert agents[0].model.code_run_tool_count() == 3
    assert caught.value.details["toolCallLimit"] == 3
    assert caught.value.details["terminationReason"] == "tool_call_limit_reached"
    assert len(client.requests) == 4
