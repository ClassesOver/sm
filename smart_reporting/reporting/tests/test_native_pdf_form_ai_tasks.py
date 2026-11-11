"""表单 AI 使用实际字段身份、预览和显式采纳，不覆盖原件。"""

import asyncio
import hashlib
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.report_editor.native_pdf_form_ai_tasks import NativePDFFormService
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests import test_native_ai

pdf_sample = test_native_ai.pdf_sample


@pytest.fixture
async def form_sample(pdf_sample):
    editor, context, _, _, _ = pdf_sample
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(300, 400))
    canvas.drawString(20, 360, 'Form')
    canvas.acroForm.textfield(name='customer', x=20, y=280, width=180, height=25, value='Alice')
    canvas.acroForm.checkbox(name='consent', x=20, y=220, checked=False)
    canvas.showPage()
    canvas.save()
    source = stream.getvalue()
    context = context.model_copy(update={'source_file': context.source_file.model_copy(update={
        'path': 'native/form-source.pdf', 'size': len(source), 'sha256': hashlib.sha256(source).hexdigest(),
    })})
    await editor.workspace.awrite_bytes(bind_native_workspace(editor.workspace, context.scope), context.source_file.path, source)
    editor.repository.get_revision.return_value = SimpleNamespace(status='saved', context=context)
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, session = await editor.grants.exchange(raw)
    model = (await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[]))['model']
    editor.pdf_text_enabled = False
    return editor, context, session, token, source, model


def payload(context, model, **kwargs):
    field = next(field for field in model['formFields'] if field['name'] == 'customer')
    return dict(client_request_id='form-1', expected_sha256=context.source_file.sha256,
                operations=[], selection=[{'fieldId': field['fieldId']}], instruction='姓名改为Bob', **kwargs)


async def fill_candidate(*, selected, **kwargs):
    field = selected[0]
    return {'answer': '已提出填写候选。', 'summary': '填写姓名', 'operations': [{
        'kind': 'setFormValue', 'fieldId': field['fieldId'], 'name': field['name'],
        'fieldKind': field['kind'], 'expectedFieldSha256': field['expectedFieldSha256'], 'value': 'Bob',
    }]}


@pytest.mark.anyio
async def test_form_real_preview_accept_merges_manual_values_without_text_permission(form_sample):
    editor, context, session, _, source, model = form_sample
    target = next(f for f in model['formFields'] if f['name'] == 'customer')
    other = next(f for f in model['formFields'] if f['name'] == 'consent')
    base = [{'kind': 'setFormValue', 'fieldId': f['fieldId'], 'expectedFieldSha256': f['expectedFieldSha256'],
             'name': f['name'], 'fieldKind': f['kind'], **value} for f, value in
            [(target, {'value': 'Manual'}), (other, {'checked': True})]]
    seen = []

    async def planner(**kwargs):
        seen.append(deepcopy(kwargs['selected']))
        return await fill_candidate(**kwargs)

    ai = NativePDFFormService(editor, planner=planner, enabled=True)
    body = {**payload(context, model), 'operations': base}
    started = await ai.start(session, **body)
    status = await ai.status(session, started['editId'], wait_ms=20000)
    assert status['status'] == 'succeeded', status
    assert seen[0][0]['value'] == 'Manual' and len(seen[0]) == 1
    proposal = status['result']['proposal']
    assert len(proposal['operations']) == 2
    assert proposal['changes'][0]['before'] == 'Manual'
    with pytest.raises(ReportingError):
        await ai.accept(session, started['editId'], expected_sha256=context.source_file.sha256,
                        operations=[], snapshot_sha256=status['snapshotSha256'])
    accepted = await ai.accept(session, started['editId'], expected_sha256=context.source_file.sha256,
                               operations=base, snapshot_sha256=status['snapshotSha256'])
    receipt = await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=accepted['operations'])
    fields = PdfReader(BytesIO(receipt['content'])).get_fields()
    assert fields['customer']['/V'] == 'Bob' and fields['consent']['/V'] != '/Off'
    assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('forgery', ['hash', 'scope', 'kind'])
async def test_form_service_rejects_forged_candidate(form_sample, forgery):
    editor, context, session, _, _, model = form_sample

    async def planner(**kwargs):
        result = await fill_candidate(**kwargs)
        op = result['operations'][0]
        if forgery == 'hash':
            op['expectedFieldSha256'] = '0' * 64
        elif forgery == 'scope':
            op['fieldId'] = next(f['fieldId'] for f in model['formFields'] if f['name'] == 'consent')
        else:
            op['kind'] = 'deletePage'
        return result

    ai = NativePDFFormService(editor, planner=planner, enabled=True)
    started = await ai.start(session, **payload(context, model))
    status = await ai.status(session, started['editId'], wait_ms=20000)
    assert status['status'] == 'failed' and 'result' not in status
    await ai.aclose()


