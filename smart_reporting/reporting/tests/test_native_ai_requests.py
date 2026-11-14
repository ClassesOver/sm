"""选区编辑在启动回执丢失时仍可按请求身份取消，不重复调用模型。"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.native_ai import NativeAIService
from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_ai import sample as sample


def request(context, model):
    return dict(client_request_id='request-1', instruction='润色',
        expected_sha256=context.source_file.sha256, operations=[],
        selection=[{'blockId': model['blocks'][0]['blockId']}])


@pytest.mark.anyio
async def test_edit_cancel_before_start_never_previews_or_calls_provider(sample, monkeypatch):
    editor, context, session, model, _ = sample
    preview, planner = AsyncMock(), AsyncMock()
    monkeypatch.setattr(editor, 'preview', preview)
    ai = NativeAIService(editor, planner=planner, enabled=True)
    try:
        cancelled = await ai.cancel_request(session, 'request-1')
        started = await ai.start_edit(session, **request(context, model))
        assert started['editId'] == cancelled['editId']
        assert started['status'] == 'cancelled'
        preview.assert_not_awaited()
        planner.assert_not_awaited()
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_edit_cancel_during_start_preview_prevents_model(sample, monkeypatch):
    editor, context, session, model, _ = sample
    entered, release = asyncio.Event(), asyncio.Event()

    async def preview(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return {'model': model, 'draftSha256': 'b' * 64}

    monkeypatch.setattr(editor, 'preview', preview)
    planner = AsyncMock()
    ai = NativeAIService(editor, planner=planner, enabled=True)
    task = asyncio.create_task(ai.start_edit(session, **request(context, model)))
    waiter = asyncio.create_task(entered.wait())
    try:
        # 未接请求协议的版本应直接在 start 失败，避免等待一个不会到达的事件。
        done, _ = await asyncio.wait([task, waiter],
                                     timeout=1, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        assert entered.is_set()
        cancelled = await ai.cancel_request(session, 'request-1')
        release.set()
        result = await task
        assert result['editId'] == cancelled['editId'] and result['status'] == 'cancelled'
        planner.assert_not_awaited()
    finally:
        release.set()
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        await asyncio.gather(task, return_exceptions=True)
        await ai.aclose()


@pytest.mark.anyio
async def test_request_http_cancel_requires_scope_csrf_and_ends_replayed_stream(sample):
    editor, context, _, model, _ = sample
    planner = AsyncMock()
    ai = NativeAIService(editor, planner=planner, enabled=True)
    app = FastAPI()
    app.include_router(create_native_ai_router(editor.grants, editor=editor, ai=ai, allowed_origin='http://test'))
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await editor.grants.exchange(raw)
    headers = {'Origin': 'http://test', 'X-CSRF-Token': editor.grants.csrf_token(token)}
    base = f'/reports/v1/native/{context.document_id}/{context.revision}/api/ai'
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            body = {'clientRequestId': 'request-1'}
            assert (await client.post(base + '/cancel-request', json=body, headers=headers)).status_code == 403
            client.cookies.set(NATIVE_SESSION_COOKIE, token)
            assert (await client.post(base + '/cancel-request', json=body)).status_code == 403
            assert (await client.post(base + '/cancel-request', json=body,
                headers={**headers, 'Origin': 'http://foreign'})).status_code == 403
            assert (await client.post(base.replace('/1/', '/2/') + '/cancel-request',
                json=body, headers=headers)).status_code == 403
            cancelled = await client.post(base + '/cancel-request', json=body, headers=headers)
            assert cancelled.status_code == 200, cancelled.text
            started = await client.post(base + '/start', headers=headers, json={
                **body, 'instruction': '修改', 'expectedSha256': context.source_file.sha256,
                'operations': [], 'selection': [{'blockId': model['blocks'][0]['blockId']}],
            })
            assert started.status_code == 200, started.text
            assert started.json()['editId'] == cancelled.json()['editId']
            assert started.json()['status'] == 'cancelled'
            events_url = base + '/' + started.json()['editId'] + '/events'
            events = await asyncio.wait_for(client.get(events_url + '?after=999'), timeout=1)
            assert '"kind":"reset"' in events.text and '"status":"cancelled"' in events.text
            consumed = await asyncio.wait_for(client.get(events_url + '?after=1'), timeout=1)
            assert consumed.status_code == 200 and consumed.text == ''
            planner.assert_not_awaited()
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_edit_same_request_is_idempotent_and_changed_content_is_rejected(sample, monkeypatch):
    editor, context, session, model, _ = sample
    monkeypatch.setattr(editor, 'preview', AsyncMock(return_value={'model': model, 'draftSha256': 'b' * 64}))
    entered = asyncio.Event()

    async def planner(*_args, **_kwargs):
        entered.set()
        await asyncio.Event().wait()

    ai = NativeAIService(editor, planner=planner, enabled=True)
    try:
        first = await ai.start_edit(session, **request(context, model))
        await entered.wait()
        second = await ai.start_edit(session, **request(context, model))
        assert first['editId'] == second['editId']
        changed = request(context, model)
        changed['instruction'] = '另一要求'
        with pytest.raises(ReportingError) as error:
            await ai.start_edit(session, **changed)
        assert error.value.code == 'native_ai_snapshot_changed'
        assert len(ai._jobs) == 1
    finally:
        await ai.aclose()
