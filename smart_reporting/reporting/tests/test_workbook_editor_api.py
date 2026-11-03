from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.report_editor.workbook_api import (
    WORKBOOK_CSRF_COOKIE,
    create_report_workbook_editor_router,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_workbook_editor import _bytes, _context


class Workbooks:
    def __init__(self):
        self.snapshots = []

    async def context_for_session(self, session):
        if session.capabilities != {'xlsx_editor': True}:
            raise ReportingError('report_workbook_permission_denied', '没有工作簿编辑权限')
        return _context(_bytes())

    async def snapshot_for_session(self, _session, operations):
        self.snapshots.append(operations)
        return {'snapshotSha256': 'c' * 64, 'workbook': {'sheets': []}}


@pytest.mark.anyio
async def test_workbook_api_scopes_cookie_and_requires_csrf_for_unsaved_snapshot(tmp_path):
    (tmp_path / 'index.html').write_text('<main>shared editor shell</main>')
    context = _context(_bytes())
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context, capabilities={'xlsx_editor': True})
    workbooks = Workbooks()
    app = FastAPI()
    app.include_router(create_report_workbook_editor_router(grants,workbooks=workbooks,static_dir=tmp_path,cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://report.test') as client:
        opened = await client.get(f'/reports/v1/workbooks/open/{raw}')
        base = opened.headers['location']
        assert base == '/reports/v1/workbooks/report-xlsx/1'
        assert f'Path={base}' in opened.headers['set-cookie']
        page = await client.get(base)
        assert page.text == '<main>shared editor shell</main>'
        denied = await client.post(base + '/api/snapshot',json={'operations':[]})
        assert denied.status_code == 403
        token = client.cookies.get(WORKBOOK_CSRF_COOKIE)
        operations = [{'kind':'applyCellEdits','edits':[]}]
        result = await client.post(base + '/api/snapshot',json={'operations':operations},headers={'X-CSRF-Token':token})
        assert result.status_code == 200
        assert workbooks.snapshots == [operations]
        wrong_scope = await client.get('/reports/v1/workbooks/another/1')
        assert wrong_scope.status_code in {403,409}


@pytest.mark.anyio
async def test_workbook_api_accept_binds_candidate_to_server_recomputed_unsaved_snapshot(tmp_path):
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(),secret='s'*32)
    raw,_ = await grants.issue(_context(_bytes()),capabilities={'xlsx_editor':True})
    workbooks = Workbooks()
    class AI:
        async def mark_accepted(self,_session,edit_id,*,snapshot_sha256):
            assert edit_id == 'edit'
            assert snapshot_sha256 == 'c' * 64
            return {'accepted':True}
    app = FastAPI()
    app.include_router(create_report_workbook_editor_router(grants,workbooks=workbooks,workbook_ai=AI(),static_dir=tmp_path,cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://report.test') as client:
        opened = await client.get('/reports/v1/workbooks/open/'+raw)
        operations=[{'kind':'applyCellEdits','edits':[]}]
        result=await client.post(opened.headers['location']+'/api/ai/edit/accept',json={'snapshotSha256':'forged-client-hash','operations':operations},headers={'X-CSRF-Token':client.cookies.get(WORKBOOK_CSRF_COOKIE)})
    assert result.status_code == 200
    assert result.json()['accepted'] is True
    assert workbooks.snapshots == [operations]
