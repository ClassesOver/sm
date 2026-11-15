"""原生 XLSX AI 的范围、草稿与请求取消契约。"""
import asyncio
from copy import deepcopy

import pytest

from smart_reporting.report_editor.native_models import NativeEditorContext, NATIVE_MEDIA
from smart_reporting.report_editor.workbook_ai import WorkbookAIProposal
from smart_reporting.reporting.models import ReportingError


class Editor:
    def __init__(self):
        self.context = NativeEditorContext(documentId="workbook", revision=1, format="xlsx", origin="upload",
            scope={"database": "db", "companyId": "co", "userId": "user", "threadId": "thread"},
            sourceFile={"path": "native/source.xlsx", "size": 10, "sha256": "a" * 64, "mediaType": NATIVE_MEDIA["xlsx"]})
        self.previews = []

    async def read_file(self, _context):
        # Controlled editor; HTTP accept now rechecks file identity after preview.
        return b"synthetic source"

    async def context_for_session(self, _session):
        return self.context

    def require_enabled(self, format):
        assert format == "xlsx"

    async def preview(self, _context, *, expected_sha256, operations):
        self.previews.append(deepcopy(operations))
        return {"draftSha256": "b" * 64, "model": {"sheets": [{"name": "Sheet", "cells": {"A1": {"value": "人工未保存值"}, "B1": {"value": "范围外私密值"}}}]}}


def proposal(column=0):
    return WorkbookAIProposal.model_validate({"summary": "修改选区", "operations": [{"kind": "applyCellEdits",
        "arguments": {"edits": [{"sheetName": "Sheet", "row": 0, "column": column, "writeValue": True, "cell": {"value": "候选"}}]}}]})


async def start(ai, **kwargs):
    return await ai.start_edit(None, client_request_id="request-1", instruction="改成候选", expected_sha256="a" * 64,
        operations=kwargs.pop("operations", []), selection={"sheetName": "Sheet", "startRow": 0, "endRow": 0, "startColumn": 0, "endColumn": 0}, **kwargs)


@pytest.mark.anyio
async def test_native_xlsx_ai_binds_full_draft_and_only_quotes_frozen_range():
    from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
    prompts = []
    async def planner(prompt, **_kwargs):
        prompts.append(prompt)
        return proposal()
    editor = Editor(); ai = NativeWorkbookAIService(editor, planner=planner, enabled=True)
    base = [{"kind": "applyColumnWidths", "sheetName": "Sheet", "entries": [{"index": 1, "widthChars": 20}]}]
    job = await start(ai, operations=base)
    result = await ai.wait_edit_status(None, job["editId"])
    assert result["status"] == "succeeded", result
    assert "人工未保存值" in prompts[0] and "范围外私密值" not in prompts[0]
    accepted = await ai.accept_edit(None, job["editId"], expected_sha256="a" * 64, operations=base, snapshot_sha256=result["snapshotSha256"])
    assert accepted["operations"] == base + proposal().engine_operations()
    with pytest.raises(ReportingError):
        await ai.accept_edit(None, job["editId"], expected_sha256="a" * 64, operations=[], snapshot_sha256=result["snapshotSha256"])
    await ai.aclose()


@pytest.mark.anyio
async def test_native_xlsx_ai_rejects_outside_range_and_cancels_before_receipt():
    from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
    calls = []
    async def planner(*_args, **_kwargs):
        calls.append(True)
        return proposal(1)
    ai = NativeWorkbookAIService(Editor(), planner=planner, enabled=True)
    job = await start(ai); result = await ai.wait_edit_status(None, job["editId"])
    assert result["status"] == "failed" and "proposal" not in result
    await ai.cancel_request(None, "early")
    result = await ai.start_edit(None, client_request_id="early", instruction="改", expected_sha256="a" * 64, operations=[], selection={}, scope="workbook")
    assert result["status"] == "cancelled" and len(calls) == 1
    await ai.aclose()

