from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent as AgnoAgent
from agno.metrics import RunMetrics
from agno.models.openai import OpenAIChat

from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    _run_context,
    _task_context,
    workspace,  # noqa: F401
)
from smart_reporting.reporting.workflow.execution import _TaskModelMetricsSettlement
from smart_reporting.reporting.workflow.runtime.code_generation import (
    ReportingCodeGenerationRunner,
)


def test_nonstream_run_output_metrics_are_recorded_with_real_request_count():
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )
    output = SimpleNamespace(
        metrics=RunMetrics(
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
            reasoning_tokens=10,
            cache_read_tokens=20,
            time_to_first_token=0.25,
        )
    )

    settlement.record_run_output(output, request_count=3)

    assert settlement.snapshot() == {
        "requestCount": 3,
        "inputTokens": 120,
        "outputTokens": 30,
        "totalTokens": 150,
        "reasoningTokens": 10,
        "cacheReadTokens": 20,
        "cacheWriteTokens": 0,
        "timeToFirstTokenSeconds": 0.25,
    }


def test_nonstream_request_count_is_kept_when_provider_omits_usage():
    settlement = _TaskModelMetricsSettlement(
        task_id="task-1", phase_attempt=1, agno_run_id="run-1"
    )

    settlement.record_run_output(SimpleNamespace(metrics=None), request_count=2)

    assert settlement.snapshot()["requestCount"] == 2


@pytest.mark.anyio
async def test_runner_records_metrics_before_no_submission(workspace):  # noqa: F811
    recorded: list[tuple[object, int]] = []
    output = SimpleNamespace(metrics=RunMetrics(total_tokens=42))

    class Model:
        def configure_code_run(self, _tools, *, max_model_requests, delivery_reserve=None, redundant_call_check=None):
            # 30 次工具调用后仍需允许一次模型终止响应。
            assert max_model_requests == 31

        def code_run_request_count(self):
            return 2

    class Agent:
        model = Model()
        tool_call_limit = 20

        async def arun(self, _prompt, **_kwargs):
            return output

    class Runtime:
        async def shutdown(self, _session_id):
            return None

    runner = ReportingCodeGenerationRunner(
        lambda _tools: Agent(),
        Runtime(),
        ReportingLspProcessManager(),
        model_metrics_recorder=lambda value, count: recorded.append((value, count)),
    )

    with pytest.raises(ReportingError) as caught:
        await runner.run(
            _task_context(workspace), workspace, {}, run_context=_run_context("task-1")
        )

    assert caught.value.code == "report_code_generation_no_submission"
    assert recorded == [(output, 2)]


@pytest.mark.anyio
async def test_runner_rejects_agno_model_without_code_protocol(workspace):  # noqa: F811
    agent = AgnoAgent(
        model=OpenAIChat(id="test", api_key="test", base_url="http://localhost")
    )
    agent.arun = AsyncMock()

    class Runtime:
        async def shutdown(self, _session_id):
            return None

    runner = ReportingCodeGenerationRunner(
        lambda _tools: agent, Runtime(), ReportingLspProcessManager()
    )

    with pytest.raises(ReportingError) as caught:
        await runner.run(
            _task_context(workspace), workspace, {}, run_context=_run_context("task-1")
        )

    assert caught.value.code == "report_code_model_protocol_missing"
    agent.arun.assert_not_awaited()


@pytest.mark.anyio
async def test_runner_records_request_count_when_agent_raises(workspace):  # noqa: F811
    recorded: list[tuple[object, int]] = []

    class Model:
        def configure_code_run(self, _tools, *, max_model_requests, delivery_reserve=None, redundant_call_check=None):
            assert max_model_requests == 31

        def code_run_request_count(self):
            return 2

    class Agent:
        model = Model()
        tool_call_limit = 20

        async def arun(self, _prompt, **_kwargs):
            raise RuntimeError("provider failed")

    class Runtime:
        async def shutdown(self, _session_id):
            return None

    runner = ReportingCodeGenerationRunner(
        lambda _tools: Agent(),
        Runtime(),
        ReportingLspProcessManager(),
        model_metrics_recorder=lambda value, count: recorded.append((value, count)),
    )

    with pytest.raises(ReportingError) as caught:
        await runner.run(
            _task_context(workspace), workspace, {}, run_context=_run_context("task-1")
        )

    assert caught.value.code == "report_code_generation_agent_failed"
    assert recorded == [(None, 2)]
