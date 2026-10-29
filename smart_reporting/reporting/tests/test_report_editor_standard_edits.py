"""标准直达改图复用任务与登记链；模型不可达，冻结身份不可放宽。"""

import hashlib
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from smart_reporting.report_editor import chart_ai
from smart_reporting.report_editor.chart_edits import load_chart_edit_records
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_report_editor_chart_ai import (
    _await_edit, _make_editor_with_chart, FakeRunner,
)


def _request(fixture, **overrides):
    return chart_ai.ChartStandardEditRequest.model_validate({
        "standard": {"standardForm": "bar"},
        "baseImagePath": fixture.chart_path,
        "expectedSha256": fixture.chart.sha256,
        **overrides,
    })


def test_standard_request_rejects_untrusted_or_missing_execution_scope():
    model = getattr(chart_ai, "ChartStandardEditRequest", None)
    assert model is not None, "缺少严格标准改图请求契约"
    valid = {"standard": {"standardForm": "bar"},
             "baseImagePath": "reports/chart.png", "expectedSha256": "a" * 64}
    assert model.model_validate(valid).standard.standard_form == "bar"
    for key in ("standard", "baseImagePath", "expectedSha256"):
        with pytest.raises(ValidationError):
            model.model_validate({name: value for name, value in valid.items() if name != key})
    for key in ("instruction", "code", "sourcePath", "dataBindings", "deterministic"):
        with pytest.raises(ValidationError):
            model.model_validate({**valid, key: "untrusted"})


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_direct_runtime_missing_and_readonly_cannot_start(tmp_path):
    fixture = await _make_editor_with_chart(tmp_path)
    service = chart_ai.ChartAIEditService(editor=fixture.editor, workspace_registry=fixture.editor.workspace_registry,
        planner=None, runner=SimpleNamespace())
    available = await service.availability(fixture.context, SimpleNamespace(capabilities=None), "chart_001")
    assert available["standardAvailable"] is False
    for session in (SimpleNamespace(capabilities=None), SimpleNamespace(capabilities={})):
        with pytest.raises(ReportingError):
            await service.start_standard_edit(fixture.context, session, "chart_001", _request(fixture))
    assert not service._jobs


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_direct_standard_without_models_registers_and_reports_honest_preview(tmp_path, monkeypatch):
    fixture = await _make_editor_with_chart(tmp_path)
    calls = []

    class Runner:
        vision_reviewer = None

        async def run_standard_visualization(self, *args, **kwargs):
            raise AssertionError("测试由固定路由边界执行")

        async def run(self, *args, **kwargs):
            raise AssertionError("直达不得进入 Coding")

    async def route(runner, context, workspace, plan, inputs, facts, run_context, *, deterministic=False):
        assert deterministic is True
        calls.append((plan, inputs))
        source = "\n".join(repr(item.path) for item in inputs.files).encode()
        await workspace.awrite_bytes(fixture.thread_id, context.script_path, source, overwrite=True)
        for page in plan.charts:
            await workspace.awrite_bytes(fixture.thread_id, page.source_path, fixture.chart_bytes, overwrite=True)
        return SimpleNamespace(visual_inspection_receipts=(), standard_chart_routes=(
            {"chartId": "chart_001", "route": "standard", "warnings": ({"code": "coverage_unproven", "message": "冻结数据语义待人工核对"},)},
        ))

    monkeypatch.setattr(chart_ai, "run_standard_chart_routes", route)
    service = chart_ai.ChartAIEditService(editor=fixture.editor,
        workspace_registry=fixture.editor.workspace_registry, planner=None, runner=Runner())
    available = await service.availability(fixture.context, SimpleNamespace(capabilities=None), "chart_001")
    assert available["available"] is False
    assert available["standardAvailable"] is True
    started = await service.start_standard_edit(fixture.context, SimpleNamespace(capabilities=None),
        "chart_001", _request(fixture, title="新的标准图"))
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "succeeded", status
    assert status["planningRoute"] == "direct"
    assert status["renderingRoute"] == "standard"
    assert status["visualInspection"]["reviewed"] is False
    assert status["warnings"] == ["冻结数据语义待人工核对（coverage_unproven）"]
    assert all(value >= 0 for value in status["stageTimingsMs"].values())
    assert set(status["stageTimingsMs"]) >= {"check", "materialize", "plan", "compile", "draw", "inspect", "register", "total"}
    records = await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path)
    assert records[-1].chart.title == "新的标准图"
    assert records[-1].plot_data_files[0].sha256 == hashlib.sha256(fixture.plot_bytes).hexdigest()
    assert len(calls) == 1
    await service.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("failure", [None, "execute", "cancel", "cleanup"])
