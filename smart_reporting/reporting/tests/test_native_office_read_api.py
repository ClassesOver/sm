"""Office 只读任务复用授权与同源保护，关闭编辑仍能读取原件。"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import (
    NATIVE_SESSION_COOKIE,
    create_native_editor_router,
)
from smart_reporting.report_editor.native_office_read_tasks import NativeOfficeReadService
from smart_reporting.reporting.tests.test_native_office_read_tasks import (
    office_sample as office_sample,
)
from smart_reporting.reporting.tests.test_native_office_read_tasks import read_all, request_for

BASE = '/reports/v1/native/office/1/api'


@pytest.fixture
async def office_http(office_sample):
    editor, context, session, _, _ = office_sample
    editor.office_enabled = False
    service = NativeOfficeReadService(editor, planners={context.format: read_all}, enabled=True)
    app = FastAPI()
    app.include_router(create_native_editor_router(editor.grants, editor=editor, ai_enabled=True))
    app.include_router(create_native_ai_router(editor.grants, editor=editor, ai=None,
        office_read=service, allowed_origin='http://test'))
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await editor.grants.exchange(raw)
    headers = {'Origin': 'http://test', 'X-CSRF-Token': editor.grants.csrf_token(token)}
    body = {'clientRequestId': 'office-http', 'expectedSha256': context.source_file.sha256,
        'operations': [], 'selection': None, 'action': 'summarize'}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            yield client, token, headers, body, service, session, context
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_office_read_roundtrip_and_capability_without_editing(office_http):
    client, token, headers, body, _, _, _ = office_http
    client.cookies.set(NATIVE_SESSION_COOKIE, token)
    context = (await client.get(BASE + '/context')).json()
    assert context['officeReadAIEnabled'] is True
    assert context['editingEnabled'] is False and context['aiEnabled'] is False
    started = await client.post(BASE + '/ai/office-read/start', json=body, headers=headers)
    assert started.status_code == 200, started.text
    task_id = started.json()['taskId']
    job = (await client.get(BASE + '/ai/office-read/' + task_id)).json()
    assert job['status'] == 'completed', job
    assert job['result']['readingVersion'] == 'source'
    assert job['result']['coverage']['scopeReadComplete'] is True
    events = await client.get(BASE + '/ai/office-read/' + task_id + '/events')
    assert events.headers['content-type'].startswith('text/event-stream')
    assert 'terminal' in events.text
    cancelled = await client.post(BASE + '/ai/office-read/cancel',
        json={'clientRequestId': body['clientRequestId']}, headers=headers)
    assert cancelled.json()['status'] == 'cancelled'


@pytest.mark.anyio
async def test_office_read_rejects_cookie_csrf_origin_cross_revision_and_extra_input(office_http):
    client, token, headers, body, _, _, _ = office_http
    assert (await client.post(BASE + '/ai/office-read/start', json=body, headers=headers)).status_code == 403
    client.cookies.set(NATIVE_SESSION_COOKIE, token)
    assert (await client.post(BASE + '/ai/office-read/start', json=body)).status_code == 403
    assert (await client.post(BASE + '/ai/office-read/start', json=body,
        headers={**headers, 'Origin': 'http://foreign'})).status_code == 403
    assert (await client.get(BASE.replace('/1/', '/2/') + '/ai/office-read/missing')).status_code == 403
    assert (await client.get(BASE.replace('/office/', '/foreign/') + '/ai/office-read/missing')).status_code == 403
    for invalid in ({**body, 'path': '/tmp/foreign'}, {**body, 'selection': []},
                    {**body, 'selection': {'sheetName': '经营', 'startRow': True,
                        'endRow': 0, 'startColumn': 0, 'endColumn': 0}}):
        assert (await client.post(BASE + '/ai/office-read/start', json=invalid, headers=headers)).status_code == 422


@pytest.mark.anyio
async def test_office_read_cross_scope_cannot_poll_existing_task(office_http):
    client, token, _, _, service, session, context = office_http
    started = await service.start(session, **request_for(context))
    client.cookies.set(NATIVE_SESSION_COOKIE, token)
    original = service.editor.context_for_session
    async def changed(_session):
        value = await original(_session)
        return value.model_copy(update={'scope': value.scope.model_copy(update={'thread_id': 'foreign'})})
    service.editor.context_for_session = changed
    response = await client.get(BASE + '/ai/office-read/' + started['taskId'])
    assert response.status_code in {403, 404}