@pytest.mark.anyio
async def test_native_xlsx_ai_real_engine_and_independent_formula_readback():
    import hashlib
    from io import BytesIO
    from openpyxl import Workbook, load_workbook
    from smart_reporting.report_editor.native_office import inspect_office, patch_office
    from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
    workbook = Workbook(); workbook.active['A1'] = 2; workbook.active['B1'] = 3
    stream = BytesIO(); workbook.save(stream); content = stream.getvalue()
    class RealEditor(Editor):
        def __init__(self):
            super().__init__()
            raw = self.context.model_dump(by_alias=True); raw['sourceFile'].update(sha256=hashlib.sha256(content).hexdigest(), size=len(content))
            self.context = NativeEditorContext.model_validate(raw)
        async def preview(self, _context, *, expected_sha256, operations):
            assert expected_sha256 == self.context.source_file.sha256
            edited = await asyncio.to_thread(patch_office, 'xlsx', content, operations)
            return {'draftSha256': hashlib.sha256(edited).hexdigest(), 'model': await asyncio.to_thread(inspect_office, 'xlsx', edited)}
    async def planner(prompt, **_kwargs):
        assert '人工值' in prompt
        return WorkbookAIProposal.model_validate({'summary': '写入求和公式', 'operations': [{'kind': 'applyCellEdits', 'arguments': {'edits': [
            {'sheetName': 'Sheet', 'row': 1, 'column': 0, 'writeValue': True, 'cell': {'value': None, 'formula': 'SUM(A1:B1)'}}]}}]})
    editor = RealEditor(); ai = NativeWorkbookAIService(editor, planner=planner, enabled=True)
    base = [{'kind': 'applyCellEdits', 'edits': [{'sheetName': 'Sheet', 'row': 2, 'column': 0, 'writeValue': True, 'cell': {'value': '人工值'}}]}]
    job = await ai.start_edit(None, client_request_id='real', instruction='A2写入求和公式', expected_sha256=editor.context.source_file.sha256, operations=base, selection={}, scope='workbook')
    result = await ai.wait_edit_status(None, job['editId']); assert result['status'] == 'succeeded', result
    accepted = await ai.accept_edit(None, job['editId'], expected_sha256=editor.context.source_file.sha256, operations=base, snapshot_sha256=result['snapshotSha256'])
    edited = await asyncio.to_thread(patch_office, 'xlsx', content, accepted['operations'])
    reopened = load_workbook(BytesIO(edited)); assert reopened.active['A2'].value == '=SUM(A1:B1)'; assert reopened.active['A3'].value == '人工值'
    assert load_workbook(BytesIO(content)).active['A2'].value is None
    await ai.aclose()