async def test_legacy_template_closes_own_session_and_drains_without_masking_primary_result(tmp_path, failure):
    fixture = await _make_editor_with_chart(tmp_path, template_ready=True)
    events = []

    class Runtime:
        async def execute_script(self, session_id, workspace, path, **kwargs):
            events.append(("execute", session_id))
            if failure == "execute":
                raise ReportingError("template_execution_failed", "原始执行失败")
            if failure == "cancel":
                raise asyncio.CancelledError
            await workspace.awrite_bytes(fixture.thread_id, path.rsplit("/", 1)[0] + "/chart.png", fixture.chart_bytes, overwrite=True)
        async def shutdown(self, session_id):
            events.append(("shutdown", session_id))
            if failure in {"cleanup", "execute"}:
                raise RuntimeError("清理失败不可覆盖主要结果")
        def drain_execution_spans(self, session_id):
            events.append(("drain", session_id))
            return {"script": [1], "shutdown": [2]}

    service = chart_ai.ChartAIEditService(editor=fixture.editor, workspace_registry=fixture.editor.workspace_registry,
        planner=None, runner=SimpleNamespace(code_mode_runtime=Runtime()))
    catalog = await service.templates(fixture.context, SimpleNamespace(capabilities=None), "chart_001")
    selected = next(item for item in catalog["templates"] if item["available"])
    started = await service.start_template(fixture.context, SimpleNamespace(capabilities=None), "chart_001",
        chart_ai.ChartTemplateApplyRequest(templateId=selected["templateId"], expectedSha256=fixture.chart.sha256))
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert [event[0] for event in events] == ["execute", "shutdown", "drain"]
    assert len({event[1] for event in events}) == 1
    if failure == "execute":
        assert status["error"]["code"] == "template_execution_failed"
    elif failure == "cancel":
        assert status["status"] == "cancelled"
    else:
        assert status["status"] == "succeeded", status
    await service.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("failure", ["route", "inspect"])
async def test_direct_failure_never_calls_planner_or_coding_and_keeps_original(tmp_path, monkeypatch, failure):
    fixture = await _make_editor_with_chart(tmp_path)

    class Runner:
        vision_reviewer = None
        async def run_standard_visualization(self, *args, **kwargs):
            raise AssertionError("模型不可达")
        async def run(self, *args, **kwargs):
            raise AssertionError("Coding 不可达")

    async def planner(*args, **kwargs):
        raise AssertionError("planner 不可达")

    async def route(runner, context, workspace, plan, *args, **kwargs):
        if failure == "route":
            raise ReportingError("standard_geometry_unsupported", "标准几何不能表达此参数。")
        # 输出缺失使真实的逐页检查失败，仍不得转入模型修复。
        return SimpleNamespace(visual_inspection_receipts=(), standard_chart_routes=())

    monkeypatch.setattr(chart_ai, "run_standard_chart_routes", route)
    service = chart_ai.ChartAIEditService(editor=fixture.editor, workspace_registry=fixture.editor.workspace_registry,
        planner=planner, runner=Runner())
    started = await service.start_standard_edit(fixture.context, SimpleNamespace(capabilities=None), "chart_001", _request(fixture))
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "failed"
    if failure == "route":
        assert "标准几何" in status["error"]["message"]
    assert await fixture.workspace.afile_bytes(fixture.thread_id, fixture.chart_path) == (fixture.chart_bytes, "image/png")
    assert not await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path)
    await service.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("inherit_settings", [True, False])
