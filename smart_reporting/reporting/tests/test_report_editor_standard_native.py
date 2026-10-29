"""真实HTTP和CodeMode集成；不将本地烟测冒称浏览器或AI性能。"""

import asyncio
import hashlib
import json
import os
from time import perf_counter

import pytest
from agno.tools.code import CodeMode
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.api import create_report_editor_router
from smart_reporting.report_editor.chart_ai import (
    ChartAIEditService,
    create_report_editor_chart_ai_service,
)
from smart_reporting.report_editor.chart_edits import load_chart_edit_records
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
from smart_reporting.reporting.trace.contracts_v1 import TraceFileRefV1, derive_resource_id
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.workflow.runtime.code_generation import ReportingCodeGenerationRunner
from smart_reporting.runtime.settings import AgentSettings

from .lineage_fixtures.manifest import register_trace_manifest
from .test_report_editor_chart_ai import _make_editor_with_chart
from .test_standard_chart_families import radar_table, sankey, table


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "mode", [False, True, "browser", "radar", "funnel", "sankey",
             "real-ai-radar", "real-ai-funnel", "real-ai-sankey", "real-ai-donut"],
    ids=["direct", "real-ai", "browser-direct", "radar", "funnel", "sankey",
         "real-ai-radar", "real-ai-funnel", "real-ai-sankey", "real-ai-donut"],
)
async def test_http_direct_chart_native_pipeline_preserves_inputs_and_original(tmp_path, mode):
    family = mode.removeprefix("real-ai-") if mode in (
        "radar", "funnel", "sankey", "real-ai-radar", "real-ai-funnel", "real-ai-sankey"
    ) else None
    browser = mode == "browser"
    real_ai = mode is True or mode in ("real-ai-radar", "real-ai-funnel", "real-ai-sankey", "real-ai-donut")
    static_dir = os.environ.get("REPORT_CHART_BROWSER_STATIC") if browser else None
    if browser and not static_dir:
        pytest.skip("浏览器原生改图烟测需要显式指定当前前端build目录")
    if real_ai and os.environ.get("REPORT_CHART_REAL_AI_SMOKE") != "1":
        pytest.skip("真实模型请求仅在显式烟测开关下执行")
    fixture = await _make_editor_with_chart(tmp_path)
    editor, context = fixture.editor, fixture.context
    index = await editor.trace.load_index(context)
    # 独立合成图形夹具按真实身份登记；不借用真实用户业务数据或伪称生产事实。
    documents = [table(), {"columns": ["total"], "rows": [[100]],
                            "columnMeta": {"total": {"unit": "元"}}}]
    if family:
        documents = [{"radar": radar_table(),
                      "funnel": table([["首", 10], ["次", 20], ["零", 0]]),
                      "sankey": sankey()}[family]]
    if browser:
        documents = documents[:1]
    refs = []
    contents = []
    for position, document in enumerate(documents):
        document.update(schema="chart-input/v1", chartId="chart_001", role="measure",
                        source={"analysisId": "analysis_001", "path": "synthetic/facts.json",
                                "dataPath": f"metrics[{position}]"}, rowCount=len(document["rows"]))
        content = json.dumps(document, ensure_ascii=False).encode()
        path = f"reports/revision-1/native-input-{position}.json"
        await fixture.workspace.awrite_bytes(fixture.thread_id, path, content)
        contents.append(content)
        refs.append(TraceFileRefV1(resourceId=derive_resource_id(path), path=path,
                                  mediaType="application/json", size=len(content),
                                  sha256=hashlib.sha256(content).hexdigest()))
    index = index.model_copy(update={
        "files": (*index.files, *refs),
        "chart_traces": (index.chart_traces[0].model_copy(update={
            "plot_data_file_resource_ids": tuple(ref.resource_id for ref in refs),
        }),),
    })
    await fixture.workspace.awrite_bytes(fixture.thread_id, "reports/revision-1/trace-index-v1.json",
                                          encode_trace_index(index), overwrite=True)
    manifest_ref = await register_trace_manifest(fixture.workspace, fixture.thread_id, index, overwrite=True)
    manifest = await editor.trace.load_manifest(context.model_copy(update={"artifact_manifest": manifest_ref}))
    manifest = manifest.model_copy(update={"charts": (fixture.chart,)})
    manifest_bytes = manifest.model_dump_json(by_alias=True).encode()
    await fixture.workspace.awrite_bytes(fixture.thread_id, manifest_ref.path, manifest_bytes, overwrite=True)
    manifest_ref = manifest_ref.model_copy(update={"size": len(manifest_bytes),
                                                 "sha256": hashlib.sha256(manifest_bytes).hexdigest()})
    context = context.model_copy(update={"artifact_manifest": manifest_ref})
    editor.state_repository.durable.payload["reportEditorContexts"]["1"] = context.model_dump(mode="json", by_alias=True)
    identity = editor.workspace_registry.get(fixture.thread_id)
    runtime = ReportingCodeModeRuntime(CodeMode(snapshot=False, allow_shell=True, cwd=str(identity.root),
                                                timeout=45, max_kernels=1))
    lsp = ReportingLspProcessManager()

    def forbidden_model(*_args, **_kwargs):
        raise AssertionError("直达改图不能调用任何模型")

    runner = ReportingCodeGenerationRunner(forbidden_model, runtime, lsp, vision_reviewer=None)
    service = ChartAIEditService(editor=editor, workspace_registry=editor.workspace_registry,
                                 planner=None, runner=runner, timeout_seconds=45)
    if real_ai:
        from smart_reporting.reporting.agent import (
            _report_model,
            _reporting_phase_model,
            create_reporting_code_agent_factory,
        )
        from smart_reporting.reporting.model_policy import (
            ReportingThinkingProfile,
            apply_reporting_thinking_profile,
        )
        from smart_reporting.reporting.vision import ReportVisionReviewer

        settings = AgentSettings.from_environment()
        assert settings.report_enable_vision, "真实AI烟测不得跳过视觉审查"
        model = _reporting_phase_model(_report_model(settings, enable_thinking=settings.report_phase_enable_thinking))
        profile = (
            ReportingThinkingProfile.on(
                reasoning_effort=settings.report_phase_reasoning_effort,
                thinking_budget=settings.report_phase_thinking_budget,
                temperature=settings.report_phase_temperature,
            ) if settings.report_phase_enable_thinking
            else ReportingThinkingProfile.off(temperature=settings.report_phase_temperature)
        )
        apply_reporting_thinking_profile(model, profile)
        model.max_tokens = settings.report_output_token_reserve
        model.top_p = 0.95
        runner.agent_factory = create_reporting_code_agent_factory(
            model=model, name="native-editor-real-ai-smoke", task_kind="visualization")
        runner.vision_reviewer = ReportVisionReviewer(settings, fixture.workspace)
        service = create_report_editor_chart_ai_service(
            editor=editor, workspace_registry=editor.workspace_registry, model=model, runner=runner,
            timeout_seconds=float(settings.report_editor_chart_ai_timeout_seconds))
    app = FastAPI()
    app.include_router(create_report_editor_router(fixture.grants, editor=editor, chart_ai=service,
                                                   cookie_secure=False, allowed_origin="http://reports.test",
                                                   static_dir=static_dir))
    grant, _ = await fixture.grants.issue(context)
    base = f"/reports/v1/editor/{context.report_id}/1"
    previous = None
    try:
        if browser:
            await _browser_direct_preview(app, grant, fixture, service, runner, runtime, tmp_path)
            return
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
            assert (await client.get(f"/reports/v1/editor/open/{grant}", follow_redirects=False)).status_code == 303
            token = client.cookies.get("report_editor_session")
            headers = {"Origin": "http://reports.test", "X-CSRF-Token": fixture.grants.csrf_token(token)}
            availability = await client.get(f"{base}/api/charts/chart_001/ai-edits/availability")
            assert availability.json()["standardAvailable"] and availability.json()["available"] is real_ai
            for form in ((family,) if family else ("donut",) if mode == "real-ai-donut" else ("pie",) if real_ai else ("pie", "donut")):
                body = {"baseImagePath": previous.image.path if previous else fixture.chart_path,
                        "expectedSha256": previous.image.sha256 if previous else fixture.chart.sha256,
                        "title": "冻结范围构成", "altText": "合成夹具构成预览",
                        "standard": {"standardForm": form, "standardValueFields": ["value"],
                                     "standardLabelField": "period",
                                     "standardComposition": {"denominator": {"mode": "reference",
                                         "ref": {"sourceIndex": 1, "field": "total"}}}}}
                if family:
                    body["standard"] = {"standardForm": form, "standardLabelField": "period",
                                        "standardValueFields": ["value"]}
                    if form == "radar":
                        body["standard"]["standardValueFields"] = ["a", "b", "c"]
                    elif form == "sankey":
                        body["standard"].update(standardLabelField=None, standardEncoding={
                            "xField": "source", "yField": "target", "valueField": "value"})
                if previous:
                    body["previousEditId"] = previous.edit_id
                started = perf_counter()
                endpoint = "standard-edits"
                if real_ai:
                    endpoint = "ai-edits"
                    body.pop("standard")
                    body["baseTitle"] = body.pop("title")
                    body["baseAltText"] = body.pop("altText")
                    if family:
                        fields = {"radar": "standardValueFields=[a,b,c]，standardForm=radar，三个轴单位均为元",
                                  "funnel": "standardValueFields=[value]，standardLabelField=period，standardForm=funnel，顺序首、次、零",
                                  "sankey": "standardEncoding={xField:source,yField:target,valueField:value}，standardForm=sankey"}[family]
                        body["instruction"] = (
                            f"按已登记图表输入改成{family}图，严格使用{fields}。"
                            "完整保留输入行、字段和真实数值，不创建或归并数据；使用 Matplotlib 静态图。"
                            "图注简述字段、单位和范围。必须先完成独立视觉审查。"
                        )
                    else:
                        body["instruction"] = (f"改成{'环形图' if form == 'donut' else '饼图'}，完整保留首输入period类别和value数值，第二输入total为独立冻结分母。"
                            f"请使用standardForm={form}，standardLabelField=period，standardValueFields=[value]，"
                            "standardComposition.denominator为mode=reference、ref={sourceIndex:1,field:total}。"
                            "保持原始数据和独立视觉审查，图注说明仅展示冻结范围，不补其他。")
                response = await client.post(f"{base}/api/charts/chart_001/{endpoint}", json=body, headers=headers)
                assert response.status_code == 202, response.text
                edit_id = response.json()["editId"]
                async with asyncio.timeout(service.timeout_seconds + 10):
                    while True:
                        result = await client.get(f"{base}/api/charts/chart_001/ai-edits/{edit_id}")
                        assert result.status_code == 200, result.text
                        status = result.json()
                        if status["status"] in {"succeeded", "failed", "cancelled"}:
                            break
                        await asyncio.sleep(.02)
                print(json.dumps({"mode": "http_real_ai_smoke" if real_ai else "http_native_no_model_smoke",
                                  "status": status["status"], "elapsedMs": round((perf_counter()-started)*1000, 3),
                                  "error": status.get("error"), "planningRoute": status.get("planningRoute"),
                                  "renderingRoute": status.get("renderingRoute")}, ensure_ascii=False))
                assert status["status"] == "succeeded", status
                assert status["planningRoute"] == ("ai" if real_ai else "direct") and status["renderingRoute"] == "standard"
                assert status["visualInspection"]["reviewed"] is real_ai
                assert len(status["deterministicImageChecks"]) == (0 if real_ai else 1)
                if form == "funnel":
                    assert any("standard_funnel_nonmonotonic" in warning
                               for warning in status["warnings"])
                records = await load_chart_edit_records(fixture.workspace, fixture.thread_id, context.markdown_path)
                previous = records[-1]
                assert previous.standard_parameters["standardForm"] == form
                if form in {"pie", "donut"}:
                    denominator = previous.standard_parameters["standardComposition"]["denominator"]
                    assert denominator["mode"] == "reference"
                    assert denominator["ref"]["sourceIndex"] == 1
                    assert denominator["ref"]["field"] == "total"
                assert [ref.sha256 for ref in previous.plot_data_files] == [ref.sha256 for ref in refs]
                assert [await fixture.workspace.afile_bytes(fixture.thread_id, ref.path) for ref in previous.plot_data_files] == [(content, "application/json") for content in contents]
                image = await client.get(f"{base}/asset/{status['imageSrc']}")
                assert image.status_code == 200, image.text
                assert hashlib.sha256(image.content).hexdigest() == previous.image.sha256
                if family:
                    assert image.headers["content-type"].startswith("image/png")
                    (tmp_path / f"native-{form}.png").write_bytes(image.content)
                assert runner.registry.active_count == 0 and not runtime._logged_connections
                print(json.dumps({"mode": "http_real_ai_smoke" if real_ai else "http_native_no_model_smoke", "form": form,
                                  "postToAssetMs": round((perf_counter()-started)*1000, 3),
                                  "stageTimingsMs": status["stageTimingsMs"]}, ensure_ascii=False))
            assert await fixture.workspace.afile_bytes(fixture.thread_id, fixture.chart_path) == (fixture.chart_bytes, "image/png")
            assert await fixture.workspace.aread_text(fixture.thread_id, context.markdown_path) == fixture.markdown
    finally:
        await service.aclose()
        await lsp.aclose()
        await runtime.aclose()
        await editor.aclose()


