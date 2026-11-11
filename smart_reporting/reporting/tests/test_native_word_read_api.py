"""Word 纯读路由复用原生会话，且独立于 Word 编辑开关。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import (
    NATIVE_SESSION_COOKIE,
    create_native_editor_router,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_ai import sample as sample


@pytest.fixture
async def word_http(sample):
    editor, context, session, _, _ = sample
    editor.docx_enabled = False
    reader = SimpleNamespace(
        start=AsyncMock(return_value={"taskId": "word-task", "status": "running"}),
        cancel_request=AsyncMock(return_value={"status": "cancelled"}),
        status=AsyncMock(return_value={"status": "completed", "result": {"answer": "摘要"}}),
        event_stream=AsyncMock(return_value=Response("data: {}\n\n", media_type="text/event-stream")),
    )
    app = FastAPI()
    app.include_router(create_native_editor_router(editor.grants, editor=editor, ai_enabled=True))
    app.include_router(create_native_ai_router(
        editor.grants, editor=editor, ai=None, word_read=reader, allowed_origin="http://test",
    ))
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await editor.grants.exchange(raw)
    headers = {"Origin": "http://test", "X-CSRF-Token": editor.grants.csrf_token(token)}
    body = {
        "clientRequestId": "word-1", "expectedSha256": context.source_file.sha256,
        "operations": [], "action": "summarize", "selection": [{"blockId": "p1", "cellId": "c1"}],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, reader, token, headers, body, editor


BASE = "/reports/v1/native/doc/1/api"


@pytest.mark.anyio
async def test_word_read_routes_forward_authorized_payload_and_stream(word_http):
    client, reader, token, headers, body, _ = word_http
    client.cookies.set(NATIVE_SESSION_COOKIE, token)
    response = await client.post(BASE + "/ai/word-read/start", json=body, headers=headers)
    assert response.status_code == 200, response.text
    kwargs = reader.start.call_args.kwargs
    assert kwargs == {
        "client_request_id": "word-1", "expected_sha256": body["expectedSha256"],
        "operations": [], "action": "summarize", "selection": body["selection"], "instruction": "",
    }
    assert (await client.get(BASE + "/ai/word-read/word-task?waitMs=15")).json()["status"] == "completed"
    assert reader.status.call_args.kwargs == {"wait_ms": 15}
    events = await client.get(BASE + "/ai/word-read/word-task/events?after=2")
    assert events.headers["content-type"].startswith("text/event-stream")
    assert reader.event_stream.call_args.args[1:] == ("word-task", 2)
    cancelled = await client.post(BASE + "/ai/word-read/cancel", json={"clientRequestId": "word-1"}, headers=headers)
    assert cancelled.json()["status"] == "cancelled"
    assert reader.cancel_request.call_args.args[1] == "word-1"


@pytest.mark.anyio
async def test_word_read_requires_cookie_csrf_origin_and_matching_revision(word_http):
    client, reader, token, headers, body, editor = word_http
    assert (await client.post(BASE + "/ai/word-read/start", json=body, headers=headers)).status_code == 403
    client.cookies.set(NATIVE_SESSION_COOKIE, token)
    assert (await client.post(BASE + "/ai/word-read/start", json=body)).status_code == 403
    assert (await client.post(BASE + "/ai/word-read/start", json=body, headers={**headers, "Origin": "http://foreign"})).status_code == 403
    assert (await client.get(BASE.replace("/1/", "/2/") + "/ai/word-read/word-task")).status_code == 403
    assert (await client.get(BASE.replace("/doc/", "/other/") + "/ai/word-read/word-task")).status_code == 403
    assert (await client.post(BASE + "/ai/word-read/cancel", json={"clientRequestId": "word-1"})).status_code == 403
    editor.context_for_session = AsyncMock(side_effect=ReportingError("native_permission_denied", "作用域不一致"))
    assert (await client.get(BASE + "/ai/word-read/word-task/events")).status_code == 403
    reader.start.assert_not_awaited()
    reader.status.assert_not_awaited()
    reader.event_stream.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", [
    {"path": "/tmp/source.docx"}, {"action": "reviewSummary"},
    {"selection": [{"blockId": "p1", "path": "/tmp/a"}]},
    {"selection": [{"cellId": "c1"}]}, {"selection": [{"blockId": 1}]},
    {"selection": [{"blockId": "p1"}] * 101}, {"selection": "p1"},
])
async def test_word_read_rejects_extra_fields_and_invalid_selection(word_http, invalid):
    client, reader, token, headers, body, _ = word_http
    client.cookies.set(NATIVE_SESSION_COOKIE, token)
    response = await client.post(BASE + "/ai/word-read/start", json={**body, **invalid}, headers=headers)
    assert response.status_code == 422, response.text
    reader.start.assert_not_awaited()


@pytest.mark.anyio
async def test_word_read_capability_is_independent_of_docx_editing(word_http):
    client, _, token, _, _, _ = word_http
    client.cookies.set(NATIVE_SESSION_COOKIE, token)
    result = (await client.get(BASE + "/context")).json()
    assert result["wordReadAIEnabled"] is True
    assert result["aiEnabled"] is False and result["editingEnabled"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("action", [None, "keyPoints"])
async def test_word_read_presets_allow_empty_selection_and_default_ask(word_http, action):
    client, reader, token, headers, body, _ = word_http
    client.cookies.set(NATIVE_SESSION_COOKIE, token)
    body.pop("action")
    body.pop("selection")
    if action is not None:
        body["action"] = action
    response = await client.post(BASE + "/ai/word-read/start", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert reader.start.call_args.kwargs["action"] == (action or "ask")
    assert reader.start.call_args.kwargs["selection"] == []


@pytest.mark.anyio
async def test_word_read_missing_service_returns_disabled(sample):
    editor, context, _, _, _ = sample
    app = FastAPI()
    app.include_router(create_native_ai_router(editor.grants, editor=editor, ai=None))
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await editor.grants.exchange(raw)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token)
        response = await client.get(BASE + "/ai/word-read/word-task")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "native_ai_disabled"


@pytest.mark.anyio
@pytest.mark.parametrize("enabled,format,expected", [(False, "docx", False), (True, "pdf", False)])
async def test_word_read_capability_requires_ai_and_docx(sample, enabled, format, expected):
    editor, context, _, _, _ = sample
    context = context.model_copy(update={"format": format})
    editor.context_for_session = AsyncMock(return_value=context)
    app = FastAPI()
    app.include_router(create_native_editor_router(editor.grants, editor=editor, ai_enabled=enabled))
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await editor.grants.exchange(raw)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token)
        result = (await client.get(BASE + "/context")).json()
    assert result["wordReadAIEnabled"] is expected


@pytest.mark.anyio
async def test_word_read_model_is_get_only_and_available_without_editing(word_http):
    client, _, token, headers, body, editor = word_http
    assert (await client.get(BASE + '/read-model')).status_code == 403
    client.cookies.set(NATIVE_SESSION_COOKIE, token)
    response = await client.get(BASE + '/read-model')
    assert response.status_code == 200, response.text
    model = response.json()
    assert model['sourceSha256'] == body['expectedSha256']
    assert model['model']['sourceSha256'] == body['expectedSha256']
    assert model['model']['blocks'][0]['text'] == '第一段原文'
    assert (await client.post(BASE + '/read-model', json={})).status_code == 405
    assert (await client.post(BASE + '/preview', headers=headers, json={
        'expectedSha256': body['expectedSha256'], 'operations': [],
    })).status_code == 503
    assert editor.docx_enabled is False


@pytest.mark.anyio
async def test_word_read_model_rejects_revision_scope_and_non_docx(word_http):
    client, _, token, _, _, editor = word_http
    client.cookies.set(NATIVE_SESSION_COOKIE, token)
    assert (await client.get(BASE.replace('/1/', '/2/') + '/read-model')).status_code == 403
    assert (await client.get(BASE.replace('/doc/', '/foreign/') + '/read-model')).status_code == 403
    original = editor.context_for_session
    context = await original(await editor.grants.lookup_session(token))
    editor.context_for_session = AsyncMock(return_value=context.model_copy(update={'format': 'pdf'}))
    assert (await client.get(BASE + '/read-model')).status_code == 422
    editor.context_for_session = AsyncMock(side_effect=ReportingError('native_permission_denied', '作用域不一致'))
    assert (await client.get(BASE + '/read-model')).status_code == 403
