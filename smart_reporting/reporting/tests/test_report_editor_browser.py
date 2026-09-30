"""Browser smoke tests for the report editor trace panel (B6 GUI verification).

Requires a Chromium-compatible browser and the frontend static build.
Marked as integration and skipped automatically when playwright or the browser
is unavailable. The system Chromium is used to avoid downloading playwright
binaries inside the test run.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    tmp_path: Path, frontend_built: None, browser_available: None,
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
            browser = await playwright.chromium.launch(executable_path=_find_chromium(), args=["--no-sandbox"])
            try:
                for context, session in zip((first, second), sessions, strict=True):
                    page = await browser.new_page(viewport={"width": 1280, "height": 720})
                    await page.context.add_cookies([{"name": "report_editor_session", "value": session,
                        "domain": "127.0.0.1", "path": "/"}])
                    response = await page.goto(f"{base_url}/reports/v1/editor/{context.report_id}/{context.revision}")
                    assert response.status == 200
                    await page.locator('button[data-action="sources"]').click()
                    overlay = page.locator(".modal-overlay").filter(has_text="数据来源")
                    await overlay.locator(".trace-item-title").filter(has_text="收入明细.csv").wait_for(timeout=15000)
                    preview = overlay.get_by_role("button", name="预览", exact=True)
                    if context == first:
                        assert "明细不可用" in (await overlay.text_content())
                        assert await preview.is_disabled()
                        assert await overlay.get_by_role("button", name="下载原始", exact=True).is_disabled()
                        dataset_id = (await editor.trace.load_index(first)).datasets[0].dataset_id
                        denied = await page.request.get(
                            f"{base_url}/reports/v1/editor/{first.report_id}/1/api/datasets/{dataset_id}/download")
                        assert denied.status == 410
                        assert (await denied.json())["detail"]["code"] == "snapshot_expired"
                        await page.screenshot(path=str(tmp_path / "retired-source-metadata.png"), full_page=True)
                    else:
                        assert await preview.is_enabled()
                        await preview.click()
                        await overlay.locator("table").filter(has_text="3600").wait_for(timeout=10000)
                        await page.screenshot(path=str(tmp_path / "live-shared-source-preview.png"), full_page=True)
                    await page.close()
            finally:
                await browser.close()
    finally:
        _stop_server(server)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_online_subject_opens_frozen_fact_and_session_expiry_has_no_retry(
    tmp_path: Path, frontend_built: None, browser_available: None,
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
            browser = await playwright.chromium.launch(executable_path=_find_chromium(), args=["--no-sandbox"])
            try:
                anonymous = await browser.new_page()
                response = await anonymous.goto(target)
                assert response is not None and response.status == 404
                await anonymous.close()
                page = await browser.new_page(viewport={"width": 1280, "height": 720})
                await page.context.add_cookies([{
                    "name": "report_editor_session", "value": session_value,
                    "domain": "127.0.0.1", "path": "/",
                }])
                response = await page.goto(target)
                assert response is not None and response.status == 200
                fact = page.locator(".trace-fact-value")
                await fact.wait_for(state="visible", timeout=15000)
                assert "3600" in (await fact.text_content() or "")
                assert "万元" in (await fact.text_content() or "")
                await page.screenshot(path=str(tmp_path / "online-subject.png"), full_page=True)
                for key, session in grants.repository.sessions.items():
                    grants.repository.sessions[key] = replace(session, expires_at=datetime.now(UTC) - timedelta(seconds=1))
                overlay = page.locator(".modal-overlay").filter(has_text="数据来源")
                await overlay.locator("button.modal-close").click()
                await page.locator('button[data-action="sources"]').click()
                status = overlay.locator('[data-trace="status"]')
                await page.wait_for_function(
                    "() => document.querySelector('[data-trace=\"status\"]')?.textContent?.includes('编辑会话已过期')",
                    timeout=10000,
                )
                assert "从报告列表重新打开" in (await status.text_content() or "")
                assert await overlay.locator(".trace-retry").count() == 0
                await page.screenshot(path=str(tmp_path / "session-expired.png"), full_page=True)
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

            # 打开来源面板。
            await page.locator('button[data-action="sources"]').click()
            overlay = page.locator(".modal-overlay").filter(has_text="数据来源")
            await overlay.wait_for(state="visible", timeout=5000)
            assert await overlay.count() == 1
            # 等待异步加载来源列表。
            await overlay.locator(".trace-item").first.wait_for(state="visible", timeout=10000)
            panel_text = await overlay.locator(".trace-list").text_content()
            assert (
                await overlay.locator(".trace-item").filter(has_text="收入明细.csv").count() >= 1
            ), f"panel text: {panel_text!r}"

            # 展开 CSV 预览。
            item = overlay.locator(".trace-item").filter(has_text="收入明细.csv").first
            await item.locator("button").filter(has_text="预览").click()
            preview = overlay.locator(".trace-table-wrap")
            await preview.wait_for(state="visible", timeout=5000)
            assert await preview.locator("text=2025-09").count() >= 1
            assert await preview.locator("text=3600").count() >= 1

            # 关闭面板。
            await overlay.locator("button.modal-close").click()
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
    browser_available: None,
) -> None:
    """从历史面板恢复 revision 1，正文与来源均回退到旧版本。"""
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
            # 初始加载当前 revision 2 的正文。
            assert await page.locator("text=Current report").first.is_visible()

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

            # 来源面板显示 revision 1 的数据来源。
            await page.locator('button[data-action="sources"]').click()
            sources_overlay = page.locator(".modal-overlay").filter(has_text="数据来源")
            await sources_overlay.wait_for(state="visible", timeout=5000)
            await sources_overlay.locator(".trace-item").first.wait_for(state="visible", timeout=10000)
            panel_text = await sources_overlay.locator(".trace-list").text_content()
            assert (
                await sources_overlay.locator(".trace-item").filter(has_text="收入明细.csv").count() >= 1
            ), f"panel text: {panel_text!r}"

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