@pytest.mark.anyio
async def test_form_precancel_and_swallowed_cancel_never_revive(form_sample):
    editor, context, session, _, _, model = form_sample
    entered = asyncio.Event()

    async def planner(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return await fill_candidate(**kwargs)

    ai = NativePDFFormService(editor, planner=planner, enabled=True)
    await ai.cancel_request(session, 'form-1')
    assert (await ai.start(session, **payload(context, model)))['status'] == 'cancelled'
    started = await ai.start(session, **{**payload(context, model), 'client_request_id': 'form-2'})
    await entered.wait()
    await ai.aclose()
    assert (await ai.status(session, started['editId'], wait_ms=0))['status'] == 'cancelled'


@pytest.mark.anyio
async def test_form_empty_candidate_fails_and_http_guards(form_sample):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
    from smart_reporting.report_editor.native_pdf_form_ai_api import (
        create_native_pdf_form_ai_router,
    )

    editor, context, session, token, _, model = form_sample
    ai = NativePDFFormService(editor, planner=AsyncMock(return_value={
        'answer': '未能提出填写候选', 'summary': '', 'operations': []}), enabled=True)
    app = FastAPI()
    app.include_router(create_native_pdf_form_ai_router(editor.grants, editor=editor, forms=ai, allowed_origin='http://test'))
    base = f'/reports/v1/native/{context.document_id}/1/api/ai/forms'
    headers = {'Origin': 'http://test', 'X-CSRF-Token': editor.grants.csrf_token(token)}
    body = payload(context, model)
    body = {'clientRequestId': body['client_request_id'], 'expectedSha256': body['expected_sha256'],
            'operations': [], 'selection': body['selection'], 'instruction': body['instruction']}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post(base + '/start', json=body)).status_code == 403
        client.cookies.set(NATIVE_SESSION_COOKIE, token)
        assert (await client.post(base + '/start', json=body)).status_code == 403
        assert (await client.post(base + '/start', json={**body, 'selection': []}, headers=headers)).status_code == 422
        response = await client.post(base + '/start', json=body, headers=headers)
        assert response.status_code == 200
        edit_id = response.json()['editId']
        status = (await client.get(base + f'/{edit_id}?waitMs=20000')).json()
        assert status['status'] == 'failed' and status['error']['code'] == 'native_ai_output_empty'
        assert (await client.get(base.replace('/1/', '/2/') + f'/{edit_id}')).status_code == 403
        assert (await client.get(base + f'/{edit_id}/events')).status_code == 200
        assert (await client.post(base + '/cancel', json={'clientRequestId': 'form-1'}, headers=headers)).json()['status'] == 'cancelled'
    await ai.aclose()


@pytest.mark.anyio
async def test_form_accept_cancellation_cannot_revive_candidate(form_sample, monkeypatch):
    editor, context, session, _, _, model = form_sample
    ai = NativePDFFormService(editor, planner=fill_candidate, enabled=True)
    started = await ai.start(session, **payload(context, model))
    status = await ai.status(session, started['editId'], wait_ms=20000)
    assert status['status'] == 'succeeded', status
    entered, release = asyncio.Event(), asyncio.Event()
    original = type(editor).preview_file

    async def delayed(self, *args, **kwargs):
        receipt = await original(self, *args, **kwargs)
        entered.set()
        await release.wait()
        return receipt

    monkeypatch.setattr(type(editor), 'preview_file', delayed)
    acceptance = asyncio.create_task(ai.accept(session, started['editId'],
        expected_sha256=context.source_file.sha256, operations=[], snapshot_sha256=status['snapshotSha256']))
    await asyncio.wait_for(entered.wait(), 20)
    await ai.cancel_request(session, 'form-1')
    release.set()
    with pytest.raises(ReportingError, match='取消'):
        await acceptance
    await ai.aclose()


@pytest.mark.anyio
async def test_form_swallowed_timeout_does_not_publish_candidate(form_sample):
    editor, context, session, _, _, model = form_sample

    async def planner(**kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return await fill_candidate(**kwargs)

    ai = NativePDFFormService(editor, planner=planner, enabled=True, timeout_seconds=3)
    started = await ai.start(session, **payload(context, model))
    status = await ai.status(session, started['editId'], wait_ms=20000)
    assert status['status'] == 'failed' and status['error']['code'] == 'native_ai_timeout'
    assert 'result' not in status
    await ai.aclose()


@pytest.mark.anyio
async def test_form_context_flag_requires_pdf_edit_but_not_text(form_sample):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor.native_api import (
        NATIVE_SESSION_COOKIE,
        create_native_editor_router,
    )

    editor, context, _, token, _, _ = form_sample
    app = FastAPI()
    app.include_router(create_native_editor_router(editor.grants, editor=editor, ai_enabled=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token)
        response = await client.get(f'/reports/v1/native/{context.document_id}/1/api/context')
        assert response.json()['pdfFormAIEnabled'] is True
        assert response.json()['pdfTextEnabled'] is False
        editor.pdf_enabled = False
        response = await client.get(f'/reports/v1/native/{context.document_id}/1/api/context')
        assert response.json()['pdfFormAIEnabled'] is False
