"""真实 Coding runner 的阶段观测不能被 metrics 消费后从混合路由消失。"""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_standard_chart_routing import setup
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime import code_generation, standard_chart_routing

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize('anyio_backend', ['asyncio'])]


@pytest.mark.parametrize('terminal', ['succeeded', 'failed', 'cancelled', 'receipt_changed'])
async def test_real_coding_runner_preserves_drained_observation_on_every_terminal_path(tmp_path, monkeypatch, terminal):
    _plan, _inputs, context = setup(tmp_path, ['custom'])
    receipt = ExecutionReceipt(runId='coding-run',
        sourceFile=FileIdentity(path=context.script_path, size=1, sha256='a' * 64),
        outputFiles=(FileIdentity(path='chart-0.png', size=1, sha256='b' * 64),))
    spans = {'script': [7, 11], 'bootstrap': [2], 'shutdown': [1]}
    drained, metrics = [], []

    class Toolkit:
        tool_functions = ()
        submitted_receipt = receipt
        visual_review_duration_ms = 5
        completed_tool_calls = 3
        terminal_failure = None

        def __init__(self, *args, **kwargs):
            pass

        async def refresh_delivery_state(self):
            pass

        def delivery_state(self):
            return {'nextTools': []}

        async def require_current_receipt(self, _receipt):
            if terminal == 'receipt_changed':
                raise ReportingError('receipt_changed', '当前图片已变化。')

    class Agent:
        model = SimpleNamespace(code_run_request_count=lambda: 1,
            code_run_request_metrics=lambda: [{'status': 'succeeded', 'durationMs': 13}])

        async def arun(self, *args, **kwargs):
            if terminal == 'failed':
                raise ReportingError('coding_failed', '绘图失败。')
            if terminal == 'cancelled':
                raise asyncio.CancelledError()
            return SimpleNamespace(metrics=None)

    @asynccontextmanager
    async def bind(*args):
        yield SimpleNamespace(visual_inspection_receipts={}, visual_repair_diagnostic=None)

    async def exists(*args):
        return True

    async def shutdown(*args):
        pass

    def drain(session):
        drained.append(session)
        return spans

    monkeypatch.setattr(code_generation, 'ReportingCodeModeToolkit', Toolkit)
    runner = code_generation.ReportingCodeGenerationRunner(lambda tools: Agent(),
        SimpleNamespace(shutdown=shutdown, drain_execution_spans=drain), None,
        registry=SimpleNamespace(bind=bind), vision_reviewer=object(), coding_metrics_recorder=metrics.append)
    operation = runner.run(context, SimpleNamespace(apath_exists=exists), {}, run_context=object())
    if terminal == 'succeeded':
        result = await operation
        assert result.execution_spans == spans
        observation = result.execution_attempts[0]
    else:
        with pytest.raises(asyncio.CancelledError if terminal == 'cancelled' else ReportingError) as caught:
            await operation
        observation = caught.value.standard_execution
    assert len(drained) == 1
    assert metrics[0]['executionSpans']['script'] == [7, 11]
    assert observation['executionSpans'] == spans
    assert observation['stageTimings']['script'] == 18
    assert observation['stageTimings']['inspect'] == 5
    assert observation['stageTimings']['model_wait'] == 13
    assert observation['status'] == ('failed' if terminal == 'receipt_changed' else terminal)
    assert observation['modelRequests'] == 1
    assert observation['toolCalls'] == 3


def test_route_span_aggregation_keeps_unknown_as_unknown_instead_of_characters(anyio_backend):
    observation = standard_chart_routing._route_observation({
        'initialCompileMs': 0, 'componentCompileMs': 0,
        'executionAttempts': [
            {'executionSpans': {'script': [7], 'bootstrap': 'unknown'}},
            {'executionSpans': {'script': 'unknown', 'bootstrap': [2]}},
        ],
    }, 100, 'succeeded')
    assert observation['executionSpans'] == {'script': 'unknown', 'bootstrap': 'unknown'}


def test_whole_unknown_attempt_prevents_partial_spans_being_reported_as_complete(anyio_backend):
    attempts = [{'executionSpans': {'script': [7]}}, {'executionSpans': 'unknown'}]
    observation = standard_chart_routing._route_observation({
        'initialCompileMs': 0, 'componentCompileMs': 0, 'executionAttempts': attempts,
    }, 100, 'succeeded')
    assert observation['executionSpans'] == 'unknown'
    assert observation['executionAttempts'][0]['executionSpans']['script'] == [7]
