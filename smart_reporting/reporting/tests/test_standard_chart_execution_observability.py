"""标准运行计时须包含失败/取消阶段，不把重试成本当成功末次成本。"""
# ruff: noqa: F811

import asyncio
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    _visualization_task_context,
    workspace,  # noqa: F401
)
from smart_reporting.reporting.tests.test_reporting_phase_models import _chart
from smart_reporting.reporting.tests.test_standard_chart_direct_execution import runner_for
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime import code_generation
from smart_reporting.reporting.workflow.runtime import standard_chart_routing as routing
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationPlanDraft

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("draw failed"),
        asyncio.CancelledError(),
        ReportingError("draw_failed", "失败", details={"original": True}),
        ReportingError("draw_failed", "失败", details=["original detail"]),
        None,
    ],
)
@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_standard_stage_observations_include_failed_and_cancelled_draws(
    workspace, monkeypatch, failure, cleanup_failure
):  # noqa: F811
    clock = [0.0]
    if isinstance(failure, ReportingError):
        failure = ReportingError(
            failure.code,
            failure.message,
            details=(
                ["original detail"] if isinstance(failure.details, list) else {"original": True}
            ),
        )
    context = _visualization_task_context(workspace)
    source = FileIdentity(path=context.script_path, size=1, sha256="a" * 64)
    output = FileIdentity(path="charts/chart.png", size=1, sha256="b" * 64)
    receipt = ExecutionReceipt(runId="attempt", sourceFile=source, outputFiles=(output,))
    captured = []
    original_details = failure.details if isinstance(failure, ReportingError) else None

    class Toolkit:
        def __init__(self, binding, *args, **kwargs):
            self.binding = binding
            binding.execution_receipt = receipt

        async def refresh_delivery_state(self):
            pass

        async def write_script(self, source):
            clock[0] += 0.002
            return {"ok": True}

        async def run_script(self):
            clock[0] += 0.017
            if failure is not None:
                raise failure
            return {"ok": True}

        async def inspect_standard_images(self):
            clock[0] += 0.005
            return {"ok": True}

        async def submit_script(self):
            clock[0] += 0.003
            return {"ok": True}

        async def require_current_receipt(self, receipt):
            pass

    async def shutdown(session_id):
        clock[0] += 0.004
        if cleanup_failure:
            raise RuntimeError("shutdown failed")

    runtime = SimpleNamespace(
        shutdown=shutdown, drain_execution_spans=lambda _: {"scriptProcess": [17]}
    )
    monkeypatch.setattr(code_generation, "ReportingCodeModeToolkit", Toolkit)
    monkeypatch.setattr(code_generation, "perf_counter", lambda: clock[0])
    sink = code_generation.logger.add(
        lambda message: captured.append(message.record), format="{message}"
    )
    try:
        if failure is None:
            result = await runner_for(runtime).run_standard_visualization(
                context, workspace, "trusted", {}, deterministic=True
            )
            observation = result.execution_attempts[0]
        else:
            with pytest.raises(type(failure)) as caught:
                await runner_for(runtime).run_standard_visualization(
                    context, workspace, "trusted", {}, deterministic=True
                )
            assert caught.value is failure
            observation = caught.value.standard_execution
            if isinstance(failure, ReportingError):
                if isinstance(original_details, dict):
                    assert caught.value.details["original"] is True
                else:
                    assert caught.value.details["originalDetails"] is original_details
                assert caught.value.details["standardExecution"] == observation
    finally:
        code_generation.logger.remove(sink)
    assert observation["stageTimings"]["draw"] == 17
    assert observation["executionSpans"] == {"scriptProcess": [17]}
    expected_status = (
        "succeeded"
        if failure is None
        else "cancelled"
        if isinstance(failure, asyncio.CancelledError)
        else "failed"
    )
    assert observation["status"] == expected_status
    assert observation["stageStatuses"]["draw"] == expected_status
    assert observation["stageStatuses"]["cleanup"] == (
        "warning" if cleanup_failure else "succeeded"
    )
    if failure is not None:
        assert observation["stageTimings"]["total"] == 23
        assert observation["failedStage"] == "draw"
        assert "inspect" not in observation["stageStatuses"]
    assert any(
        record["extra"].get("standard_execution", {}).get("status") == expected_status
        for record in captured
    )


