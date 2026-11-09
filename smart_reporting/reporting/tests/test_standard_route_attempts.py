"""混合路由保留全尝试成本；预检复用不省略证明核验。"""
import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_standard_chart_routing import setup
from smart_reporting.reporting.workflow.runtime import standard_chart_routing as routing

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize('anyio_backend', ['asyncio'])]


@pytest.mark.parametrize('terminal', [None, 'failure', 'cancelled'])
async def test_mixed_route_accumulates_children_and_final_attempts(tmp_path, monkeypatch, terminal):
    plan, inputs, context = setup(tmp_path, ['line', 'custom'])
    clock = [0.0]
    calls = []
    original = routing.standard_visualization_preflight

    def preflight(*args):
        clock[0] += .002
        return original(*args)

    async def execute(ctx, source, phase):
        clock[0] += .010
        calls.append(ctx.script_path)
        observation = {'status': 'succeeded', 'stageTimings': {'draw': 7, 'total': 10},
                       'executionSpans': {'scriptProcess': [7]}}
        if ctx.script_path == context.script_path and terminal:
            error = asyncio.CancelledError() if terminal == 'cancelled' else ReportingError('draw_failed', '失败')
            error.standard_execution = {**observation, 'status': 'cancelled' if terminal == 'cancelled' else 'failed'}
            raise error
        (tmp_path / ctx.script_path).write_text(source)
        identity = SimpleNamespace(path=ctx.script_path, sha256=hashlib.sha256(source.encode()).hexdigest())
        return SimpleNamespace(script_file=identity, execution_receipt=None,
                               stage_timings=observation['stageTimings'], execution_spans=observation['executionSpans'],
                               execution_attempts=(observation,))

    async def standard(ctx, workspace, source, facts):
        return await execute(ctx, source, 'standard')

    async def coding(ctx, workspace, facts, **kwargs):
        return await execute(ctx, 'pass\n', 'coding')

    async def read(task_id, path):
        return (tmp_path / path).read_bytes(), 'text/x-python'

    monkeypatch.setattr(routing, 'standard_visualization_preflight', preflight)
    monkeypatch.setattr(routing, 'perf_counter', lambda: clock[0])
    operation = routing.run_standard_chart_routes(SimpleNamespace(run_standard_visualization=standard, run=coding),
        context, SimpleNamespace(afile_bytes=read), plan, inputs, {}, object())
    if terminal:
        with pytest.raises(asyncio.CancelledError if terminal == 'cancelled' else ReportingError) as caught:
            await operation
        attempts = caught.value.standard_execution_attempts
        timings = caught.value.standard_route_execution['stageTimings']
        assert len(caught.value.standard_chart_routes) == 2
    else:
        result = await operation
        attempts, timings = result.execution_attempts, result.stage_timings
    assert len(calls) == 3
    assert [item['routePhase'] for item in attempts] == ['component_standard', 'component_coding', 'final']
    assert timings['draw'] == 21
    assert timings['total'] == 30
    assert sum(item['stageTimings'].get('draw', 0) for item in attempts) == 21
    assert attempts[-1]['status'] == ('succeeded' if terminal is None else 'cancelled' if terminal == 'cancelled' else 'failed')


async def test_supported_single_reuses_initial_preflight_but_retains_proof_check(tmp_path, monkeypatch):
    plan, inputs, context = setup(tmp_path, ['line'])
    compiled = []
    original = routing.standard_visualization_preflight

    def preflight(*args):
        compiled.append(args)
        return original(*args)

    async def standard(*args, **kwargs):
        return SimpleNamespace(script_file=None, execution_receipt=None)

    monkeypatch.setattr(routing, 'standard_visualization_preflight', preflight)
    await routing.run_standard_chart_routes(SimpleNamespace(run_standard_visualization=standard),
        context, object(), plan, inputs, {}, object())
    # create_standard_render_proofs仍独立重编译；这里只统计路由预检。
    assert len(compiled) == 1
