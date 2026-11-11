"""PDF 阅读任务不依赖编辑开关，不修改文档或草稿。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests import test_native_ai

# 直接复用原有真实 PDF/会话 fixture，不复制其初始化逻辑。
pdf_sample = test_native_ai.pdf_sample


def service(editor, planner, **kwargs):
    from smart_reporting.report_editor.native_pdf_ai_tasks import NativePDFReadService

    return NativePDFReadService(editor, planner=planner, enabled=True, **kwargs)


def payload(context, **overrides):
    return {
        "client_request_id": "request-1",
        "expected_sha256": context.source_file.sha256,
        "operations": [],
        "selection": [],
        "action": "summarize",
        "instruction": "",
        **overrides,
    }


@pytest.mark.anyio
async def test_read_without_selection_or_pdf_edit_flags_keeps_original(pdf_sample):
    editor, context, session, _, source = pdf_sample
    editor.pdf_enabled = editor.pdf_text_enabled = False
    planner = AsyncMock(
        return_value={"answer": "第1页有应付金额。", "coverage": {"pagesRead": [1]}}
    )
    ai = service(editor, planner)
    started = await ai.start(session, **payload(context))
    result = await ai.status(session, started["taskId"], wait_ms=20000)
    assert result["status"] == "completed", result
    assert result["result"]["answer"]
    assert "operations" not in result and "proposal" not in result
    assert planner.call_args.kwargs["content"] == source
    assert planner.call_args.kwargs["selection"] == []
    assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
async def test_same_request_is_idempotent_but_changed_request_rejected(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    planner = AsyncMock(return_value={"answer": "总结"})
    ai = service(editor, planner)
    first = await ai.start(session, **payload(context))
    second = await ai.start(session, **payload(context))
    assert first["taskId"] == second["taskId"]
    with pytest.raises(ReportingError, match="请求"):
        await ai.start(session, **payload(context, instruction="变化"))
    await ai.status(session, first["taskId"], wait_ms=20000)
    assert planner.await_count == 1
    await ai.aclose()


@pytest.mark.anyio
async def test_cancel_before_start_prevents_late_provider_call(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    planner = AsyncMock(return_value={"answer": "迟到"})
    ai = service(editor, planner)
    cancelled = await ai.cancel_request(session, "request-1")
    started = await ai.start(session, **payload(context))
    assert started["status"] == cancelled["status"] == "cancelled"
    planner.assert_not_awaited()
    await ai.aclose()


@pytest.mark.anyio
async def test_cancellation_stops_task_and_discards_late_result(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    entered = asyncio.Event()

    async def planner(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return {"answer": "不应该展示迟到结果"}

    ai = service(editor, planner)
    started = await ai.start(session, **payload(context))
    await entered.wait()
    await ai.cancel_request(session, "request-1")
    result = await ai.status(session, started["taskId"], wait_ms=0)
    assert result["status"] == "cancelled" and "result" not in result
    await ai.aclose()


@pytest.mark.anyio
async def test_changed_source_and_expired_context_never_reach_planner(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    planner = AsyncMock(return_value={"answer": "不应调用"})
    ai = service(editor, planner)
    with pytest.raises(ReportingError):
        await ai.start(session, **payload(context, expected_sha256="0" * 64))
    planner.assert_not_awaited()
    await ai.aclose()


@pytest.mark.anyio
async def test_empty_answer_is_failure_not_successful_read(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    ai = service(editor, AsyncMock(return_value={"answer": " "}))
    started = await ai.start(session, **payload(context))
    result = await ai.status(session, started["taskId"], wait_ms=20000)
    assert result["status"] == "failed" and "result" not in result
    await ai.aclose()


@pytest.mark.anyio
async def test_pdf_read_http_requires_cookie_csrf_origin_and_revision(pdf_sample):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor.native_ai_api import create_native_ai_router
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE

    editor, context, _, _, _ = pdf_sample
    editor.pdf_enabled = editor.pdf_text_enabled = False
    planner = AsyncMock(return_value={"answer": "只读总结"})
    ai = service(editor, planner)
    app = FastAPI()
    app.include_router(
        create_native_ai_router(
            editor.grants,
            editor=editor,
            ai=None,
            pdf_read=ai,
            allowed_origin="http://test",
        )
    )
    raw, _ = await editor.grants.issue(
        context, capabilities=editor.capabilities(context)
    )
    token, _ = await editor.grants.exchange(raw)
    base = f"/reports/v1/native/{context.document_id}/1/api/ai/read"
    body = {
        "clientRequestId": "http-1",
        "expectedSha256": context.source_file.sha256,
        "action": "summarize",
        "operations": [],
        "selection": [],
    }
    headers = {"Origin": "http://test", "X-CSRF-Token": editor.grants.csrf_token(token)}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post(base + "/start", json=body)).status_code == 403
        client.cookies.set(NATIVE_SESSION_COOKIE, token)
        assert (await client.post(base + "/start", json=body)).status_code == 403
        foreign = {**headers, "Origin": "http://foreign"}
        assert (
            await client.post(base + "/start", json=body, headers=foreign)
        ).status_code == 403
        response = await client.post(base + "/start", json=body, headers=headers)
        assert response.status_code == 200, response.text
        task_id = response.json()["taskId"]
        status = await client.get(base + f"/{task_id}?waitMs=20000")
        assert status.json()["status"] == "completed", status.text
        assert (
            await client.get(base.replace("/1/", "/2/") + f"/{task_id}")
        ).status_code == 403
        cancelled = await client.post(
            base + "/cancel", json={"clientRequestId": "before-start"}, headers=headers
        )
        assert cancelled.json()["status"] == "cancelled"
        assert "operations" not in status.json()
    await ai.aclose()


@pytest.mark.anyio
async def test_pdf_preset_uses_actual_agno_reader_through_http(pdf_sample):
    import json

    from agno.models.response import ModelResponse
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor.native_ai_api import create_native_ai_router
    from smart_reporting.report_editor.native_api import (
        NATIVE_SESSION_COOKIE,
        create_native_editor_router,
    )
    from smart_reporting.report_editor.native_pdf_ai import (
        create_native_pdf_read_planner,
    )
    from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel

    editor, context, _, _, source = pdf_sample
    editor.pdf_enabled = editor.pdf_text_enabled = False
    model = ScriptedModel(
        id="scripted",
        expected_tool_text="Amount due 500",
        responses=[
            ModelResponse(
                tool_calls=[
                    {
                        "id": "read-1",
                        "type": "function",
                        "function": {
                            "name": "read_pages",
                            "arguments": '{"start_page":1,"page_count":2}',
                        },
                    }
                ]
            ),
            ModelResponse(
                content=json.dumps(
                    {
                        "answer": "第1页应付金额为500，第2页未提取到正文。",
                        "citations": [1],
                    }
                )
            ),
        ],
    )
    ai = service(editor, create_native_pdf_read_planner(model))
    app = FastAPI()
    app.include_router(
        create_native_editor_router(editor.grants, editor=editor, ai_enabled=True)
    )
    app.include_router(
        create_native_ai_router(
            editor.grants,
            editor=editor,
            ai=None,
            pdf_read=ai,
            allowed_origin="http://test",
        )
    )
    raw, _ = await editor.grants.issue(
        context, capabilities=editor.capabilities(context)
    )
    token, _ = await editor.grants.exchange(raw)
    base = f"/reports/v1/native/{context.document_id}/1/api"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token)
        caps = (await client.get(base + "/context")).json()
        assert caps["pdfReadAIEnabled"] is True
        assert caps["editingEnabled"] is False and caps["pdfTextEnabled"] is False
        headers = {"Origin": "http://test", "X-CSRF-Token": caps["csrfToken"]}
        started = await client.post(
            base + "/ai/read/start",
            headers=headers,
            json={
                "clientRequestId": "actual-loop",
                "expectedSha256": context.source_file.sha256,
                "action": "summarize",
                "instruction": "",
                "operations": [],
                "selection": [],
            },
        )
        assert started.status_code == 200, started.text
        task = (
            await client.get(
                base + "/ai/read/" + started.json()["taskId"] + "?waitMs=20000"
            )
        ).json()
        assert task["status"] == "completed", task
        result = task["result"]
        assert result["sourceSha256"] == context.source_file.sha256
        assert result["coverage"]["fullyReadPages"] == [1, 2]
        assert result["coverage"]["scopeReadComplete"] is True
        assert result["coverage"]["ocrPerformed"] is False
        assert result["toolEvents"][0]["tool"] == "read_pages"
        assert result["citations"][0]["pageNumber"] == 1
        assert "operations" not in task and "proposal" not in task
        assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
async def test_pre_cancel_can_reserve_tombstone_when_running_capacity_is_full(
    pdf_sample,
):
    editor, context, session, _, _ = pdf_sample

    async def planner(**kwargs):
        await asyncio.Event().wait()

    ai = service(editor, planner)
    try:
        for i in range(32):
            await ai.start(session, **payload(context, client_request_id=f"busy-{i}"))
        cancelled = await ai.cancel_request(session, "not-started-yet")
        assert cancelled["status"] == "cancelled"
        late = await ai.start(
            session, **payload(context, client_request_id="not-started-yet")
        )
        assert late["status"] == "cancelled"
    finally:
        await ai.aclose()