async def test_direct_inherits_ordered_full_template_inputs_bindings_and_dataset_ids(tmp_path, monkeypatch, inherit_settings):
    from smart_reporting.report_editor.chart_edits import ChartEditRecord, append_chart_edit_record
    fixture = await _make_editor_with_chart(tmp_path)
    prefix = "reports/revision-1/chart-edits/cedit-previous123"
    image_path, script_path = f"{prefix}/chart.png", f"{prefix}/chart_edit.py"
    await fixture.workspace.awrite_bytes(fixture.thread_id, image_path, fixture.chart_bytes)
    await fixture.workspace.awrite_bytes(fixture.thread_id, script_path, b"pass\n")
    inputs = [fixture.plot_bytes, fixture.plot_bytes.replace(b"3600", b"3700")]
    refs = []
    for position, content in enumerate(inputs, 1):
        path = f"{prefix}/input-{position}.json"
        await fixture.workspace.awrite_bytes(fixture.thread_id, path, content)
        refs.append({"path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    bindings = [{"analysisId": "analysis_001", "factPath": "facts/first.json", "dataPath": "/metrics/0", "fields": ["period", "revenue"]},
                {"analysisId": "analysis_001", "factPath": "facts/second.json", "dataPath": "/metrics/1", "fields": ["period", "revenue"]}]
    record = ChartEditRecord.model_validate({"editId": "cedit-previous123", "chartId": "chart_001",
        "baseImagePath": fixture.chart_path, "baseImageSha256": fixture.chart.sha256,
        "instruction": "已登记模板", "level": ["L1"], "dataOrigin": "template",
        "image": {"path": image_path, "size": len(fixture.chart_bytes), "sha256": fixture.chart.sha256},
        "script": {"path": script_path, "size": 5, "sha256": hashlib.sha256(b"pass\n").hexdigest()},
        "plotDataFiles": refs, "dataBindings": bindings, "standardParameters": {"standardForm": "bar", "standardValueFields": ["revenue"]},
        "chart": {"title": "收入", "altText": "完整输入", "visualForm": "柱状图", "datasetIds": ["dataset-url-abc0001"]},
        "createdAt": datetime.now(UTC).isoformat(), "userId": "user-1"})
    await append_chart_edit_record(fixture.workspace, fixture.thread_id, fixture.context.markdown_path, record)

    async def route(runner, context, workspace, plan, frozen, *args, deterministic=False):
        assert deterministic
        assert [file.content for file in frozen.files] == inputs
        assert list(plan.charts[0].data_bindings) == bindings
        await workspace.awrite_bytes(fixture.thread_id, context.script_path, repr([file.path for file in frozen.files]).encode(), overwrite=True)
        await workspace.awrite_bytes(fixture.thread_id, context.declared_output_paths[0], fixture.chart_bytes, overwrite=True)
        return SimpleNamespace(visual_inspection_receipts=(), standard_chart_routes=({"route": "standard"},))

    monkeypatch.setattr(chart_ai, "run_standard_chart_routes", route)
    service = chart_ai.ChartAIEditService(editor=fixture.editor, workspace_registry=fixture.editor.workspace_registry, planner=None,
        runner=SimpleNamespace(run_standard_visualization=lambda: None))
    previous = record
    for _ in range(2):
        started = await service.start_standard_edit(fixture.context, SimpleNamespace(capabilities=None), "chart_001",
            _request(fixture, standard={} if inherit_settings else {"standardForm": "bar"},
                     inheritPreviousStandard=inherit_settings,
                     previousEditId=previous.edit_id, baseImagePath=previous.image.path))
        status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
        assert status["status"] == "succeeded", status
        previous = (await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path))[-1]
        assert previous.data_origin == "template"
        assert list(previous.data_bindings) == bindings
        assert previous.chart.dataset_ids == ("dataset-url-abc0001",)
        assert [item.sha256 for item in previous.plot_data_files] == [item["sha256"] for item in refs]
        assert previous.standard_parameters["standardValueFields"] == (["revenue"] if inherit_settings else [])
    # AI明确不给standard时进入自由绘图，不能被上一轮模板参数强制接管。
    async def planner(request):
        assert {"pie", "donut", "radar", "funnel", "sankey"}.issubset(request["standardChartCapabilities"]["forms"])
        assert "standardComposition" in request["standardChartSchema"]["properties"]
        return chart_ai.ChartEditPlan(level=("L1",), drawInstruction="自由调整布局", standard=None)
    service.planner = planner
    service.runner = FakeRunner(fixture.chart_bytes)
    async def forbidden_route(*args, **kwargs):
        raise AssertionError("AI自由绘图不得强套继承参数")
    monkeypatch.setattr(chart_ai, "run_standard_chart_routes", forbidden_route)
    started = await service.start_edit(fixture.context, SimpleNamespace(capabilities=None), "chart_001",
        chart_ai.ChartAIEditRequest(instruction="自由调整", previousEditId=previous.edit_id, baseImagePath=previous.image.path,
            expectedSha256=previous.image.sha256))
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "succeeded", status
    latest = (await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path))[-1]
    assert latest.standard_parameters == {}
    assert [ref.sha256 for ref in latest.plot_data_files] == [item["sha256"] for item in refs]
    assert status["planningRoute"] == "ai" and status["renderingRoute"] == "coding"
    await service.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_standard_route_requires_csrf_strict_body_and_service_readonly_guard():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from smart_reporting.report_editor import ReportEditorGrantService
    from smart_reporting.report_editor.api import create_report_editor_router
    from smart_reporting.report_editor.service import InMemoryReportEditorRepository, ReportEditorSession

    class Editor:
        async def context_for_session(self, session):
            return SimpleNamespace(report_id=session.report_id, revision=session.revision)

    class Service:
        async def start_standard_edit(self, context, session, chart_id, request):
            if session.capabilities is not None:
                raise ReportingError("report_editor_chart_ai_unavailable", "当前会话只读。")
            return {"editId": "cedit-0123456789abcdef", "status": "queued"}

    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=Editor(), chart_ai=Service(), cookie_secure=False))
    session = ReportEditorSession(report_id="report-1", revision=1, workflow_run_id="report-1", context_sha256="0" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1))
    await repository.put_session(hashlib.sha256(b"session-1").hexdigest(), session)
    base = "/reports/v1/editor/report-1/1/api/charts/chart_001/standard-edits"
    body = {"standard": {"standardForm": "bar"}, "baseImagePath": "reports/chart.png", "expectedSha256": "a" * 64}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.example.com") as client:
        client.cookies.set("report_editor_session", "session-1")
        assert (await client.post(base, json=body)).status_code == 403
        headers = {"Origin": "https://reports.example.com", "X-CSRF-Token": grants.csrf_token("session-1")}
        assert (await client.post(base, json={**body, "instruction": "不得被忽略"}, headers=headers)).status_code == 422
        assert (await client.post(base, json=body, headers=headers)).status_code == 202
        await repository.put_session(hashlib.sha256(b"session-1").hexdigest(), replace(session, capabilities={}))
        assert (await client.post(base, json=body, headers=headers)).status_code != 202


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("overrides", [{"expectedSha256": "0" * 64}, {"baseImagePath": "../foreign.png"}])
async def test_direct_rejects_changed_hash_and_foreign_base_before_execution(tmp_path, overrides):
    fixture = await _make_editor_with_chart(tmp_path)
    service = chart_ai.ChartAIEditService(editor=fixture.editor, workspace_registry=fixture.editor.workspace_registry,
        planner=None, runner=SimpleNamespace(run_standard_visualization=lambda: None))
    started = await service.start_standard_edit(fixture.context, SimpleNamespace(capabilities=None), "chart_001", _request(fixture, **overrides))
    status = await _await_edit(service, fixture.context, "chart_001", started["editId"])
    assert status["status"] == "failed"
    assert status["error"]["code"] == "report_editor_chart_ai_base_changed"
    await service.aclose()
