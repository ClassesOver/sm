"""任务回执保留真实全程计时、安全故障原因和有序来源绑定。"""
import asyncio
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor import chart_ai
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime.chart_inputs import _materialize_chart
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding
from smart_reporting.reporting.tests.test_report_editor_chart_ai import (
    FakeRunner, _await_edit, _make_editor_with_chart,
)
from smart_reporting.reporting.workflow.checkpoint import ChartVisualInspectionReceipt


def service_with_clock(monkeypatch):
    clock = [1.0]
    monkeypatch.setattr(chart_ai, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    service = chart_ai.ChartAIEditService(editor=SimpleNamespace(), workspace_registry=SimpleNamespace(),
        planner=None, runner=SimpleNamespace(run_standard_visualization=lambda: None))
    context = SimpleNamespace(report_id="report", revision=1, scope={"userId": "user"})
    async def check(*args, **kwargs):
        clock[0] += .040
        return None, (context, None, None, None)
    monkeypatch.setattr(service, "_check", check)
    request = chart_ai.ChartStandardEditRequest(standard={"standardForm": "bar"},
        baseImagePath="reports/chart.png", expectedSha256="a" * 64)
    return service, context, request, clock


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_request_total_includes_precheck_and_background_queue(monkeypatch):
    service, context, request, clock = service_with_clock(monkeypatch)
    async def run(*args, **kwargs):
        clock[0] += .002
        return {"status": "succeeded"}
    monkeypatch.setattr(service, "_run_edit", run)
    started = await service.start_standard_edit(context, SimpleNamespace(capabilities=None), "chart", request)
    clock[0] += .005
    await service._jobs[started["editId"]].task
    await asyncio.sleep(0)
    timings = service.edit_status(context, "chart", started["editId"])["stageTimingsMs"]
    assert timings["check"] == 40
    assert timings["total"] == 47
    assert timings["queued"] == 7


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_failure_and_cancel_status_keep_bounded_reason_and_real_execution_observations(monkeypatch, cancelled):
    service, context, request, clock = service_with_clock(monkeypatch)
    observation = {"status": "cancelled" if cancelled else "failed", "failedStage": "inspect",
        "stageTimings": {"draw": 17, "inspect": 3, "total": 23},
        "stageStatuses": {"draw": "succeeded", "inspect": "cancelled" if cancelled else "failed"},
        "executionSpans": {"scriptProcess": [17]}, "rows": [["secret"]]}
    failure = asyncio.CancelledError() if cancelled else ReportingError("report_standard_visualization_failed",
        "标准图片检查失败。", details={"code": "report_chart_blank", "message": "第二页为空白图片。",
        "details": {"path": "charts/page-2.png", "rows": [["secret"]]}, "source": "secret script",
        "standardExecution": observation})
    failure.standard_execution = observation
    failure.standard_execution_attempts = (observation,)
    failure.standard_route_total_ms = 27
    async def run(*args, **kwargs):
        clock[0] += .027
        raise failure
    monkeypatch.setattr(service, "_run_edit", run)
    started = await service.start_standard_edit(context, SimpleNamespace(capabilities=None), "chart", request)
    with pytest.raises(type(failure)):
        await service._jobs[started["editId"]].task
    await asyncio.sleep(0)
    status = service.edit_status(context, "chart", started["editId"])
    assert status["status"] == ("cancelled" if cancelled else "failed")
    assert status["stageTimingsMs"]["total"] == 67
    assert status["executionStageTimingsMs"] == {"draw": 17, "inspect": 3, "total": 23}
    assert status["executionStageStatuses"]["inspect"] == ("cancelled" if cancelled else "failed")
    assert status["executionSpans"] == {"scriptProcess": [17]}
    assert status["standardRouteTotalMs"] == 27
    assert len(status["executionAttempts"]) == 1
    assert "secret" not in str(status)
    if not cancelled:
        diagnostic = status["error"]["executionDiagnostic"]
        assert diagnostic == {"code": "report_chart_blank", "message": "第二页为空白图片。",
            "phase": "inspect", "details": {"path": "charts/page-2.png"}}
        assert "report_chart_blank" in status["error"]["message"]


def test_same_source_distinct_fields_and_roles_preserve_input_order():
    bindings = tuple(ChartDataBinding(analysisId="analysis", factPath="facts/data.json",
        dataPath="findings[0].rows", fields=fields, role=role)
        for fields, role in [(("category", "amount"), "main"), (("total",), "denominator")])
    chart = SimpleNamespace(chart_id="chart", data_bindings=bindings)
    files, _entries = _materialize_chart(chart,
        {("analysis", "facts/data.json", "findings[0].rows"): (frozenset({"category", "amount", "total"}), {})},
        {"facts/data.json": {"findings": [{"columns": ["category", "amount", "total"], "rows": [["甲", 20, 100]]}]}}, "plots")
    restored = chart_ai._bindings_from_plot_files(files)
    assert [(item["fields"], item["role"]) for item in restored] == [
        (["category", "amount"], "main"), (["total"], "denominator")]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_nonmapping_reporting_error_details_preserve_primary_failure_code(monkeypatch):
    service, context, request, _clock = service_with_clock(monkeypatch)
    error = ReportingError("runner_primary_failure", "原始运行失败。", details=["original"])
    async def run(*args, **kwargs):
        raise error
    monkeypatch.setattr(service, "_run_edit", run)
    started = await service.start_standard_edit(context, SimpleNamespace(capabilities=None), "chart", request)
    with pytest.raises(ReportingError) as failed:
        await service._jobs[started["editId"]].task
    assert failed.value is error
    status = service.edit_status(context, "chart", started["editId"])
    assert status["status"] == "failed"
    assert status["error"] == {"code": "runner_primary_failure", "message": "原始运行失败。"}


def test_route_aggregate_drives_attribution_without_replacing_final_runner_or_adding_nested_totals(monkeypatch):
    monkeypatch.setattr(chart_ai, "time", SimpleNamespace(monotonic=lambda: .100))
    job = chart_ai._ChartEditJob(report_id="report", revision=1, chart_id="chart", user_id="user",
        task=None, started_at=0, finished_at=.100, stage_timings_ms={"draw": 80})
    error = ReportingError("route_failed", "路由检查失败。")
    error.standard_execution = {"status": "failed", "stageTimings": {"inspect": 3, "total": 7}}
    error.standard_route_execution = {"status": "failed", "initialCompileMs": 2,
        "initialCompileStatus": "succeeded", "stageTimings": {"inspect": 17, "compile": 5, "total": 40},
        "routeTotalMs": 50, "executionSpans": {"scriptProcess": [11, 19], "secret": [1]},
        "rows": [["secret"]]}
    error.standard_route_total_ms = 50
    outer = ReportingError("wrapped", "包装错误。")
    outer.__cause__ = error
    job.capture_execution(outer, phase="initial")
    assert job.execution_observation["executionStageTimingsMs"] == {"inspect": 3, "total": 7}
    route = job.execution_observation["executionRounds"][0]["standardRouteExecution"]
    assert route["stageTimings"] == {"inspect": 17, "compile": 5, "total": 40}
    assert route["initialCompileMs"] == 2
    assert route["executionSpans"] == {"scriptProcess": [11, 19]}
    assert job.timings()["inspect"] == 17
    assert job.timings()["compile"] == 5
    assert job.timings()["draw"] == 58
    assert job.timings()["total"] == 100
    assert "secret" not in str(job.execution_observation)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("repair_outcome", ["succeeded", "failed", "cancelled"])
async def test_repair_rounds_retain_first_and_actual_repair_observations(tmp_path, monkeypatch, repair_outcome):
    fixture = await _make_editor_with_chart(tmp_path)
    runner = FakeRunner(fixture.chart_bytes)
    runner.run_standard_visualization = lambda *args: None
    async def planner(request):
        return chart_ai.ChartEditPlan(level=("L1",), drawInstruction="调整布局", standard={"standardForm": "bar"})
    async def route(runner, context, workspace, plan, inputs, facts, run_context):
        first = await runner.run(context, workspace, facts, run_context=run_context)
        first.visual_inspection_receipts = (ChartVisualInspectionReceipt(
            sourcePath=context.declared_output_paths[0], sha256=fixture.chart.sha256, reviewed=True,
            requiresRevision=True, modelId="fixture-review"),)
        first.stage_timings = {"draw": 11, "inspect": 3, "compile": 2, "total": 19}
        first.stage_statuses = {"draw": "succeeded", "inspect": "succeeded", "compile": "succeeded"}
        first.execution_spans = {"scriptProcess": [11]}
        first.route_total_ms = 25
        first.execution_attempts = ({"attempt": 1, "status": "succeeded", "stageTimings": {"draw": 11}},)
        return first
    original_run = runner.run
    async def run(context, workspace, facts, *, run_context, diagnostic=None):
        if diagnostic is None:
            return await original_run(context, workspace, facts, run_context=run_context)
        if repair_outcome != "succeeded":
            error = asyncio.CancelledError() if repair_outcome == "cancelled" else ReportingError(
                "repair_failed", "修复图片检查未完成。")
            error.standard_execution = {"status": repair_outcome, "failedStage": "inspect",
                "stageTimings": {"draw": 31, "inspect": 7, "total": 41},
                "stageStatuses": {"draw": "succeeded", "inspect": repair_outcome},
                "executionSpans": {"scriptProcess": [31]}}
            error.standard_execution_attempts = (error.standard_execution,)
            raise error
        repaired = await original_run(context, workspace, facts, run_context=run_context, diagnostic=diagnostic)
        repaired.stage_timings = {"draw": 31, "inspect": 7, "total": 41}
        repaired.stage_statuses = {"draw": "succeeded", "inspect": "succeeded"}
        repaired.execution_spans = {"scriptProcess": [31]}
        return repaired
    monkeypatch.setattr(chart_ai, "run_standard_chart_routes", route)
    service = chart_ai.ChartAIEditService(editor=fixture.editor, workspace_registry=fixture.editor.workspace_registry,
        planner=planner, runner=runner)
    monkeypatch.setattr(runner, "run", run)
    started = await service.start_edit(fixture.context, SimpleNamespace(capabilities=None), "chart_001",
        chart_ai.ChartAIEditRequest(instruction="调整布局"))
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == ("cancelled" if repair_outcome == "cancelled" else "succeeded"), status
    rounds = status["executionRounds"]
    assert [(item["round"], item["phase"], item["status"]) for item in rounds] == [
        (1, "initial", "succeeded"), (2, "repair", repair_outcome)]
    assert rounds[0]["executionStageTimingsMs"] == {"draw": 11, "inspect": 3, "compile": 2, "total": 19}
    assert rounds[0]["standardRouteTotalMs"] == 25
    assert rounds[0]["executionAttempts"][0]["attempt"] == 1
    assert rounds[0]["executionSpans"] == {"scriptProcess": [11]}
    assert rounds[1]["executionStageTimingsMs"] == {"draw": 31, "inspect": 7, "total": 41}
    assert rounds[1]["executionStageStatuses"]["inspect"] == repair_outcome
    assert rounds[1]["executionSpans"] == {"scriptProcess": [31]}
    assert "standardRouteTotalMs" not in rounds[1]
    assert status["executionTimingSemantics"] == "per-round nested timings; totals and spans are not additive wall time"
    assert status["stageTimingsMs"]["inspect"] >= 10
    assert status["stageTimingsMs"]["compile"] >= 2
    assert status["executionStageTimingsMs"] == (
        {"draw": 11, "inspect": 3, "compile": 2, "total": 19} if repair_outcome == "failed"
        else {"draw": 31, "inspect": 7, "total": 41})
    if repair_outcome == "failed":
        assert any("已保留首轮结果" in warning for warning in status["warnings"])
    await service.aclose()