async def _browser_direct_preview(app, grant, fixture, service, runner, runtime, tmp_path):
    """真实浏览器点预设至图片解码；不mock接口、不接受或保存报告正文。"""
    from playwright.async_api import async_playwright

    from .test_report_editor_browser import _start_server, _stop_server

    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.firefox.launch()
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                response = await page.goto(f"{base_url}/reports/v1/editor/open/{grant}")
                assert response.status == 200
                image = page.locator('.milkdown img[src*="chart-001.png"]').first
                await image.wait_for(timeout=20000)
                await image.scroll_into_view_if_needed()
                await image.hover()
                await page.locator(".asset-ai-edit-button").click()
                panel = page.locator(".chart-ai-edit")
                await panel.locator("#chart-ai-standard-preset").wait_for()
                assert await panel.locator('[data-action="submit"]').is_disabled()
                for position, form in enumerate(("pie", "donut")):
                    await panel.locator("#chart-ai-standard-preset").select_option(form)
                    async with page.expect_response(lambda result: result.request.method == "POST"
                        and result.url.endswith("/standard-edits")) as accepted:
                        started = perf_counter()
                        await panel.locator('[data-action="apply-standard"]').click()
                    response = await accepted.value
                    assert response.status == 202, await response.text()
                    edit_id = (await response.json())["editId"]
                    preview = panel.locator(".chart-ai-pages img").first
                    await preview.wait_for(timeout=60000)
                    await preview.evaluate("image => image.decode()")
                    elapsed = round((perf_counter() - started) * 1000, 3)
                    assert await preview.evaluate("image => image.naturalWidth > 0 && image.naturalHeight > 0")
                    status = service.edit_status(fixture.context, "chart_001", edit_id)
                    assert status["status"] == "succeeded" and status["planningRoute"] == "direct"
                    assert status["visualInspection"]["reviewed"] is False
                    assert runner.registry.active_count == 0 and not runtime._logged_connections
                    records = await load_chart_edit_records(fixture.workspace, fixture.thread_id, fixture.context.markdown_path)
                    assert records[-1].edit_id == edit_id
                    if position:
                        assert records[-1].base_image_path == records[-2].image.path
                        assert records[-1].plot_data_files == records[-2].plot_data_files
                    print(json.dumps({"mode": "firefox_native_no_model_smoke", "form": form,
                        "clickToDecodedPreviewMs": elapsed, "stageTimingsMs": status["stageTimingsMs"]}, ensure_ascii=False))
                    await page.screenshot(path=str(tmp_path / f"native-{form}-1280.png"), full_page=True)
                    assert await fixture.workspace.aread_text(fixture.thread_id, fixture.context.markdown_path) == fixture.markdown
                    if not position:
                        await panel.locator('[data-action="continue"]').click()
                await page.set_viewport_size({"width": 390, "height": 844})
                assert await panel.evaluate("element => element.scrollWidth <= element.clientWidth")
                await page.screenshot(path=str(tmp_path / "native-donut-390.png"), full_page=True)
                assert errors == []
            finally:
                await browser.close()
    finally:
        _stop_server(server)
