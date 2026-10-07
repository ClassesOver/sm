"""Browser smoke tests for the report editor evidence browser.

Requires the frontend static build and Playwright. Most tests use system
Chromium; evidence workflow matrix tests also accept Firefox/WebKit
via REPORT_EDITOR_BROWSER. Selected non-Chromium engines must be installed
before running tests; a missing executable or dependency fails explicitly.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
    create_report_editor_router,
)
from smart_reporting.reporting.delivery.publishing import ReportDownloadGrant
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_report_editor_retention import _make_shared_revisions
from smart_reporting.reporting.tests.test_trace_subject_validate import (
    _make_editor_with_subject,
)
from smart_reporting.reporting.workflow.state import ReportingPhase
from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY

pytestmark = [pytest.mark.integration]


def _find_chromium() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None


@pytest.fixture(scope="module")
def browser_available() -> None:
    pytest.importorskip("playwright")
    if _find_chromium() is None:
        pytest.skip("no chromium-based browser found in PATH")


@pytest.fixture(scope="module")
def frontend_built() -> None:
    index = Path(__file__).parents[3] / "smart_reporting" / "report_editor" / "static" / "index.html"
    if not index.is_file():
        pytest.skip("frontend static build not found")


@pytest.fixture
def browser_download_dir():
    # Snap Chromium 与测试进程的 /tmp 不共享；项目目录对两者均可见。
    with TemporaryDirectory(prefix=".editor-download-", dir=Path(__file__).parents[3]) as directory:
        yield directory


@pytest.fixture
def evidence_browser_engine():
    pytest.importorskip("playwright")
    engine = os.environ.get("REPORT_EDITOR_BROWSER", "chromium")
    if engine not in ("chromium", "firefox", "webkit"):
        pytest.fail(f"不支持的证据浏览器测试引擎：{engine}")
    if engine == "chromium" and _find_chromium() is None:
        pytest.skip("no chromium-based browser found in PATH")
    return engine


def _start_server(app: FastAPI) -> tuple[str, Any]:
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("server failed to start")
    assert server.servers
    sock = next(iter(server.servers))
    port = sock.sockets[0].getsockname()[1]
    return f"http://127.0.0.1:{port}", server


def _stop_server(server: Any) -> None:
    server.should_exit = True
    deadline = time.monotonic() + 5
    while server.started and time.monotonic() < deadline:
        time.sleep(0.05)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_retired_sources_keep_browser_metadata_and_live_revision_preview(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str,
) -> None:
    from playwright.async_api import async_playwright

    editor, repository, first, second, _ = await _make_shared_revisions(tmp_path)
    repository.durable = repository.durable.model_copy(update={"phase": ReportingPhase.COMPLETED})
    now = datetime.now(UTC)
    await editor.set_revision_retention(first, expires_at=now)
    await editor.cleanup_revision_sources(second, now=now)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    sessions = []
    for context in (first, second):
        raw, _ = await grants.issue(context)
        value, _ = await grants.exchange(raw)
        sessions.append(value)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            try:
                for context, session in zip((first, second), sessions, strict=True):
                    page = await browser.new_page(viewport={"width": 1280, "height": 720})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    await page.context.add_cookies([{"name": "report_editor_session", "value": session,
                        "domain": "127.0.0.1", "path": "/"}])
                    response = await page.goto(f"{base_url}/reports/v1/editor/{context.report_id}/{context.revision}")
                    assert response.status == 200
                    await page.locator('button[data-action="sources"]').click()
                    overlay = page.locator(".evidence-shell")
                    dataset = overlay.locator(".evidence-directory-item").filter(has_text="收入明细.csv")
                    await dataset.wait_for(timeout=15000)
                    await dataset.click()
                    if context == first:
                        await overlay.locator(".evidence-status").filter(has_text="数据快照已超过保留期").wait_for()
                        assert await overlay.locator(".evidence-table").count() == 0
                        assert await overlay.locator(".evidence-retry").count() == 0
                        assert await overlay.get_by_role("button", name="下载此快照", exact=True).count() == 0
                        dataset_id = (await editor.trace.load_index(first)).datasets[0].dataset_id
                        denied = await page.request.get(
                            f"{base_url}/reports/v1/editor/{first.report_id}/1/api/datasets/{dataset_id}/download")
                        assert denied.status == 410
                        assert (await denied.json())["detail"]["code"] == "snapshot_expired"
                        await page.screenshot(path=str(tmp_path / "retired-source-metadata.png"), full_page=True)
                    else:
                        await overlay.locator("table").filter(has_text="3600").wait_for(timeout=10000)
                        await page.screenshot(path=str(tmp_path / "live-shared-source-preview.png"), full_page=True)
                    assert errors == []
                    await page.close()
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_online_subject_opens_frozen_fact_and_session_expiry_has_no_retry(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str,
) -> None:
    from playwright.async_api import async_playwright

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    assert index is not None
    subject_id = index.subject_bindings[0].subject_id
    raw, _ = await grants.issue(context)
    session_value, _ = await grants.exchange(raw)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    target = f"{base_url}/reports/v1/editor/{context.report_id}/{context.revision}?subject={subject_id}"
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            try:
                anonymous = await browser.new_page()
                response = await anonymous.goto(target)
                assert response is not None and response.status == 404
                await anonymous.close()
                page = await browser.new_page(viewport={"width": 1280, "height": 720})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.context.add_cookies([{
                    "name": "report_editor_session", "value": session_value,
                    "domain": "127.0.0.1", "path": "/",
                }])
                response = await page.goto(target)
                assert response is not None and response.status == 200
                await page.locator(".evidence-subject-links button").filter(has_text="事实").click()
                fact = page.locator(".evidence-fact-value")
                await fact.wait_for(state="visible", timeout=15000)
                assert "3,600" in (await fact.text_content() or "")
                assert "万元" in (await fact.text_content() or "")
                await page.screenshot(path=str(tmp_path / "online-subject.png"), full_page=True)
                for key, session in grants.repository.sessions.items():
                    grants.repository.sessions[key] = replace(session, expires_at=datetime.now(UTC) - timedelta(seconds=1))
                overlay = page.locator(".evidence-shell")
                await overlay.locator(".evidence-directory-item").filter(has_text="收入明细.csv").click()
                status = overlay.locator('.evidence-status').filter(has_text="编辑会话已过期")
                await status.wait_for(timeout=10000)
                assert "从报告列表重新打开" in (await status.text_content() or "")
                assert await overlay.locator(".evidence-retry").count() == 0
                await page.screenshot(path=str(tmp_path / "session-expired.png"), full_page=True)
                assert errors == []
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("scenario", ["owner_download", "share", "preview_integrity", "download_integrity"])
async def test_evidence_snapshot_download_and_access_failures(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str, scenario: str, browser_download_dir: str,
) -> None:
    from playwright.async_api import async_playwright, expect

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    dataset = index.datasets[0]
    source = next(item for item in index.files if item.resource_id == dataset.file_resource_id)
    original, _ = await editor.workspace.afile_bytes(context.scope["threadId"], source.path)
    capabilities = {"download_original": False} if scenario == "share" else None
    raw, _ = await grants.issue(context, capabilities=capabilities)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options, downloads_path=browser_download_dir)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 720})
                errors = []
                downloads = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("download", lambda download: downloads.append(download))
                await page.goto(f"{base_url}/reports/v1/editor/open/{raw}")
                await page.locator('button[data-action="sources"]').click()
                item = page.locator(".evidence-directory-item").filter(has_text="收入明细.csv")
                await item.wait_for()
                if scenario == "preview_integrity":
                    await editor.workspace.awrite_bytes(context.scope["threadId"], source.path, b"tampered\n", overwrite=True)
                await item.click()
                if scenario == "preview_integrity":
                    await expect(page.locator(".evidence-status")).to_contain_text("文件完整性校验失败")
                    assert await page.locator(".evidence-table").count() == 0
                    assert await page.get_by_role("button", name="下载此快照", exact=True).count() == 0
                    assert await page.locator(".evidence-retry").count() == 0
                else:
                    await expect(page.locator(".evidence-table")).to_contain_text("3600")
                    if scenario == "download_integrity":
                        await editor.workspace.awrite_bytes(context.scope["threadId"], source.path, b"tampered\n", overwrite=True)
                    url = page.url
                    async with page.expect_response(lambda response: response.request.method == "HEAD" and "/download" in response.url) as probe:
                        await page.get_by_role("button", name="下载此快照", exact=True).click()
                    response = await probe.value
                    expected = {"owner_download": 200, "share": 403, "download_integrity": 409}[scenario]
                    assert response.status == expected
                    if scenario == "owner_download":
                        await expect(page.locator(".evidence-dataset-note")).not_to_contain_text("下载失败")
                        deadline = time.monotonic() + 5
                        while not downloads and time.monotonic() < deadline:
                            await page.wait_for_timeout(50)
                        assert len(downloads) == 1
                        assert downloads[0].suggested_filename == "收入明细.csv"
                        assert Path(await downloads[0].path()).read_bytes() == original
                    else:
                        message = "无权下载原始文件" if scenario == "share" else "文件完整性校验失败"
                        await expect(page.locator(".evidence-dataset-note")).to_contain_text(message)
                        assert page.url == url
                        assert downloads == []
                        await expect(page.locator(".evidence-table")).to_contain_text("3600")
                await page.screenshot(path=str(tmp_path / f"evidence-{scenario}.png"), full_page=True)
                await page.set_viewport_size({"width": 390, "height": 844})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await page.screenshot(path=str(tmp_path / f"evidence-{scenario}-mobile.png"), full_page=True)
                await page.locator(".evidence-tab-report").click()
                await expect(page.locator(".evidence-shell")).to_be_hidden()
                assert errors == []
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("leaf_count", [12, 100], ids=["small", "scale"])
async def test_shared_fact_dependencies_expand_in_batches_with_real_backend(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str, leaf_count: int,
) -> None:
    from playwright.async_api import async_playwright, expect
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    entry = index.fact_files[0]
    source = next(item for item in index.files if item.resource_id == entry.file_resource_id)
    thread = context.scope["threadId"]
    bundle = json.loads(await editor.workspace.aread_text(thread, source.path))
    template = bundle["metrics"][0]
    leaves = [f"fact-{position:016x}" for position in range(leaf_count)]
    derived = ["fact-" + "b" * 16, "fact-" + "c" * 16]
    bundle["metrics"] = [dict(template, factId=key, metricCodes=["shared_income"])
                         for key in leaves]
    bundle["derivedMetrics"] = [
        {"factId": key, "code": f"ratio_{position}", "kind": "ratio",
         "numeratorMetric": "shared_income", "denominatorMetric": "shared_income",
         "value": 1.0, "unit": "倍", "warnings": []}
        for position, key in enumerate(derived)
    ]
    content = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
    await editor.workspace.awrite_bytes(thread, source.path, content, overwrite=True)
    subject = index.subject_bindings[0]
    ref = subject.fact_refs[0]
    subject = subject.model_copy(update={"fact_refs": tuple(
        ref.model_copy(update={"fact_key": key, "fact_kind": "derived", "json_pointer": f"/derivedMetrics/{position}"})
        for position, key in enumerate(derived)
    )})
    updated = index.model_copy(update={
        "files": tuple(item.model_copy(update={"size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
                       if item.resource_id == source.resource_id else item for item in index.files),
        "subject_bindings": (subject,), "tables": (),
    })
    await editor.workspace.awrite_bytes(thread, "reports/revision-1/trace-index-v1.json", encode_trace_index(updated), overwrite=True)
    manifest = await register_trace_manifest(editor.workspace, thread, updated, overwrite=True)
    context = context.model_copy(update={"artifact_manifest": manifest})
    state = SimpleNamespace(payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"{base_url}/reports/v1/editor/open/{raw}")
                await page.locator('button[data-action="sources"]').click()
                await page.locator(".evidence-directory-item").filter(has_text="正文引用").click()
                await page.get_by_role("button", name="展开", exact=True).click()
                # 批次坐标与节点数量断言针对 2D DOM；默认关系图仍为 3D。
                await page.get_by_role("button", name="切换到 2D 关系图", exact=True).click()
                await expect(page.locator(".evidence-node")).to_have_count(3)
                positions = "nodes => Object.fromEntries(nodes.map(node => [node.dataset.evidenceNode, [node.style.left, node.style.top]]))"
                original = await page.locator(".evidence-node").evaluate_all(positions)
                title = await page.locator(".evidence-object-title").text_content()
                batch_seconds = []
                for key, edge_count in zip(derived, (leaf_count + 2, leaf_count * 2 + 2), strict=True):
                    await page.locator(f'[data-evidence-node="fact:analysis_001/{key}"]').click()
                    started = time.monotonic()
                    await page.locator(".evidence-branch-load").click()
                    await expect(page.get_by_role("button", name="已加载登记关系", exact=True)).to_be_visible()
                    batch_seconds.append(time.monotonic() - started)
                    await expect(page.locator(".evidence-node")).to_have_count(leaf_count + 3)
                    await expect(page.locator(".evidence-graph-edge")).to_have_count(edge_count)
                    current = await page.locator(".evidence-node").evaluate_all(positions)
                    for identity, position in original.items():
                        assert current[identity] == position
                    original = current
                    assert await page.locator(".evidence-object-title").text_content() == title
                    assert not await page.locator('[data-evidence="back"]').is_enabled()
                await expect(page.locator(".evidence-graph-edge.is-preview")).to_have_count(leaf_count + 1)
                assert await page.locator(".evidence-graph-map").evaluate("""map => {
                    const nodes = [...map.querySelectorAll('.evidence-node')].map(node => ({
                        id: node.dataset.evidenceNode, x: node.offsetLeft, y: node.offsetTop,
                        w: node.offsetWidth, h: node.offsetHeight,
                    }));
                    if (nodes.some((node, i) => nodes.slice(i + 1).some(other =>
                        node.x < other.x + other.w && other.x < node.x + node.w &&
                        node.y < other.y + other.h && other.y < node.y + node.h))) return false;
                    for (const edge of map.querySelectorAll('.evidence-graph-edge')) {
                        const obstacles = nodes.filter(node => node.id !== edge.dataset.from && node.id !== edge.dataset.to);
                        for (let offset = 0; offset < edge.getTotalLength(); offset += 4) {
                            const point = edge.getPointAtLength(offset);
                            if (obstacles.some(node => point.x > node.x && point.x < node.x + node.w &&
                                point.y > node.y && point.y < node.y + node.h)) return false;
                        }
                    }
                    return true;
                }""")
                await page.locator(".evidence-preview-enter").click()
                await expect(page.locator(".evidence-fact-value")).to_contain_text("1")
                await page.locator('[data-evidence="back"]').click()
                await expect(page.locator(".evidence-eyebrow")).to_have_text("引用")
                assert await page.locator(".evidence-node").evaluate_all(positions) == original
                await page.set_viewport_size({"width": 390, "height": 844})
                await page.get_by_role("button", name="查看关系图", exact=True).click()
                await page.locator(f'[data-evidence-node="fact:analysis_001/{leaves[-1]}"]').click()
                await expect(page.locator(".evidence-graph-edge.is-preview")).to_have_count(2)
                await page.get_by_role("button", name="定位当前对象", exact=True).click()
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await page.screenshot(path=str(tmp_path / "real-shared-dependencies-mobile.png"), full_page=True)
                assert errors == []
                print(f"shared-dependencies: browser={evidence_browser_engine} nodes={leaf_count + 3} edges={leaf_count * 2 + 2} batches={batch_seconds}")
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("kind", ["chart", "chart_caption", "duplicate"])
async def test_real_chart_subject_locates_image_or_caption_without_guessing(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str, kind: str,
) -> None:
    from PIL import Image
    from playwright.async_api import async_playwright, expect
    from smart_reporting.reporting.tests.test_report_editor_trace import _make_editor
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.trace.contracts_v1 import SubjectBindingV1, SubjectLocatorV1
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    editor, grants, workspace = await _make_editor(tmp_path, with_chart_trace=True, with_fact_file=True, with_drilldown=True)
    state = await editor.state_repository.get("report-1")
    from smart_reporting.report_editor import ReportEditorContext

    context = ReportEditorContext.model_validate(state.payload["reportEditorContexts"]["1"])
    await editor.read_document(context)
    index = await editor.trace.load_index(context)
    thread = context.scope["threadId"]
    chart = index.chart_traces[0]
    source = next(file for file in index.files if file.resource_id == chart.image_file_resource_id)
    image = io.BytesIO()
    Image.new("RGB", (240, 120), "#007ea7").save(image, format="PNG")
    content = image.getvalue()
    await workspace.awrite_bytes(thread, source.path, content, overwrite=True)
    subject = SubjectBindingV1(
        subjectId="sub-" + "0" * 16, subjectKind="chart_caption" if kind == "chart_caption" else "chart",
        locator=SubjectLocatorV1(chartId=chart.chart_id), subjectSha256="a" * 64,
        factRefs=index.subject_bindings[0].fact_refs,
    )
    updated = index.model_copy(update={
        "files": tuple(file.model_copy(update={"size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
                       if file.resource_id == source.resource_id else file for file in index.files),
        "subject_bindings": (subject,),
    })
    await workspace.awrite_bytes(thread, "reports/revision-1/trace-index-v1.json", encode_trace_index(updated), overwrite=True)
    manifest = await register_trace_manifest(workspace, thread, updated, overwrite=True)
    job = {**context.job, "render": {**context.job.get("render", {}), "images": [{
        "path": source.path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
    }]}}
    context = context.model_copy(update={"artifact_manifest": manifest, "job": job})
    state = SimpleNamespace(payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))
    markdown = "# 报告\n\n![趋势](chart-001.png)\n\n*图表：成本趋势*\n"
    if kind == "duplicate":
        markdown += "\n![重复](chart-001.png)\n"
    await workspace.awrite_text(thread, "reports/revision-1/draft/report.md", markdown)
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                exchange = await page.request.get(f"{base_url}/reports/v1/editor/open/{raw}")
                assert exchange.status == 200
                await page.goto(f"{base_url}/reports/v1/editor/{context.report_id}/1?subject={subject.subject_id}")
                await page.locator(".evidence-subject-links").wait_for()
                await page.get_by_role("button", name="定位正文", exact=True).click()
                await expect(page.locator(".evidence-shell")).to_be_hidden()
                if kind == "duplicate":
                    await expect(page.locator(".save-state-label")).to_contain_text("无法确认该图表")
                    await expect(page.locator(".report-located-subject")).to_have_count(0)
                else:
                    target = page.locator(".report-located-subject")
                    await expect(target).to_have_count(1)
                    if kind == "chart_caption":
                        await expect(target).to_contain_text("图表：成本趋势")
                        await page.keyboard.type("X")
                        await expect(target).to_contain_text("X图表：成本趋势")
                    else:
                        await expect(target.locator("img[src]")).to_have_count(1)
                    await expect(page.locator(".ProseMirror img[src]")).to_have_count(1)
                    assert await page.locator(".ProseMirror img[src]").evaluate("image => image.complete && image.naturalWidth === 240")
                    assert await page.evaluate("document.activeElement.classList.contains('ProseMirror')")
                    await page.screenshot(path=str(tmp_path / f"real-{kind}-location.png"), full_page=True)
                assert errors == []
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_real_chart_sources_page_recover_and_restore_browser_state(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str,
) -> None:
    from urllib.parse import parse_qs, urlsplit

    from matplotlib.figure import Figure
    from playwright.async_api import async_playwright, expect
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.trace.contracts_v1 import ChartTraceV1, TraceFileRefV1, derive_resource_id
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    thread = context.scope["threadId"]
    rows = [[f"P{position:02d}", 1000 + position] for position in range(1, 22)]
    figure = Figure(figsize=(6, 3))
    axes = figure.subplots()
    axes.plot([row[0] for row in rows], [row[1] for row in rows])
    axes.set_title("Registered revenue series")
    axes.tick_params(axis="x", labelrotation=90)
    figure.tight_layout()
    image = io.BytesIO()
    figure.savefig(image, format="png")
    files = []
    contents = [image.getvalue()]
    paths = ["reports/revision-1/chart-real.png"]
    for role, plot_rows in (("main", rows), ("short", rows[:2])):
        paths.append(f"reports/revision-1/chart-real-{role}.chart-input.json")
        contents.append(json.dumps({
            "schema": "chart-input/v1", "chartId": "chart_real", "role": role,
            "source": {"analysisId": "analysis_001"}, "columns": ["period", "revenue"],
            "rows": plot_rows, "rowCount": len(plot_rows),
        }).encode())
    for path, content in zip(paths, contents, strict=True):
        await editor.workspace.awrite_bytes(thread, path, content)
        files.append(TraceFileRefV1(
            resourceId=derive_resource_id(path), path=path,
            mediaType="image/png" if path.endswith(".png") else "application/json",
            size=len(content), sha256=hashlib.sha256(content).hexdigest(),
        ))
    chart = ChartTraceV1(
        chartId="chart_real", imageFileResourceId=files[0].resource_id,
        plotDataFileResourceIds=tuple(file.resource_id for file in files[1:]),
        datasetIds=(index.datasets[0].dataset_id,),
        transformNotes=("登记的完整期间序列，未按当前引用筛选",),
    )
    updated = index.model_copy(update={"files": (*index.files, *files), "chart_traces": (chart,)})
    await editor.workspace.awrite_bytes(thread, "reports/revision-1/trace-index-v1.json", encode_trace_index(updated), overwrite=True)
    manifest = await register_trace_manifest(editor.workspace, thread, updated, overwrite=True)
    context = context.model_copy(update={"artifact_manifest": manifest})
    state = SimpleNamespace(payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                offsets = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: offsets.append(int(parse_qs(urlsplit(request.url).query).get("offset", ["0"])[0]))
                        if "/api/charts/chart_real/source?" in request.url else None)
                exchange = await page.request.get(f"{base_url}/reports/v1/editor/open/{raw}")
                assert exchange.status == 200
                await page.goto(f"{base_url}/reports/v1/editor/{context.report_id}/1")
                await page.locator('[data-action="sources"]').click()
                await page.locator(".evidence-directory-item").filter(has_text="chart_real").click()
                main_table = page.locator(".evidence-table").first
                await expect(main_table.locator("tr:has(td)")).to_have_count(20)
                await expect(main_table.locator("tr:has(td)").first).to_have_text("P011001")
                await expect(page.locator(".evidence-chart-info")).to_contain_text(chart.transform_notes[0])
                await expect(page.locator(".evidence-plot-range").first).to_contain_text("共 21 行")
                await editor.workspace.awrite_bytes(thread, paths[1], contents[1] + b" ", overwrite=True)
                async with page.expect_response(lambda response: "/api/charts/chart_real/source?" in response.url) as failed:
                    await page.locator(".evidence-more").click()
                assert (await failed.value).status == 409
                await expect(page.locator(".evidence-more-error")).to_be_visible()
                await expect(main_table.locator("tr:has(td)")).to_have_count(20)
                await expect(page.locator(".evidence-more")).to_be_enabled()
                await editor.workspace.awrite_bytes(thread, paths[1], contents[1], overwrite=True)
                await page.locator(".evidence-more").click()
                await expect(main_table.locator("tr:has(td)")).to_have_count(1)
                await expect(main_table.locator("tr:has(td)")).to_have_text("P211021")
                await expect(page.locator(".evidence-plot-range").last).to_have_text("共 2 行 · 当前页无预览记录")
                await page.get_by_role("button", name="展开", exact=True).click()
                await page.get_by_role("button", name="切换到关系列表", exact=True).click()
                # 关系列表与来源目录使用同一显示名：文件名 → 业务名称 → 数据集 ID。
                dataset = index.datasets[0]
                dataset_label = dataset.filename or dataset.business_label or dataset.dataset_id
                await page.locator(".evidence-relation-list button").filter(has_text=dataset_label).click()
                await expect(page.locator(".evidence-eyebrow")).to_have_text("快照")
                await page.locator('[data-evidence="back"]').click()
                await expect(main_table.locator("tr:has(td)")).to_have_text("P211021")
                assert offsets == [0, 20, 20]
                await page.reload()
                await page.locator('[data-action="sources"]').click()
                await expect(main_table.locator("tr:has(td)")).to_have_text("P211021")
                assert offsets == [0, 20, 20, 20]
                await page.locator(".evidence-previous").click()
                await expect(main_table.locator("tr:has(td)")).to_have_count(20)
                await expect(main_table.locator("tr:has(td)").first).to_have_text("P011001")
                await page.set_viewport_size({"width": 390, "height": 844})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await page.screenshot(path=str(tmp_path / "real-chart-source-mobile.png"), full_page=True)
                assert offsets == [0, 20, 20, 20, 0]
                assert errors == []
            finally:
                await browser.close()
    finally:
        await editor.workspace.awrite_bytes(thread, paths[1], contents[1], overwrite=True)
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_real_branch_integrity_failure_preserves_graph_and_recovers(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str,
) -> None:
    from playwright.async_api import async_playwright, expect
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    source = next(item for item in index.files if item.resource_id == index.fact_files[0].file_resource_id)
    thread = context.scope["threadId"]
    bundle = json.loads(await editor.workspace.aread_text(thread, source.path))
    leaf = bundle["metrics"][0]["factId"]
    derived = "fact-" + "b" * 16
    bundle["derivedMetrics"] = [{
        "factId": derived, "code": "income_ratio", "kind": "ratio",
        "numeratorMetric": "income_total", "denominatorMetric": "income_total",
        "value": 1.0, "unit": "倍", "warnings": [],
    }]
    content = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
    await editor.workspace.awrite_bytes(thread, source.path, content, overwrite=True)
    subject = index.subject_bindings[0]
    ref = subject.fact_refs[0].model_copy(update={
        "fact_key": derived, "fact_kind": "derived", "json_pointer": "/derivedMetrics/0",
    })
    subject = subject.model_copy(update={"fact_refs": (ref,)})
    updated = index.model_copy(update={
        "files": tuple(item.model_copy(update={"size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
                       if item.resource_id == source.resource_id else item for item in index.files),
        "subject_bindings": (subject,), "tables": (),
    })
    await editor.workspace.awrite_bytes(thread, "reports/revision-1/trace-index-v1.json", encode_trace_index(updated), overwrite=True)
    manifest = await register_trace_manifest(editor.workspace, thread, updated, overwrite=True)
    context = context.model_copy(update={"artifact_manifest": manifest})
    state = SimpleNamespace(payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                exchange = await page.request.get(f"{base_url}/reports/v1/editor/open/{raw}")
                assert exchange.status == 200
                await page.goto(f"{base_url}/reports/v1/editor/{context.report_id}/1?subject={subject.subject_id}")
                await page.get_by_role("button", name="展开", exact=True).click()
                # 关系图默认 3D；该回放检查 2D DOM 节点坐标与恢复契约，显式切换模式。
                await page.get_by_role("button", name="切换到 2D 关系图", exact=True).click()
                await expect(page.locator(".evidence-node")).to_have_count(2)
                positions = "nodes => Object.fromEntries(nodes.map(node => [node.dataset.evidenceNode, [node.style.left, node.style.top]]))"
                original = await page.locator(".evidence-node").evaluate_all(positions)
                title = await page.locator(".evidence-object-title").text_content()
                preview_fits = """preview => {
                    const boxes = [...preview.children].filter(child => child.textContent.trim()).map(child => child.getBoundingClientRect());
                    const parent = preview.getBoundingClientRect();
                    return boxes.every((box, i) => box.left >= parent.left && box.right <= parent.right &&
                        boxes.slice(i + 1).every(other => !(box.left < other.right && other.left < box.right &&
                            box.top < other.bottom && other.top < box.bottom)));
                }"""
                await page.locator(f'[data-evidence-node="fact:analysis_001/{derived}"]').click()
                await editor.workspace.awrite_bytes(thread, source.path, content + b" ", overwrite=True)
                async with page.expect_response(lambda response: "/api/facts/" in response.url) as failed:
                    await page.locator(".evidence-branch-load").click()
                response = await failed.value
                assert response.status == 409
                assert (await response.json())["detail"]["code"] == "snapshot_integrity_failed"
                await expect(page.get_by_role("button", name="重试加载关系", exact=True)).to_be_visible()
                assert await page.locator(".evidence-preview").evaluate(preview_fits)
                assert await page.locator(".evidence-node").evaluate_all(positions) == original
                await expect(page.locator(".evidence-graph-edge")).to_have_count(1)
                assert await page.locator(".evidence-object-title").text_content() == title
                await expect(page.locator('[data-evidence="back"]')).to_be_disabled()
                await page.screenshot(path=str(tmp_path / "real-branch-integrity-failed.png"), full_page=True)
                await page.set_viewport_size({"width": 390, "height": 844})
                await page.get_by_role("button", name="查看关系图", exact=True).click()
                assert await page.locator(".evidence-preview").evaluate(preview_fits)
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await page.screenshot(path=str(tmp_path / "real-branch-integrity-mobile.png"), full_page=True)
                await page.get_by_role("button", name="返回详情", exact=True).click()
                await page.set_viewport_size({"width": 1280, "height": 900})

                await editor.workspace.awrite_bytes(thread, source.path, content, overwrite=True)
                async with page.expect_response(lambda response: "/api/facts/" in response.url) as recovered:
                    await page.locator(".evidence-branch-load").click()
                assert (await recovered.value).status == 200
                await expect(page.get_by_role("button", name="已加载登记关系", exact=True)).to_be_disabled()
                await expect(page.locator(".evidence-node")).to_have_count(3)
                await expect(page.locator(".evidence-graph-edge")).to_have_count(2)
                current = await page.locator(".evidence-node").evaluate_all(positions)
                for identity, position in original.items():
                    assert current[identity] == position
                assert f"fact:analysis_001/{leaf}" in current
                assert await page.locator(".evidence-object-title").text_content() == title
                await expect(page.locator('[data-evidence="back"]')).to_be_disabled()
                await page.locator(".evidence-preview-enter").click()
                await expect(page.locator(".evidence-fact-value")).to_contain_text("1")
                await page.locator('[data-evidence="back"]').click()
                await expect(page.locator(".evidence-eyebrow")).to_have_text("引用")
                assert await page.locator(".evidence-node").evaluate_all(positions) == current
                await page.screenshot(path=str(tmp_path / "real-branch-integrity-recovered.png"), full_page=True)
                assert errors == []
            finally:
                await browser.close()
    finally:
        await editor.workspace.awrite_bytes(thread, source.path, content, overwrite=True)
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_high_fanout_graph_keeps_positions_and_last_node_accessible(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str,
) -> None:
    from playwright.async_api import async_playwright, expect
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    template = index.subject_bindings[0]
    subjects = tuple(template.model_copy(update={
        "subject_id": f"sub-{position:016x}", "claim_id": f"claim-{position}",
    }) for position in range(300))
    updated = index.model_copy(update={"subject_bindings": subjects})
    thread = context.scope["threadId"]
    await editor.workspace.awrite_bytes(thread, "reports/revision-1/trace-index-v1.json", encode_trace_index(updated), overwrite=True)
    manifest = await register_trace_manifest(editor.workspace, thread, updated, overwrite=True)
    context = context.model_copy(update={"artifact_manifest": manifest})
    state = SimpleNamespace(payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            launch_options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**launch_options)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"{base_url}/reports/v1/editor/open/{raw}")
                await page.locator('button[data-action="sources"]').click()
                await page.locator(".evidence-directory-item").filter(has_text="正文引用").first.click()
                started = time.monotonic()
                await page.locator(".evidence-subject-links button").filter(has_text="事实").click()
                # 该规模回放断言 2D 卡片坐标；产品默认模式仍为 3D。
                await page.get_by_role("button", name="切换到 2D 关系图", exact=True).click()
                await expect(page.locator(".evidence-node")).to_have_count(301, timeout=15000)
                load_seconds = time.monotonic() - started
                await expect(page.locator(".evidence-relations-note")).to_contain_text("已加载 301 个节点 · 局部关系")
                assert await page.locator(".evidence-graph-edge").count() == 300
                positions = "nodes => Object.fromEntries(nodes.map(node => [node.dataset.evidenceNode, [parseFloat(node.style.left), parseFloat(node.style.top)]]))"
                original = await page.locator(".evidence-node").evaluate_all(positions)
                values = list(original.values())
                for offset, (x, y) in enumerate(values):
                    assert x >= 0 and y >= 0
                    for other_x, other_y in values[offset + 1:]:
                        assert abs(x - other_x) >= 170 or abs(y - other_y) >= 76
                last = page.locator(f'[data-evidence-node="subject:{subjects[-1].subject_id}"]')
                title = await page.locator(".evidence-object-title").text_content()
                started = time.monotonic()
                await last.click()
                await expect(last).to_have_attribute("aria-pressed", "true")
                preview_seconds = time.monotonic() - started
                assert await page.locator(".evidence-node").evaluate_all(positions) == original
                assert await page.locator(".evidence-object-title").text_content() == title
                await page.locator(".evidence-preview-enter").click()
                await expect(page.locator(".evidence-eyebrow")).to_have_text("引用")
                await page.locator('[data-evidence="back"]').click()
                await expect(page.locator(".evidence-fact-value")).to_contain_text("3,600")
                assert await page.locator(".evidence-node").evaluate_all(positions) == original
                await page.set_viewport_size({"width": 390, "height": 844})
                await page.get_by_role("button", name="查看关系图", exact=True).click()
                await page.get_by_role("button", name="缩小关系图", exact=True).click()
                await last.click()
                await expect(last).to_have_attribute("aria-pressed", "true")
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await page.screenshot(path=str(tmp_path / "high-fanout-graph-mobile.png"), full_page=True)
                await page.get_by_role("button", name="定位当前对象", exact=True).click()
                current = page.locator(".evidence-node.is-current")
                await expect(current).to_be_focused()
                assert await current.evaluate("""node => {
                    const nodeRect = node.getBoundingClientRect();
                    const viewport = document.querySelector('.evidence-graph-scroll').getBoundingClientRect();
                    return nodeRect.left >= viewport.left && nodeRect.right <= viewport.right &&
                        nodeRect.top >= viewport.top && nodeRect.bottom <= viewport.bottom;
                }""")
                await expect(last).to_have_attribute("aria-pressed", "true")
                assert await page.locator(".evidence-object-title").text_content() == title
                assert await page.locator(".evidence-node").evaluate_all(positions) == original
                await page.screenshot(path=str(tmp_path / "high-fanout-current-mobile.png"), full_page=True)
                await page.get_by_role("button", name="重置视图", exact=True).click()
                assert await page.locator(".evidence-graph-scroll").evaluate("node => node.scrollLeft === 0 && node.scrollTop === 0")
                await page.get_by_role("button", name="返回详情", exact=True).click()
                await expect(page.get_by_role("button", name="查看关系图", exact=True)).to_be_focused()
                assert errors == []
                print(f"high-fanout: browser={evidence_browser_engine} nodes=301 edges=300 load={load_seconds:.3f}s preview={preview_seconds:.3f}s")
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_large_snapshot_pagination_and_expired_cursor_recovery(
    tmp_path: Path, frontend_built: None, monkeypatch, evidence_browser_engine: str,
) -> None:
    from playwright.async_api import async_playwright, expect
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.trace import dataset_service
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    dataset = index.datasets[0]
    source = next(item for item in index.files if item.resource_id == dataset.file_resource_id)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["record", "region", "note"])
    writer.writerows((f"ROW{position:06d}", "华东" if position % 2 else "华北", "明细" * 256) for position in range(20000))
    content = buffer.getvalue().encode("utf-8")
    assert len(content) > 29 * 1024 * 1024
    updated_file = source.model_copy(update={"size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    updated_index = index.model_copy(update={
        "files": tuple(updated_file if item.resource_id == source.resource_id else item
            for item in index.files if item.resource_id in (source.resource_id, index.markdown_file_resource_id)),
        "datasets": (dataset.model_copy(update={"row_count": 20000}),),
        "fact_files": (), "subject_bindings": (), "tables": (),
    })
    thread = context.scope["threadId"]
    await editor.workspace.awrite_bytes(thread, source.path, content, overwrite=True)
    await editor.workspace.awrite_bytes(thread, "reports/revision-1/trace-index-v1.json", encode_trace_index(updated_index), overwrite=True)
    manifest = await register_trace_manifest(editor.workspace, thread, updated_index, overwrite=True)
    context = context.model_copy(update={"artifact_manifest": manifest})
    state = SimpleNamespace(payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))
    clock = [time.time()]
    monkeypatch.setattr(dataset_service, "time", SimpleNamespace(time=lambda: clock[0]))
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            launch_options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**launch_options)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"{base_url}/reports/v1/editor/open/{raw}")
                await page.locator('button[data-action="sources"]').click()
                await page.locator(".evidence-directory-item").filter(has_text="收入明细.csv").click()
                scope = page.locator(".evidence-dataset-scope")
                await expect(scope).to_contain_text("完整快照共 20000 行 · 预览序号 1–50")
                await expect(page.locator(".evidence-table tr:has(td)")).to_have_count(50)
                await page.get_by_role("button", name="下一页", exact=True).click()
                await expect(scope).to_contain_text("预览序号 51–100")
                await page.locator(".evidence-filter").fill("ROW000075")
                await expect(page.locator(".evidence-filter-count")).to_have_text("本页匹配 1 / 50 行")
                await expect(page.locator("td.evidence-row-number")).to_have_text("76")
                await page.locator(".evidence-column-resize").first.press("ArrowRight")
                column_width = await page.locator(".evidence-table col:not(.evidence-row-number)").first.get_attribute("style")
                await page.reload()
                await page.locator('button[data-action="sources"]').click()
                await expect(scope).to_contain_text("预览序号 51–100")
                await expect(page.locator(".evidence-filter")).to_have_value("ROW000075")
                assert await page.locator(".evidence-table col:not(.evidence-row-number)").first.get_attribute("style") == column_width
                await expect(page.locator("td.evidence-row-number")).to_have_text("76")
                clock[0] += 7200
                for _ in range(2):
                    async with page.expect_response(lambda response: "/preview?" in response.url and response.status == 400):
                        await page.get_by_role("button", name="下一页", exact=True).click()
                    await expect(page.locator(".evidence-more-error")).to_contain_text("分页游标")
                    await expect(page.get_by_role("button", name="下一页", exact=True)).to_be_enabled()
                reset = page.get_by_role("button", name="重新加载第一页", exact=True)
                await expect(reset).to_have_count(1)
                await expect(scope).to_contain_text("预览序号 51–100")
                await expect(page.locator(".evidence-table")).to_contain_text("ROW000075")
                await page.set_viewport_size({"width": 390, "height": 844})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert await page.locator(".evidence-more-error").evaluate(
                    "node => node.getBoundingClientRect().top >= document.querySelector('.evidence-more').getBoundingClientRect().bottom"
                )
                await page.screenshot(path=str(tmp_path / "large-snapshot-expired-cursor.png"), full_page=True)
                await page.set_viewport_size({"width": 1280, "height": 900})
                await reset.click()
                await expect(scope).to_contain_text("预览序号 1–50")
                await expect(page.locator(".evidence-filter-count")).to_contain_text("本页匹配 0 / 50 行")
                await page.get_by_role("button", name="下一页", exact=True).click()
                await expect(scope).to_contain_text("预览序号 51–100")
                clock[0] += 7200
                await page.reload()
                await page.locator('button[data-action="sources"]').click()
                await expect(page.locator(".evidence-status")).to_contain_text("分页游标")
                assert await page.locator(".evidence-table").count() == 0
                await page.get_by_role("button", name="重新打开第一页", exact=True).click()
                await expect(scope).to_contain_text("预览序号 1–50")
                await page.locator(".evidence-filter").fill("")
                await expect(page.locator(".evidence-table tr:has(td)")).to_have_count(50)
                await expect(page.locator(".evidence-table")).to_contain_text("ROW000000")
                await page.set_viewport_size({"width": 390, "height": 844})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await page.screenshot(path=str(tmp_path / "large-snapshot-cursor-recovery.png"), full_page=True)
                assert errors == []
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_cached_evidence_revalidates_current_draft_without_reloading_registered_fact(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str,
) -> None:
    from playwright.async_api import async_playwright, expect

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    markdown = await editor.workspace.aread_text(context.scope["threadId"], context.markdown_path)
    markdown += "\n本期收入3600万元。[[claim:claim-1]]\n"
    await editor.workspace.awrite_text(
        context.scope["threadId"], "reports/revision-1/draft/report.md", markdown,
    )
    index = await editor.trace.load_index(context)
    subject_id = index.subject_bindings[0].subject_id
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 720})
                facts = []
                errors = []
                page.on("request", lambda request: facts.append(request.url) if "/api/facts/" in request.url else None)
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"{base_url}/reports/v1/editor/open/{raw}?subject={subject_id}")
                await page.locator('button[data-action="sources"]').click()
                # 引用显示名为去掉 sub- 前缀后的 6 位短号（与前端 subjectLabel 一致）。
                subject_short = subject_id.removeprefix("sub-")[:6]
                await page.locator(".evidence-directory-item").filter(has_text=f"#{subject_short}").first.click()
                await page.locator(".evidence-subject-links button").filter(has_text="事实").click()
                citation = page.locator('[data-status-row="citation"]')
                await expect(citation).to_contain_text("引用有效")
                await expect(page.locator(".evidence-fact-value")).to_contain_text("3,600 万元")
                verification = await page.locator('[data-status-row="verification"]').text_content()
                await page.locator(".evidence-tab-report").click()
                paragraph = page.locator(".ProseMirror p").filter(has_text="本期收入3600万元")
                await paragraph.click()
                await page.keyboard.press("Home")
                for _ in "本期收入":
                    await page.keyboard.press("ArrowRight")
                for _ in "3600":
                    await page.keyboard.press("Shift+ArrowRight")
                await page.keyboard.type("3800")
                paragraph = page.locator(".ProseMirror p").filter(has_text="本期收入3800万元")
                await expect(paragraph).to_contain_text("本期收入3800万元")
                for _ in "3800":
                    await page.keyboard.press("Shift+ArrowLeft")
                assert await page.evaluate("getSelection().toString()") == "3800"
                await page.locator('button[data-action="sources"]').click()
                await expect(citation).to_contain_text("内容已变更")
                await expect(page.locator(".evidence-warning")).to_contain_text("暂不计算差额")
                await page.locator(".evidence-tab-report").click()
                assert await page.evaluate("getSelection().toString()") == "3800"
                await expect(paragraph).to_contain_text("本期收入3800万元")
                await page.locator('button[data-action="save"]').click()
                await expect(page.locator(".save-state-label")).to_contain_text("已保存")
                assert "3800万元" in (await editor.read_document(context)).markdown
                await page.locator('button[data-action="sources"]').click()
                await expect(citation).to_contain_text("内容已变更")
                await expect(page.locator(".evidence-warning")).to_contain_text("暂不计算差额")
                await expect(page.locator('[data-status-row="verification"]')).to_have_text(verification)
                await expect(page.locator(".evidence-fact-value")).to_contain_text("3,600 万元")
                assert len(facts) == 1
                await page.screenshot(path=str(tmp_path / "real-cached-draft-warning.png"), full_page=True)
                await page.locator('.evidence-warning').get_by_role("button", name="定位正文").click()
                await expect(page.locator(".evidence-shell")).to_be_hidden()
                await expect(paragraph).to_contain_text("本期收入3800万元")
                assert errors == []
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_same_fact_subject_tasks_keep_anchor_identity_with_real_backend(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str,
) -> None:
    from playwright.async_api import async_playwright, expect
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    template = index.subject_bindings[0]
    subjects = tuple(template.model_copy(update={
        "subject_id": f"sub-{position:016x}", "claim_id": f"claim-{position + 1}",
    }) for position in range(2))
    assert subjects[0].fact_refs == subjects[1].fact_refs
    updated = index.model_copy(update={"subject_bindings": subjects})
    thread = context.scope["threadId"]
    await editor.workspace.awrite_bytes(thread, "reports/revision-1/trace-index-v1.json", encode_trace_index(updated), overwrite=True)
    manifest = await register_trace_manifest(editor.workspace, thread, updated, overwrite=True)
    context = context.model_copy(update={"artifact_manifest": manifest})
    state = SimpleNamespace(payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))
    markdown = await editor.workspace.aread_text(thread, context.markdown_path)
    for subject in subjects:
        markdown += f"\n收入3600万元。[[claim:{subject.claim_id}]][[citation:{subject.subject_id}]]\n"
    await editor.workspace.awrite_text(thread, "reports/revision-1/draft/report.md", markdown)
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"{base_url}/reports/v1/editor/open/{raw}")
                url = f"{base_url}/reports/v1/editor/{context.report_id}/{context.revision}"
                await page.goto(f"{url}?subject={subjects[0].subject_id}")
                await page.locator(".evidence-subject-links button").filter(has_text="事实").click()
                await expect(page.locator(".evidence-fact-value")).to_contain_text("3,600 万元")
                await expect(page.locator('[data-evidence="back"]')).to_be_enabled()
                first_key = await page.locator('.evidence-tab[aria-selected="true"]').get_attribute("data-evidence-tab")
                await page.goto(f"{url}?subject={subjects[1].subject_id}")
                await page.locator(".evidence-subject-links").wait_for()
                await expect(page.locator(".evidence-tab-name")).to_have_count(2)
                names = await page.locator(".evidence-tab-name").all_text_contents()
                # 两条引用 ID 前缀相同：短号自动加长到可区分，页签名不再同名。
                assert names[0] != names[1]
                second_key = await page.locator('.evidence-tab[aria-selected="true"]').get_attribute("data-evidence-tab")
                assert first_key != second_key
                await expect(page.locator('[data-evidence="back"]')).to_be_disabled()
                await expect(page.locator('.evidence-tab-stage')).to_have_text(["事实", "引用"])
                await page.goto(f"{url}?subject={subjects[0].subject_id}")
                await expect(page.locator(".evidence-fact-value")).to_contain_text("3,600 万元")
                await expect(page.locator(".evidence-tab-name")).to_have_count(2)
                await expect(page.locator('.evidence-tab[aria-selected="true"]')).to_have_attribute("data-evidence-tab", first_key)
                await expect(page.locator('[data-evidence="back"]')).to_be_enabled()
                await page.locator('[data-evidence="back"]').click()
                await page.locator(".evidence-subject-links").wait_for()
                roots = await page.evaluate("""() => {
                    const key = Object.keys(sessionStorage).find(key => key.startsWith('smart-reporting-evidence:'));
                    return JSON.parse(sessionStorage.getItem(key)).tasks.map(task => task.root.key);
                }""")
                assert roots == [subject.subject_id for subject in subjects]
                await page.screenshot(path=str(tmp_path / "same-fact-independent-subject-tasks.png"), full_page=True)
                assert errors == []
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("ambiguous", [False, True])
async def test_table_subject_locates_current_cell_without_guessing(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str, ambiguous: bool,
) -> None:
    from playwright.async_api import async_playwright, expect
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.trace.contracts_v1 import SubjectLocatorV1
    from smart_reporting.reporting.trace.index_builder import encode_trace_index
    from smart_reporting.reporting.trace.table_builder import render_table_markdown

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    index = await editor.trace.load_index(context)
    subject = index.subject_bindings[0].model_copy(update={
        "subject_kind": "table_cell", "claim_id": None,
        "locator": SubjectLocatorV1(tableId="tbl-1", rowKey="row:cur", columnKey="income_total"),
    })
    updated = index.model_copy(update={"subject_bindings": (subject,)})
    thread = context.scope["threadId"]
    await editor.workspace.awrite_bytes(thread, "reports/revision-1/trace-index-v1.json", encode_trace_index(updated), overwrite=True)
    manifest = await register_trace_manifest(editor.workspace, thread, updated, overwrite=True)
    context = context.model_copy(update={"artifact_manifest": manifest})
    state = SimpleNamespace(payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))
    rows = [["上期", "9,999"], ["本期", "3,600"]]
    if ambiguous:
        rows.append(["本期", "3,600"])
    markdown = "# 报告\n\n" + render_table_markdown("tbl-1", ("income_total",), rows) + "\n"
    await editor.workspace.awrite_text(thread, "reports/revision-1/draft/report.md", markdown)
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                exchange = await page.request.get(f"{base_url}/reports/v1/editor/open/{raw}")
                assert exchange.status == 200
                await page.goto(f"{base_url}/reports/v1/editor/{context.report_id}/{context.revision}?subject={subject.subject_id}")
                await page.locator(".evidence-subject-links").wait_for()
                await page.get_by_role("button", name="定位正文", exact=True).click()
                await expect(page.locator(".evidence-shell")).to_be_hidden()
                if ambiguous:
                    await expect(page.locator(".save-state-label")).to_contain_text("无法确认该单元格")
                    await expect(page.locator(".report-located-subject")).to_have_count(0)
                else:
                    target = page.locator(".ProseMirror tr").nth(2).locator("td").nth(1).locator("p")
                    await expect(target).to_have_class("report-located-subject")
                    await expect(target).to_have_text("3,600")
                    assert await page.evaluate("document.activeElement.classList.contains('ProseMirror')")
                    await page.keyboard.type("X")
                    await expect(target).to_have_text("X3,600")
                    await expect(page.locator(".ProseMirror tr").nth(1)).to_contain_text("9,999")
                    await page.screenshot(path=str(tmp_path / "table-cell-location.png"), full_page=True)
                assert errors == []
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_same_keys_in_two_reports_keep_browser_history_isolated(
    tmp_path: Path, frontend_built: None, evidence_browser_engine: str,
) -> None:
    from playwright.async_api import async_playwright, expect

    editor, grants, first = await _make_editor_with_subject(tmp_path, report_id="report-1")
    second_editor, _, second = await _make_editor_with_subject(tmp_path, report_id="report-2")
    first_index = await editor.trace.load_index(first)
    second_index = await second_editor.trace.load_index(second)
    subject_id = first_index.subject_bindings[0].subject_id
    assert second_index.subject_bindings[0].subject_id == subject_id
    first_ref = first_index.subject_bindings[0].fact_refs[0]
    second_ref = second_index.subject_bindings[0].fact_refs[0]
    assert (first_ref.analysis_id, first_ref.fact_key) == (second_ref.analysis_id, second_ref.fact_key)
    assert first_ref.file_resource_id != second_ref.file_resource_id
    assert first.scope["threadId"] != second.scope["threadId"]
    states = {
        context.workflow_run_id: SimpleNamespace(payload={
            "reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)},
        }) for context in (first, second)
    }
    editor.state_repository = SimpleNamespace(get=AsyncMock(side_effect=lambda run_id: states.get(run_id)))
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base_url, server = _start_server(app)
    try:
        async with async_playwright() as playwright:
            engine = getattr(playwright, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                urls = [f"{base_url}/reports/v1/editor/{context.report_id}/1" for context in (first, second)]
                for context in (first, second):
                    raw, _ = await grants.issue(context)
                    exchange = await page.request.get(f"{base_url}/reports/v1/editor/open/{raw}")
                    assert exchange.status == 200
                await page.goto(f"{urls[0]}?subject={subject_id}")
                await page.locator(".evidence-subject-links button").filter(has_text="事实").click()
                await expect(page.locator(".evidence-fact-value")).to_contain_text("3,600 万元")
                await expect(page.locator('[data-evidence="back"]')).to_be_enabled()
                first_storage = await page.evaluate("sessionStorage.getItem('smart-reporting-evidence:' + location.pathname)")
                assert len(json.loads(first_storage)["tasks"][0]["history"]) > 1

                await page.goto(f"{urls[1]}?subject={subject_id}")
                await page.locator(".evidence-subject-links").wait_for()
                await expect(page.locator(".evidence-tab-name")).to_have_count(1)
                await expect(page.locator('[data-evidence="back"]')).to_be_disabled()
                await expect(page.locator(".evidence-tab-stage")).to_have_text("引用")
                assert await page.evaluate("sessionStorage.getItem('smart-reporting-evidence:/reports/v1/editor/report-1/1')") == first_storage
                await page.locator(".evidence-subject-links button").filter(has_text="事实").click()
                await expect(page.locator(".evidence-fact-value")).to_contain_text("3,600 万元")
                await page.locator('[data-evidence="back"]').click()
                await page.locator(".evidence-subject-links").wait_for()

                await page.goto(f"{urls[0]}?subject={subject_id}")
                await expect(page.locator(".evidence-fact-value")).to_contain_text("3,600 万元")
                await expect(page.locator('[data-evidence="back"]')).to_be_enabled()
                await expect(page.locator(".evidence-tab-name")).to_have_count(1)
                await page.goto(f"{urls[1]}?subject={subject_id}")
                await page.locator(".evidence-subject-links").wait_for()
                await expect(page.locator(".evidence-tab-stage")).to_have_text("引用")
                await expect(page.locator('[data-evidence="forward"]')).to_be_enabled()
                await page.locator('[data-evidence="forward"]').click()
                await expect(page.locator(".evidence-fact-value")).to_contain_text("3,600 万元")
                keys = await page.evaluate("Object.keys(sessionStorage).filter(key => key.startsWith('smart-reporting-evidence:')).sort()")
                assert keys == [f"smart-reporting-evidence:/reports/v1/editor/{context.report_id}/1" for context in (first, second)]
                assert errors == []
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_loads_table_and_trace_panel_opens_csv_preview(
    tmp_path: Path,
    frontend_built: None,
    browser_available: None,
) -> None:
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    thread_id = context.scope["threadId"]
    workspace = editor.workspace

    # 构造包含服务端表格与 claim 的正文；使用 B6 修复后的 table 格式（结束标记前空行）。
    markdown = (
        "# Current report\n\n"
        "## 1. 收入\n\n"
        "本期收入 3,600 元。[[claim:claim-1]]\n\n"
        "[[table:tbl-1]]\n"
        "|  | income_total |\n"
        "| --- | --- |\n"
        "| 本期 | 3,600 |\n"
        "| 上期 | 3,600 |\n\n"
        "[[/table:tbl-1]]\n"
    )
    await workspace.awrite_text(thread_id, context.markdown_path, markdown, overwrite=True)
    await workspace.awrite_text(thread_id, "reports/revision-1/draft/report.md", markdown)

    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))

    # 通过 ASGI 兑换授权拿到会话 cookie，再让真实浏览器访问本地 HTTP 服务。
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        assert response.status_code == 303
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if "report_editor_session=" in c)
        session_value = session_cookie.split(";")[0].split("=")[1]

    base_url, server = _start_server(app)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=_find_chromium(), args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.context.add_cookies(
                [
                    {
                        "name": "report_editor_session",
                        "value": session_value,
                        "domain": "127.0.0.1",
                        "path": "/",
                    }
                ]
            )
            await page.goto(f"{base_url}/reports/v1/editor/{context.report_id}/{context.revision}")

            # 等待编辑器加载完成：状态栏不再显示“载入中”。
            await page.locator(".save-state-label").wait_for(state="visible", timeout=15000)
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent !== '载入中'",
                timeout=15000,
            )

            # table 协议块不可见。
            assert not await page.locator("text=[[table:tbl-1]]").first.is_visible()
            assert not await page.locator("text=[[/table:tbl-1]]").first.is_visible()
            # 表格正常渲染且包含预期数据。
            table = page.locator("table").filter(has_text="income_total")
            await table.wait_for(timeout=5000)
            assert await table.count() == 1
            assert await page.locator("table").filter(has_text="3,600").count() >= 1

            # 来源目录进入快照对象页，完整预览由真实后端提供。
            await page.locator('button[data-action="sources"]').click()
            overlay = page.locator(".evidence-shell")
            await overlay.wait_for(state="visible", timeout=5000)
            assert await overlay.count() == 1
            item = overlay.locator(".evidence-directory-item").filter(has_text="收入明细.csv")
            await item.wait_for(state="visible", timeout=10000)
            await item.click()
            preview = overlay.locator(".evidence-table-wrap")
            await preview.wait_for(state="visible", timeout=5000)
            assert await preview.locator("text=2025-09").count() >= 1
            assert await preview.locator("text=3600").count() >= 1

            # 返回正文，编辑器中的表格保留。
            await overlay.locator(".evidence-tab-report").click()
            await overlay.wait_for(state="hidden", timeout=5000)

            await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_lineage_display_switches_hide_browser_entries_but_keep_editor_usable(
    tmp_path: Path,
    frontend_built: None,
    browser_available: None,
) -> None:
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    editor._lineage_features.update(panel=False, exportSources=False)
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        response = await client.get(
            f"/reports/v1/editor/open/{raw}", follow_redirects=False
        )
        session_value = next(
            value
            for value in response.headers.get_list("set-cookie")
            if "report_editor_session=" in value
        ).split(";")[0].split("=")[1]

    base_url, server = _start_server(app)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                executable_path=_find_chromium(), args=["--no-sandbox"]
            )
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.context.add_cookies([{
                "name": "report_editor_session",
                "value": session_value,
                "domain": "127.0.0.1",
                "path": "/",
            }])
            await page.goto(
                f"{base_url}/reports/v1/editor/{context.report_id}/{context.revision}"
            )
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent !== '载入中'",
                timeout=15000,
            )

            assert await page.locator('button[data-action="sources"]').is_hidden()
            assert await page.locator('button[data-action="save"]').is_visible()
            assert await page.locator('button[data-action="pdf"]').is_visible()
            assert await page.locator('.source-validation-status').is_hidden()
            await page.locator('button[data-action="export-settings"]').click()
            assert await page.locator('input[name="sources"]').is_hidden()
            await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_history_restore_reverts_markdown_and_sources(
    tmp_path: Path,
    frontend_built: None,
    evidence_browser_engine: str,
) -> None:
    """从历史面板恢复 revision 1，正文与来源均回退到旧版本。"""
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    editor, grants, historical = await _make_editor_with_subject(tmp_path)
    thread_id = historical.scope["threadId"]
    workspace = editor.workspace

    new_markdown = "# Current report\n\nRestored later.\n"
    current = historical.model_copy(update={
        "revision": 2,
        "markdown_path": "reports/revision-2/report.md",
        "artifact_manifest": None,
        "job": {
            "jobId": historical.job_id,
            "render": {
                "markdown": {
                    "path": "reports/revision-2/report.md",
                    "sha256": hashlib.sha256(new_markdown.encode()).hexdigest(),
                },
            },
        },
    })
    await workspace.awrite_text(thread_id, current.markdown_path, new_markdown)
    index = await editor.trace.load_index(historical)
    markdown_id = derive_resource_id(current.markdown_path)
    updated = index.model_copy(update={
        "revision": 2, "markdown_file_resource_id": markdown_id,
        "files": tuple(item.model_copy(update={
            "resource_id": markdown_id, "path": current.markdown_path,
            "size": len(new_markdown.encode()), "sha256": hashlib.sha256(new_markdown.encode()).hexdigest(),
        }) if item.resource_id == index.markdown_file_resource_id else item for item in index.files),
    })
    await workspace.awrite_bytes(thread_id, "reports/revision-2/trace-index-v1.json", encode_trace_index(updated))
    manifest = await register_trace_manifest(workspace, thread_id, updated)
    current = current.model_copy(update={"artifact_manifest": manifest})
    state = SimpleNamespace(payload={"reportEditorContexts": {
        "1": historical.model_dump(mode="json", by_alias=True),
        "2": current.model_dump(mode="json", by_alias=True),
    }})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))

    raw, _ = await grants.issue(current)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        assert response.status_code == 303
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if "report_editor_session=" in c)
        session_value = session_cookie.split(";")[0].split("=")[1]

    base_url, server = _start_server(app)
    try:
        from playwright.async_api import async_playwright, expect

        async with async_playwright() as p:
            engine = getattr(p, evidence_browser_engine)
            options = {"executable_path": _find_chromium(), "args": ["--no-sandbox"]} if evidence_browser_engine == "chromium" else {}
            browser = await engine.launch(**options)
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.context.add_cookies(
                [
                    {
                        "name": "report_editor_session",
                        "value": session_value,
                        "domain": "127.0.0.1",
                        "path": "/",
                    }
                ]
            )
            await page.goto(f"{base_url}/reports/v1/editor/{current.report_id}/{current.revision}")

            await page.locator(".save-state-label").wait_for(state="visible", timeout=15000)
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent !== '载入中'",
                timeout=15000,
            )
            # 初始加载当前 revision 2 的正文。
            assert await page.locator("text=Current report").first.is_visible()

            # 在当前修订留下一个打开任务及一个关闭记录，恢复时必须丢弃。
            await page.locator('button[data-action="sources"]').click()
            sources_overlay = page.locator(".evidence-shell")
            await sources_overlay.locator(".evidence-directory-item").filter(has_text="收入明细.csv").click()
            await expect(sources_overlay.locator("table")).to_contain_text("3600")
            await page.locator(".evidence-filter").fill("OLDSTATE")
            await sources_overlay.locator(".evidence-directory-item").filter(has_text="正文引用").click()
            await expect(page.locator(".evidence-eyebrow")).to_have_text("引用")
            await page.locator('.evidence-tab-close[aria-label*="正文引用"]').click()
            await page.get_by_label("全部任务", exact=True).click()
            await expect(page.get_by_role("button", name="恢复最近关闭的任务", exact=True)).to_be_enabled()
            await page.get_by_label("全部任务", exact=True).click()
            await sources_overlay.locator(".evidence-tab-report").click()

            # 打开历史面板并选择 revision 1。
            await page.locator('button[data-action="history"]').click()
            history_overlay = page.locator(".history-panel")
            await history_overlay.wait_for(state="visible", timeout=5000)
            await history_overlay.locator(".history-list").wait_for(timeout=5000)
            await history_overlay.locator(".history-item").filter(has_text="版本 1").wait_for(timeout=10000)
            await history_overlay.locator(".history-item").filter(has_text="版本 1").first.click()

            restore_button = history_overlay.locator("button.history-restore")
            await restore_button.wait_for(state="visible", timeout=5000)

            # 自动确认恢复对话框。
            async def _accept_dialog(dialog) -> None:
                await dialog.accept()

            page.on("dialog", _accept_dialog)
            await restore_button.click()

            # 等待恢复完成：状态栏提示且历史面板关闭。
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent.includes('已恢复第 1 版')",
                timeout=15000,
            )
            await history_overlay.wait_for(state="hidden", timeout=5000)

            # 正文回退到 revision 1（限定在编辑器区域，避免历史差异面板残留文本干扰）。
            await page.wait_for_function(
                "() => { const el = document.querySelector('#report-editor'); return el !== null && el.textContent.includes('报告'); }",
                timeout=15000,
            )
            editor_text = await page.evaluate("() => document.querySelector('#report-editor')?.textContent ?? ''")
            assert "Current report" not in editor_text, f"editor still contains current text: {editor_text!r}"

            # 恢复后新来源目录显示历史登记的数据，不复用旧任务。
            await page.locator('button[data-action="sources"]').click()
            sources_overlay = page.locator(".evidence-shell")
            await sources_overlay.wait_for(state="visible", timeout=5000)
            await expect(page.locator(".evidence-tab-close")).to_have_count(0)
            await page.get_by_label("全部任务", exact=True).click()
            await expect(page.get_by_role("button", name="恢复最近关闭的任务", exact=True)).to_be_disabled()
            await page.get_by_label("全部任务", exact=True).click()
            dataset = sources_overlay.locator(".evidence-directory-item").filter(has_text="收入明细.csv")
            await dataset.wait_for(state="visible", timeout=10000)
            await dataset.click()
            await expect(page.locator(".evidence-filter")).to_have_value("")
            await sources_overlay.locator("table").filter(has_text="3600").wait_for()

            # 恢复后继续编辑；旧文档的书签不能覆盖新选区。
            await sources_overlay.locator(".evidence-tab-report").click()
            paragraph = page.locator("#report-editor .ProseMirror h1").first
            await paragraph.click()
            await page.keyboard.press("End")
            await page.keyboard.type("RESTOREEDIT")
            await expect(paragraph).to_contain_text("RESTOREEDIT")
            for _ in "RESTOREEDIT":
                await page.keyboard.press("Shift+ArrowLeft")
            assert await page.evaluate("getSelection().toString()") == "RESTOREEDIT"
            await page.locator('button[data-action="sources"]').click()
            await expect(sources_overlay.locator("table")).to_contain_text("3600")
            await sources_overlay.locator(".evidence-tab-report").click()
            assert await page.evaluate("getSelection().toString()") == "RESTOREEDIT"
            await page.locator('button[data-action="save"]').click()
            await expect(page.locator(".save-state-label")).to_contain_text("已保存")
            saved = await editor.read_document(current)
            assert "RESTOREEDIT" in saved.markdown
            assert "Current report" not in saved.markdown
            await page.reload()
            await expect(page.locator("#report-editor .ProseMirror")).to_contain_text("RESTOREEDIT")
            await page.locator('button[data-action="sources"]').click()
            await expect(sources_overlay.locator("table")).to_contain_text("3600")
            await page.screenshot(path=str(tmp_path / "history-restore-continued-edit.png"), full_page=True)
            assert errors == []

            await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_dual_window_save_reports_conflict(
    tmp_path: Path,
    frontend_built: None,
    browser_available: None,
) -> None:
    """双窗口编辑：A 保存后 B 再保存应触发 CAS 冲突提示。"""
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        assert response.status_code == 303
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if "report_editor_session=" in c)
        session_value = session_cookie.split(";")[0].split("=")[1]

    base_url, server = _start_server(app)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=_find_chromium(), args=["--no-sandbox"])
            context_a = await browser.new_context(viewport={"width": 1280, "height": 720})
            context_b = await browser.new_context(viewport={"width": 1280, "height": 720})
            for ctx in (context_a, context_b):
                await ctx.add_cookies(
                    [
                        {
                            "name": "report_editor_session",
                            "value": session_value,
                            "domain": "127.0.0.1",
                            "path": "/",
                        }
                    ]
                )
            page_a = await context_a.new_page()
            page_b = await context_b.new_page()

            for page in (page_a, page_b):
                await page.goto(f"{base_url}/reports/v1/editor/{context.report_id}/{context.revision}")
                await page.locator(".save-state-label").wait_for(state="visible", timeout=15000)
                await page.wait_for_function(
                    "() => document.querySelector('.save-state-label')?.textContent !== '载入中'",
                    timeout=15000,
                )

            # 窗口 A 在文档末尾追加内容并手动保存。
            await page_a.locator("#report-editor").click()
            await page_a.keyboard.press("Control+End")
            await page_a.keyboard.type(" edited by window A")
            await page_a.locator('button[data-action="save"]').click()
            await page_a.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent.includes('已保存')",
                timeout=15000,
            )

            # 窗口 B 在不知情的情况下追加内容并保存，应触发 CAS 冲突。
            await page_b.locator("#report-editor").click()
            await page_b.keyboard.press("Control+End")
            await page_b.keyboard.type(" edited by window B")
            await page_b.locator('button[data-action="save"]').click()
            await page_b.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent.includes('保存冲突')",
                timeout=15000,
            )

            await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_repeated_export_creates_sequential_revisions(
    tmp_path: Path,
    frontend_built: None,
    browser_available: None,
) -> None:
    """连续点击导出 PDF，验证生成 revision 2 与 revision 3。"""
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    thread_id = context.scope["threadId"]
    workspace = editor.workspace

    # 为当前 revision 补全 job render 记录与草稿，使导出流程能定位到当前 PDF revision。
    # 使用不含 table 协议块的简单正文，避免 Milkdown 序列化后 table marker 格式被破坏。
    simple_markdown = "# 导出测试\n\n正文内容。\n"
    simple_sha = hashlib.sha256(simple_markdown.encode()).hexdigest()
    context = context.model_copy(update={
        "job": {
            "jobId": context.job_id,
            "status": "validated",
            "render": {
                "markdown": {"path": context.markdown_path, "size": len(simple_markdown.encode()), "sha256": simple_sha},
                "pdf": {"path": "reports/revision-1/report.pdf", "size": 3, "sha256": hashlib.sha256(b"pdf").hexdigest()},
                "word": {"path": "reports/revision-1/report.docx", "size": 4, "sha256": hashlib.sha256(b"word").hexdigest()},
                "images": [],
            },
        },
    })
    await workspace.awrite_text(thread_id, "reports/revision-1/draft/report.md", simple_markdown)

    durable = SimpleNamespace(
        state_version=1,
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}},
    )

    class StateRepository:
        async def get(self, _run_id: str):
            return durable

        async def apply(self, _run_id: str, command, *, expected_version: int):
            assert expected_version == durable.state_version
            payload = durable.payload.copy()
            payload["reportEditorContexts"] = {
                **payload.get("reportEditorContexts", {}),
                str(command.payload["context"]["revision"]): command.payload["context"],
            }
            durable.state_version += 1
            durable.payload = payload

    editor.state_repository = StateRepository()

    class Tools:
        async def _render_report_pair(
            self, _job_id, markdown_path, output_path, *, artifact_manifest, run_context
        ):
            await workspace.awrite_bytes(thread_id, output_path, b"pdf")
            await workspace.awrite_bytes(
                thread_id, output_path.replace(".pdf", ".docx"), b"word"
            )
            stored = run_context.session_state[REPORT_JOBS_STATE_KEY][context.job_id]
            stored["render"] = {
                "markdown": {
                    "path": markdown_path,
                    "size": len((await workspace.aread_text(thread_id, markdown_path)).encode()),
                    "sha256": artifact_manifest["markdown"]["sha256"],
                },
                "pdf": {"path": output_path, "size": 3, "sha256": hashlib.sha256(b"pdf").hexdigest()},
                "word": {
                    "path": output_path.replace(".pdf", ".docx"),
                    "size": 4,
                    "sha256": hashlib.sha256(b"word").hexdigest(),
                },
                "images": [],
            }
            return {"validation": {"ok": True}}

    class Persistence:
        async def persist(self, **_kwargs):
            return None

    class Downloads:
        async def issue(self, **kwargs):
            return "download", ReportDownloadGrant(
                grant_hash="d" * 64, expires_at=datetime(2026, 10, 15, tzinfo=UTC), **kwargs
            )

    class EditorGrants:
        async def issue(self, _context):
            return "editor", datetime(2026, 10, 15, tzinfo=UTC)

    editor.report_tools = Tools()
    editor.artifact_persistence = Persistence()
    editor.download_grants = Downloads()
    editor.editor_grants = EditorGrants()
    editor.public_base_url = "https://reports.example.com"

    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        assert response.status_code == 303
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if "report_editor_session=" in c)
        session_value = session_cookie.split(";")[0].split("=")[1]

    base_url, server = _start_server(app)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=_find_chromium(), args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.context.add_cookies(
                [
                    {
                        "name": "report_editor_session",
                        "value": session_value,
                        "domain": "127.0.0.1",
                        "path": "/",
                    }
                ]
            )
            await page.goto(f"{base_url}/reports/v1/editor/{context.report_id}/{context.revision}")
            await page.locator(".save-state-label").wait_for(state="visible", timeout=15000)
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent !== '载入中'",
                timeout=15000,
            )

            for expected_revision in (2, 3):
                await page.locator('button[data-action="pdf"]').click()
                overlay = page.locator(".export-panel")
                await overlay.wait_for(state="visible", timeout=30000)
                revision_label = overlay.locator(".export-revision")
                await revision_label.wait_for(timeout=5000)
                assert await revision_label.text_content() == f"版本 {expected_revision} 已生成"
                await overlay.locator("button.export-panel-close").click()
                await overlay.wait_for(state="hidden", timeout=5000)

            await browser.close()
    finally:
        _stop_server(server)



@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_export_failure_shows_error_and_recoverable(
    tmp_path: Path,
    frontend_built: None,
    browser_available: None,
) -> None:
    """导出渲染失败后前端显示错误并可通过重试恢复，编辑器保持可用。"""
    editor, grants, context = await _make_editor_with_subject(tmp_path)
    thread_id = context.scope["threadId"]
    workspace = editor.workspace

    simple_markdown = "# 故障恢复测试\n\n正文内容。\n"
    simple_sha = hashlib.sha256(simple_markdown.encode()).hexdigest()
    context = context.model_copy(update={
        "job": {
            "jobId": context.job_id,
            "status": "validated",
            "render": {
                "markdown": {"path": context.markdown_path, "size": len(simple_markdown.encode()), "sha256": simple_sha},
                "pdf": {"path": "reports/revision-1/report.pdf", "size": 3, "sha256": hashlib.sha256(b"pdf").hexdigest()},
                "word": {"path": "reports/revision-1/report.docx", "size": 4, "sha256": hashlib.sha256(b"word").hexdigest()},
                "images": [],
            },
        },
    })
    await workspace.awrite_text(thread_id, "reports/revision-1/draft/report.md", simple_markdown)

    durable = SimpleNamespace(
        state_version=1,
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}},
    )

    class StateRepository:
        async def get(self, _run_id: str):
            return durable

        async def apply(self, _run_id: str, command, *, expected_version: int):
            assert expected_version == durable.state_version
            payload = durable.payload.copy()
            payload["reportEditorContexts"] = {
                **payload.get("reportEditorContexts", {}),
                str(command.payload["context"]["revision"]): command.payload["context"],
            }
            durable.state_version += 1
            durable.payload = payload

    editor.state_repository = StateRepository()

    render_attempts = 0

    class Tools:
        async def _render_report_pair(
            self, _job_id, markdown_path, output_path, *, artifact_manifest, run_context
        ):
            nonlocal render_attempts
            render_attempts += 1
            if render_attempts == 1:
                raise ReportingError("report_editor_export_failed", "渲染失败")
            await workspace.awrite_bytes(thread_id, output_path, b"pdf")
            await workspace.awrite_bytes(
                thread_id, output_path.replace(".pdf", ".docx"), b"word"
            )
            stored = run_context.session_state[REPORT_JOBS_STATE_KEY][context.job_id]
            stored["render"] = {
                "markdown": {
                    "path": markdown_path,
                    "size": len((await workspace.aread_text(thread_id, markdown_path)).encode()),
                    "sha256": artifact_manifest["markdown"]["sha256"],
                },
                "pdf": {"path": output_path, "size": 3, "sha256": hashlib.sha256(b"pdf").hexdigest()},
                "word": {
                    "path": output_path.replace(".pdf", ".docx"),
                    "size": 4,
                    "sha256": hashlib.sha256(b"word").hexdigest(),
                },
                "images": [],
            }
            return {"validation": {"ok": True}}

    class Persistence:
        async def persist(self, **_kwargs):
            return None

    class Downloads:
        async def issue(self, **kwargs):
            return "download", ReportDownloadGrant(
                grant_hash="d" * 64, expires_at=datetime(2026, 10, 15, tzinfo=UTC), **kwargs
            )

    class EditorGrants:
        async def issue(self, _context):
            return "editor", datetime(2026, 10, 15, tzinfo=UTC)

    editor.report_tools = Tools()
    editor.artifact_persistence = Persistence()
    editor.download_grants = Downloads()
    editor.editor_grants = EditorGrants()
    editor.public_base_url = "https://reports.example.com"

    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        assert response.status_code == 303
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if "report_editor_session=" in c)
        session_value = session_cookie.split(";")[0].split("=")[1]

    base_url, server = _start_server(app)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=_find_chromium(), args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.context.add_cookies(
                [
                    {
                        "name": "report_editor_session",
                        "value": session_value,
                        "domain": "127.0.0.1",
                        "path": "/",
                    }
                ]
            )
            await page.goto(f"{base_url}/reports/v1/editor/{context.report_id}/{context.revision}")
            await page.locator(".save-state-label").wait_for(state="visible", timeout=15000)
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent !== '载入中'",
                timeout=15000,
            )

            await page.locator('button[data-action="pdf"]').click()
            # 等待阻塞遮罩与错误状态：第一次导出失败。
            await page.wait_for_function(
                "() => document.querySelector('.save-state')?.dataset.state === 'error'",
                timeout=30000,
            )
            label = page.locator(".save-state-label")
            assert "导出失败" in (await label.text_content() or "")
            assert await page.locator(".export-panel").is_hidden()
            assert await page.locator(".export-block-overlay").is_hidden()

            # 点击重试按钮，第二次导出应成功并显示 revision 2。
            await page.locator("button.save-retry").click()
            overlay = page.locator(".export-panel")
            await overlay.wait_for(state="visible", timeout=30000)
            revision_label = overlay.locator(".export-revision")
            await revision_label.wait_for(timeout=5000)
            assert await revision_label.text_content() == "版本 2 已生成"

            # 关闭面板后编辑器仍可编辑并保存。
            await overlay.locator("button.export-panel-close").click()
            await overlay.wait_for(state="hidden", timeout=5000)
            await page.locator("#report-editor").click()
            await page.keyboard.type(" 恢复后追加")
            await page.locator('button[data-action="save"]').click()
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent.includes('已保存')",
                timeout=15000,
            )

            await browser.close()
    finally:
        _stop_server(server)



@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_history_restore_recovers_image_asset(
    tmp_path: Path,
    frontend_built: None,
    browser_available: None,
) -> None:
    """从历史版本恢复后，正文中注册的图片资源能在编辑器中重新加载。"""
    from PIL import Image

    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile, ChartArtifact
    from smart_reporting.reporting.trace.contracts_v1 import canonical_json_bytes

    editor, grants, historical = await _make_editor_with_subject(tmp_path)
    thread_id = historical.scope["threadId"]
    workspace = editor.workspace

    # revision 1：正文含图片，且图片已注册到 job.render.images。
    image_path = "reports/revision-1/chart.png"
    image_buffer = io.BytesIO()
    Image.new("RGB", (80, 40), "blue").save(image_buffer, format="PNG")
    image_bytes = image_buffer.getvalue()
    await workspace.awrite_bytes(thread_id, image_path, image_bytes)
    image_sha = hashlib.sha256(image_bytes).hexdigest()

    original_markdown = await workspace.aread_text(thread_id, historical.markdown_path)
    manifest = await editor.trace.load_manifest(historical)
    index = await editor.trace.load_index(historical)
    assert manifest is not None and index is not None
    historical_markdown = original_markdown.rstrip("\n") + "\n\n![历史趋势](chart.png)\n"
    historical_sha = hashlib.sha256(historical_markdown.encode()).hexdigest()
    await workspace.awrite_text(thread_id, historical.markdown_path, historical_markdown, overwrite=True)
    markdown_identity = ArtifactFile(
        path=historical.markdown_path, mediaType="text/markdown",
        size=len(historical_markdown.encode()), sha256=historical_sha,
    )
    index = index.model_copy(update={"files": tuple(
        file.model_copy(update={"size": markdown_identity.size, "sha256": historical_sha})
        if file.resource_id == index.markdown_file_resource_id else file
        for file in index.files
    )})
    index_bytes = canonical_json_bytes(index.model_dump(mode="json", by_alias=True))
    assert manifest.trace_index is not None and historical.artifact_manifest is not None
    await workspace.awrite_bytes(thread_id, manifest.trace_index.path, index_bytes, overwrite=True)
    manifest = manifest.model_copy(update={
        "markdown": markdown_identity,
        "trace_index": manifest.trace_index.model_copy(update={
            "size": len(index_bytes), "sha256": hashlib.sha256(index_bytes).hexdigest(),
        }),
        "charts": (ChartArtifact(
            chartId="chart-history", datasetIds=(index.datasets[0].dataset_id,),
            path=image_path, mediaType="image/png", size=len(image_bytes), sha256=image_sha,
        ),),
    })
    manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json", by_alias=True))
    await workspace.awrite_bytes(
        thread_id, historical.artifact_manifest.path, manifest_bytes, overwrite=True,
    )
    historical = historical.model_copy(update={
        "artifact_manifest": historical.artifact_manifest.model_copy(update={
            "size": len(manifest_bytes), "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        }),
        "job": {
            "jobId": historical.job_id,
            "status": "validated",
            "render": {
                "markdown": {
                    "path": historical.markdown_path,
                    "size": len(historical_markdown.encode()),
                    "sha256": historical_sha,
                },
                "images": [
                    {
                        "path": image_path,
                        "size": len(image_bytes),
                        "sha256": image_sha,
                    }
                ],
            },
        },
    })

    # revision 2：正文不含图片。
    current_markdown = "# 当前报告\n\n当前版本无图片。\n"
    current = historical.model_copy(update={
        "revision": 2,
        "markdown_path": "reports/revision-2/report.md",
        "artifact_manifest": None,
        "job": {
            "jobId": historical.job_id,
            "render": {
                "markdown": {
                    "path": "reports/revision-2/report.md",
                    "size": len(current_markdown.encode()),
                    "sha256": hashlib.sha256(current_markdown.encode()).hexdigest(),
                },
                "images": [],
            },
        },
    })
    await workspace.awrite_text(thread_id, current.markdown_path, current_markdown)

    state = SimpleNamespace(payload={"reportEditorContexts": {
        "1": historical.model_dump(mode="json", by_alias=True),
        "2": current.model_dump(mode="json", by_alias=True),
    }})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))

    raw, _ = await grants.issue(current)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        assert response.status_code == 303
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if "report_editor_session=" in c)
        session_value = session_cookie.split(";")[0].split("=")[1]

    base_url, server = _start_server(app)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=_find_chromium(), args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.context.add_cookies(
                [
                    {
                        "name": "report_editor_session",
                        "value": session_value,
                        "domain": "127.0.0.1",
                        "path": "/",
                    }
                ]
            )
            await page.goto(f"{base_url}/reports/v1/editor/{current.report_id}/{current.revision}")

            await page.locator(".save-state-label").wait_for(state="visible", timeout=15000)
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent !== '载入中'",
                timeout=15000,
            )
            # 当前版本无图片。
            assert await page.locator("#report-editor img").count() == 0

            # 打开历史面板并恢复 revision 1。
            await page.locator('button[data-action="history"]').click()
            history_overlay = page.locator(".history-panel")
            await history_overlay.wait_for(state="visible", timeout=5000)
            history_item = history_overlay.locator(".history-item").filter(has_text="版本 1").first
            await history_item.wait_for(state="visible", timeout=10000)
            await history_item.click()
            restore_button = history_overlay.locator("button.history-restore")
            await restore_button.wait_for(state="visible", timeout=10000)

            async def _accept_dialog(dialog) -> None:
                await dialog.accept()

            page.on("dialog", _accept_dialog)
            await restore_button.click()
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent.includes('已恢复第 1 版')",
                timeout=15000,
            )
            await history_overlay.wait_for(state="hidden", timeout=5000)

            # 恢复后编辑器区域应出现图片元素且加载成功。
            img = page.locator("#report-editor img").first
            await img.wait_for(state="visible", timeout=15000)
            assert await img.get_attribute("src") is not None
            await page.wait_for_function(
                "() => { const img = document.querySelector('#report-editor img'); "
                "return img?.complete && img.naturalWidth === 80 && img.naturalHeight === 40; }",
                timeout=15000,
            )
            # 刷新后仍从持久化的历史来源读取图片，而非仅靠内存中的恢复状态。
            await page.reload()
            await page.wait_for_function(
                "() => document.querySelector('#report-editor img')?.naturalWidth === 80",
                timeout=15000,
            )

            await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_ai_accept_and_undo_revalidate_claim(
    tmp_path: Path,
    frontend_built: None,
    browser_available: None,
) -> None:
    """通过可见 AI 工具应用改值，撤销后重新取得有效来源。"""
    from smart_reporting.report_editor.ai import ReportEditorAIService

    editor, grants, context = await _make_editor_with_subject(tmp_path)
    thread_id = context.scope["threadId"]
    original = "本期收入3600万元。"
    markdown = await editor.workspace.aread_text(thread_id, context.markdown_path)
    markdown += f"\n{original}[[claim:claim-1]]\n"
    await editor.workspace.awrite_text(thread_id, "reports/revision-1/draft/report.md", markdown)
    calls = []

    class Agent:
        async def arun(self, prompt, **_kwargs):
            calls.append(prompt)
            yield SimpleNamespace(event="RunContent", content="本期收入3800万元。")

    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(
        grants, editor=editor, ai=ReportEditorAIService(Agent()), cookie_secure=False,
    ))
    base_url, server = _start_server(app)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=_find_chromium(), args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.goto(f"{base_url}/reports/v1/editor/open/{raw}")
            paragraph = page.locator("#report-editor .ProseMirror p").filter(has_text=original)
            await paragraph.wait_for(state="visible", timeout=15000)
            from playwright.async_api import expect

            await expect(page.locator(".source-validation-status")).to_have_attribute("data-state", "valid", timeout=15000)
            await paragraph.click()
            await page.keyboard.press("Home")
            for _ in original:
                await page.keyboard.press("Shift+ArrowRight")
            await page.get_by_role("button", name="AI 改写", exact=True).click()
            await page.get_by_role("option", name="润色表达").click()
            accept = page.locator(".milkdown-ai-diff-actions-btn-accept")
            await accept.wait_for(state="visible", timeout=15000)
            await page.locator(".milkdown-ai-diff-actions-btn-reject").click()
            await expect(accept).to_be_hidden()
            assert original in (await paragraph.text_content() or "")
            await expect(page.locator(".source-validation-status")).to_have_attribute("data-state", "valid", timeout=15000)
            await paragraph.click()
            await page.keyboard.press("Home")
            for _ in original:
                await page.keyboard.press("Shift+ArrowRight")
            await page.get_by_role("button", name="AI 改写", exact=True).click()
            await page.get_by_role("option", name="润色表达").click()
            await accept.wait_for(state="visible", timeout=15000)
            await accept.click()
            await page.wait_for_function(
                "() => document.querySelector('#report-editor')?.textContent.includes('3800')",
                timeout=15000,
            )
            await page.wait_for_function(
                "() => document.querySelector('.source-validation-status')?.dataset.state === 'stale'",
                timeout=15000,
            )
            await page.locator('button[data-action="save"]').click()
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent.includes('已保存')",
                timeout=15000,
            )
            saved = await editor.read_document(context)
            assert "3800" in saved.markdown and "[[claim:claim-1]]" in saved.markdown
            assert len(calls) == 2 and all("[[claim:" not in prompt for prompt in calls)
            await page.screenshot(path=str(tmp_path / "ai-accepted-stale.png"), full_page=True)

            await page.locator("#report-editor .ProseMirror p").filter(has_text="本期收入3800万元").click()
            await page.keyboard.press("Control+z")
            await page.wait_for_function(
                "() => document.querySelector('#report-editor')?.textContent.includes('本期收入3600万元')",
                timeout=15000,
            )
            await page.wait_for_function(
                "() => document.querySelector('.source-validation-status')?.dataset.state === 'valid'",
                timeout=15000,
            )
            await page.locator('button[data-action="save"]').click()
            await page.wait_for_function(
                "() => document.querySelector('.save-state-label')?.textContent.includes('已保存')",
                timeout=15000,
            )
            assert original in (await editor.read_document(context)).markdown
            await page.screenshot(path=str(tmp_path / "ai-undone-valid.png"), full_page=True)
            await browser.close()
    finally:
        _stop_server(server)