@pytest.mark.parametrize(
    "final_failure", [None, RuntimeError("second draw failed"), asyncio.CancelledError()]
)
async def test_layout_retry_records_failed_attempt_cost_before_success(monkeypatch, final_failure):
    clock = [0.0]
    calls = []
    plan = VisualizationPlanDraft(charts=(_chart("chart.png"),))

    def preflight(*args):
        clock[0] += 0.003
        return SimpleNamespace(source="trusted", diagnostic=None)

    async def run(*args, **kwargs):
        calls.append(kwargs)
        clock[0] += 0.012
        observation = {
            "status": "failed" if len(calls) == 1 else "succeeded",
            "failedStage": "draw" if len(calls) == 1 else None,
            "stageTimings": {"draw": 7, "total": 12},
            "stageStatuses": {"draw": "failed" if len(calls) == 1 else "succeeded"},
            "executionSpans": {"scriptProcess": [7]},
        }
        if len(calls) == 1:
            error = ReportingError(
                "layout",
                "布局失败",
                details={"standardDiagnostic": {"code": "standard_chart_layout_unresolved"}},
            )
            error.standard_execution = observation
            raise error
        if final_failure is not None:
            observation["status"] = (
                "cancelled" if isinstance(final_failure, asyncio.CancelledError) else "failed"
            )
            final_failure.standard_execution = observation
            raise final_failure
        return SimpleNamespace(
            execution_attempts=(observation,),
            stage_timings=observation["stageTimings"],
            execution_spans=observation["executionSpans"],
        )

    monkeypatch.setattr(routing, "standard_visualization_preflight", preflight)
    monkeypatch.setattr(routing, "perf_counter", lambda: clock[0])
    if final_failure is not None:
        with pytest.raises(type(final_failure)) as caught:
            await routing._run_standard_with_layout_retry(
                SimpleNamespace(run_standard_visualization=run),
                object(),
                object(),
                plan,
                object(),
                {},
                deterministic=True,
            )
        assert caught.value is final_failure
        attempts = final_failure.standard_execution_attempts
        assert len(attempts) == 2
        assert [item["durationMs"] for item in attempts] == [15, 15]
        assert attempts[0]["status"] == "failed"
        assert attempts[1]["status"] == (
            "cancelled" if isinstance(final_failure, asyncio.CancelledError) else "failed"
        )
        assert final_failure.standard_route_total_ms == 30
        return
    result = await routing._run_standard_with_layout_retry(
        SimpleNamespace(run_standard_visualization=run),
        object(),
        object(),
        plan,
        object(),
        {},
        deterministic=True,
    )
    assert len(result.execution_attempts) == 2
    assert [item["status"] for item in result.execution_attempts] == ["failed", "succeeded"]
    assert [item["durationMs"] for item in result.execution_attempts] == [15, 15]
    assert result.stage_timings == {"draw": 14, "total": 24, "compile": 6}
    assert result.execution_spans == {"scriptProcess": [7, 7]}
    assert result.route_total_ms == 30
    assert calls == [{"deterministic": True}, {"deterministic": True}]


