"""状态等待复用同一任务；HTTP断连或超时不得取消正在绘图的任务。"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.api import create_report_editor_router
from smart_reporting.report_editor.chart_ai import ChartAIEditService, ChartStandardEditRequest
from smart_reporting.reporting.models import ReportingError


async def _running_service(monkeypatch, outcome):
    service = ChartAIEditService(editor=SimpleNamespace(), workspace_registry=SimpleNamespace(),
        planner=None, runner=SimpleNamespace(run_standard_visualization=lambda: None))
    context = SimpleNamespace(report_id="report", revision=1, scope={"userId": "user"})
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def check(*_args, **_kwargs):
        return None, (context, None, None, None)

    async def run(*_args, **_kwargs):
        entered.set()
        await gate.wait()
        if outcome == "failed":
            raise ReportingError("standard_geometry_invalid", "几何检查未通过。")
        return {"status": "succeeded"}

    monkeypatch.setattr(service, "_check", check)
    monkeypatch.setattr(service, "_run_edit", run)
    started = await service.start_standard_edit(context, SimpleNamespace(capabilities=None), "chart",
        ChartStandardEditRequest(standard={"standardForm": "bar"},
            baseImagePath="reports/chart.png", expectedSha256="a" * 64))
    await entered.wait()
    return service, context, started["editId"], gate


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("outcome", ["succeeded", "failed", "cancelled"])
async def test_status_wait_returns_existing_job_terminal_result(monkeypatch, outcome):
    service, context, edit_id, gate = await _running_service(monkeypatch, outcome)
    try:
        waiter = asyncio.create_task(service.wait_edit_status(context, "chart", edit_id, wait_ms=1500))
        await asyncio.sleep(0)
        assert not waiter.done()
        if outcome == "cancelled":
            service.cancel_edit(context, "chart", edit_id)
        else:
            gate.set()
        status = await asyncio.wait_for(waiter, .5)
        assert status["status"] == outcome
        assert status == service.edit_status(context, "chart", edit_id)
        assert set(service._jobs) == {edit_id}
        if outcome == "failed":
            assert status["error"]["code"] == "standard_geometry_invalid"
    finally:
        await service.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("stop_waiting", ["timeout", "disconnect"])
async def test_status_wait_timeout_or_disconnect_does_not_cancel_job(monkeypatch, stop_waiting):
    service, context, edit_id, gate = await _running_service(monkeypatch, "succeeded")
    try:
        if stop_waiting == "timeout":
            status = await service.wait_edit_status(context, "chart", edit_id, wait_ms=1)
            assert status["status"] == "running"
        else:
            waiter = asyncio.create_task(service.wait_edit_status(context, "chart", edit_id, wait_ms=1500))
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        task = service._jobs[edit_id].task
        assert not task.done() and not task.cancelling()
        gate.set()
        await task
        assert service.edit_status(context, "chart", edit_id)["status"] == "succeeded"
    finally:
        await service.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_status_wait_rejects_other_chart_before_waiting(monkeypatch):
    service, context, edit_id, _gate = await _running_service(monkeypatch, "succeeded")
    try:
        with pytest.raises(ReportingError) as caught:
            await asyncio.wait_for(service.wait_edit_status(context, "foreign", edit_id, wait_ms=1500), .5)
        assert caught.value.code == "report_editor_chart_ai_missing"
        assert not service._jobs[edit_id].task.done()
    finally:
        await service.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_http_status_wait_is_bounded_scoped_and_returns_completion(monkeypatch):
    service, context, edit_id, gate = await _running_service(monkeypatch, "succeeded")

    async def session_for(_token):
        return SimpleNamespace(report_id="report", revision=1)

    async def context_for(_session):
        return context

    app = FastAPI()
    app.include_router(create_report_editor_router(SimpleNamespace(lookup_session=session_for),
        editor=SimpleNamespace(context_for_session=context_for), chart_ai=service))
    url = f"/reports/v1/editor/report/1/api/charts/chart/ai-edits/{edit_id}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
            assert (await client.get(url)).json()["status"] == "running"
            for invalid in ("-1", "1501", "1.5"):
                assert (await client.get(url, params={"waitMs": invalid})).status_code == 422
            assert (await client.get(url.replace("/charts/chart/", "/charts/foreign/"),
                params={"waitMs": 1500})).status_code == 404
            pending = asyncio.create_task(client.get(url, params={"waitMs": 1500}))
            await asyncio.sleep(0)
            assert not pending.done()
            gate.set()
            response = await asyncio.wait_for(pending, .5)
            assert response.status_code == 200 and response.json()["status"] == "succeeded"
    finally:
        await service.aclose()