@pytest.mark.anyio
async def test_native_xlsx_ai_http_scope_csrf_selection_and_cancel_request():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from types import SimpleNamespace
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
    from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
    from smart_reporting.report_editor.workbook_native_ai_api import create_native_workbook_ai_router
    class Grants:
        def csrf_token(self, _raw): return 'csrf'
        async def lookup_session(self, raw):
            assert raw == 'session'
            return SimpleNamespace(report_id='workbook', revision=1)
    async def planner(*_args, **_kwargs): return proposal()
    editor = Editor(); ai = NativeWorkbookAIService(editor, planner=planner, enabled=True)
    app = FastAPI(); app.include_router(create_native_workbook_ai_router(Grants(), editor=editor, ai=ai, allowed_origin='https://editor.test'))
    base = '/reports/v1/native/workbook/1/api/workbook-ai'
    payload = {'clientRequestId': 'http', 'instruction': '修改', 'expectedSha256': 'a'*64, 'operations': [],
        'selection': {'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0}}
    headers = {'Origin': 'https://editor.test', 'X-CSRF-Token': 'csrf'}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='https://editor.test', cookies={NATIVE_SESSION_COOKIE: 'session'}) as client:
        assert (await client.post(base+'/start', json=payload)).status_code == 403
        assert (await client.post(base.replace('/workbook/1/', '/workbook/2/')+'/start', json=payload, headers=headers)).status_code == 403
        assert (await client.post(base+'/start', json={**payload, 'path': '/tmp/foreign'}, headers=headers)).status_code == 422
        assert (await client.post(base+'/start', json={**payload, 'selection': {**payload['selection'], 'startRow': True}}, headers=headers)).status_code == 422
        cancelled = await client.post(base+'/cancel-request', json={'clientRequestId': 'http'}, headers=headers)
        started = await client.post(base+'/start', json=payload, headers=headers)
        assert started.status_code == 200 and started.json()['status'] == 'cancelled'
        assert started.json()['editId'] == cancelled.json()['editId']
        started = await client.post(base+'/start', json={**payload, 'clientRequestId': 'ready'}, headers=headers)
        job = (await client.get(base+'/'+started.json()['editId'])).json(); assert job['status'] == 'succeeded', job
        accepted = await client.post(base+'/'+job['editId']+'/accept', json={'expectedSha256': 'a'*64, 'operations': [], 'snapshotSha256': job['snapshotSha256']}, headers=headers)
        assert accepted.status_code == 200 and accepted.json()['accepted'] is True
        raw = editor.context.model_dump(by_alias=True); raw['scope']['companyId'] = 'other'; editor.context = NativeEditorContext.model_validate(raw)
        assert (await client.get(base+'/'+job['editId'])).status_code == 404
    await ai.aclose()

@pytest.mark.anyio
@pytest.mark.parametrize('phase', ['base_preview', 'planner', 'candidate_preview'])
async def test_native_xlsx_ai_cancelled_dependency_cannot_resume_or_publish(phase):
    from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
    entered = asyncio.Event(); planner_calls = []
    class SwallowEditor(Editor):
        async def preview(self, context, *, expected_sha256, operations):
            if phase == ('candidate_preview' if operations else 'base_preview'):
                entered.set()
                try: await asyncio.sleep(30)
                except asyncio.CancelledError: pass
            return await super().preview(context, expected_sha256=expected_sha256, operations=operations)
    async def planner(*_args, **_kwargs):
        planner_calls.append(True)
        if phase == 'planner':
            entered.set()
            try: await asyncio.sleep(30)
            except asyncio.CancelledError: pass
        return proposal()
    ai = NativeWorkbookAIService(SwallowEditor(), planner=planner, enabled=True)
    job = await start(ai); await entered.wait()
    await ai.cancel_request(None, 'request-1')
    status = await ai.wait_edit_status(None, job['editId'])
    assert status['status'] == 'cancelled' and 'proposal' not in status
    assert len(planner_calls) == (0 if phase == 'base_preview' else 1)
    await ai.aclose()

@pytest.mark.anyio
async def test_native_xlsx_ai_prompt_disambiguates_boolean_write_flag_from_numeric_value():
    from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
    async def planner(prompt, **_kwargs):
        assert 'writeValue 必须是 JSON 布尔值 true 或 false' in prompt
        assert '"writeValue": true' in prompt and '"value": 59' in prompt
        assert '不能把 59 等待写入值填入 writeValue' in prompt
        planned = proposal().model_dump(mode='json')
        planned['operations'][0]['arguments']['edits'][0]['cell']['value'] = 59
        return WorkbookAIProposal.model_validate(planned)
    ai = NativeWorkbookAIService(Editor(), planner=planner, enabled=True)
    job = await start(ai); result = await ai.wait_edit_status(None, job['editId'])
    assert result['status'] == 'succeeded', result
    assert result['proposal']['operations'][0]['edits'][0]['writeValue'] is True
    assert result['proposal']['operations'][0]['edits'][0]['cell']['value'] == 59
    await ai.aclose()


def test_native_xlsx_ai_real_engine_never_coerces_numeric_write_flag():
    from smart_reporting.report_editor.native_office import patch_office
    from smart_reporting.reporting.tests.test_native_office import workbook_bytes
    operation = proposal().engine_operations()[0]
    operation['edits'][0].update(writeValue=59, cell={'value': 59})
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        patch_office('xlsx', workbook_bytes(), [operation])
    assert operation['edits'][0]['writeValue'] == 59