@pytest.mark.parametrize("deterministic,chart_count", [(True, 1), (True, 2), (False, 1)])
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError, ReportingError])
async def test_failed_outer_route_keeps_initial_compile_cost_and_original_diagnostic(
    monkeypatch, chart_count, failure_type, deterministic
):
    clock = [0.0]
    plan = VisualizationPlanDraft(
        charts=tuple(
            _chart(f"chart-{index}.png").model_copy(update={"chart_id": f"chart-{index}"})
            for index in range(chart_count)
        )
    )
    original_details = ["original route detail"]
    failure = (
        failure_type("draw_failed", "primary", details=original_details)
        if failure_type is ReportingError
        else failure_type()
    )

    def preflight(*args):
        clock[0] += 0.003
        return SimpleNamespace(source="trusted", diagnostic=None, warnings=())

    async def run(*args, **kwargs):
        clock[0] += 0.012
        failure.standard_execution = {
            "status": "cancelled" if failure_type is asyncio.CancelledError else "failed",
            "stageTimings": {"draw": 7, "total": 12},
            "executionSpans": {"scriptProcess": [7]},
        }
        raise failure

    monkeypatch.setattr(routing, "standard_visualization_preflight", preflight)
    monkeypatch.setattr(routing, "perf_counter", lambda: clock[0])
    with pytest.raises(failure_type) as caught:
        await routing.run_standard_chart_routes(
            SimpleNamespace(run_standard_visualization=run),
            object(),
            object(),
            plan,
            object(),
            {},
            object(),
            deterministic=deterministic,
        )
    assert caught.value is failure
    assert failure.standard_route_total_ms == (18 if chart_count == 1 else 15)
    assert failure.standard_route_execution["stageTimings"]["compile"] == (
        6 if chart_count == 1 else 3
    )
    assert failure.standard_route_execution["initialCompileMs"] == 3
    assert failure.standard_route_execution["status"] == (
        "cancelled" if failure_type is asyncio.CancelledError else "failed"
    )
    assert failure.standard_route_execution["executionSpans"] == {"scriptProcess": [7]}
    if failure_type is ReportingError:
        assert failure.details["originalDetails"] is original_details
        assert failure.details["standardRouteTotalMs"] == (18 if chart_count == 1 else 15)


@pytest.mark.parametrize("deterministic", [True, False])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_outer_route_failed_retry_includes_initial_compile_without_fake_attempt(
    monkeypatch, deterministic, cancelled
):
    clock = [0.0]
    calls = []
    plan = VisualizationPlanDraft(charts=(_chart("chart.png"),))
    failure = asyncio.CancelledError() if cancelled else RuntimeError("final draw failed")

    def preflight(*args):
        clock[0] += 0.003
        return SimpleNamespace(source="trusted", diagnostic=None, warnings=())

    async def run(*args, **kwargs):
        calls.append(kwargs)
        clock[0] += 0.012
        error = (
            ReportingError(
                "layout",
                "重试",
                details={"standardDiagnostic": {"code": "standard_chart_layout_unresolved"}},
            )
            if len(calls) == 1
            else failure
        )
        error.standard_execution = {
            "status": "cancelled" if isinstance(error, asyncio.CancelledError) else "failed",
            "stageTimings": {"draw": 7, "total": 12},
            "executionSpans": {"scriptProcess": [7]},
        }
        raise error

    monkeypatch.setattr(routing, "standard_visualization_preflight", preflight)
    monkeypatch.setattr(routing, "perf_counter", lambda: clock[0])
    with pytest.raises(type(failure)) as caught:
        await routing.run_standard_chart_routes(
            SimpleNamespace(run_standard_visualization=run),
            object(),
            object(),
            plan,
            object(),
            {},
            object(),
            deterministic=deterministic,
        )
    assert caught.value is failure
    assert failure.standard_route_total_ms == 33
    assert failure.standard_route_execution["stageTimings"] == {
        "draw": 14,
        "total": 24,
        "compile": 9,
    }
    assert failure.standard_route_execution["executionSpans"] == {"scriptProcess": [7, 7]}
    assert len(failure.standard_execution_attempts) == 2
    assert [item["durationMs"] for item in failure.standard_execution_attempts] == [15, 15]
    assert calls == ([{"deterministic": True}] * 2 if deterministic else [{}, {}])
