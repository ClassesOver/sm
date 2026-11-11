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

    async def file_for_session(self, session):
        return await self.context_for_session(session), _bytes()


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
        malformed = await client.post(base + '/api/snapshot', content=b'{not json',
            headers={'X-CSRF-Token': token, 'Content-Type': 'application/json'})
        assert malformed.status_code == 400
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


@pytest.mark.anyio
async def test_workbook_download_keeps_chinese_filename_in_rfc5987_header(tmp_path):
    context = _context(_bytes()).model_copy(update={"xlsx_path": "报表/智能分析/run/revision-1/医院运营分析报告_2025.xlsx"})
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context, capabilities={'xlsx_download': True})

    class Downloads(Workbooks):
        async def download_for_session(self, _session):
            return context, b'xlsx-bytes'

    app = FastAPI()
    app.include_router(create_report_workbook_editor_router(grants, workbooks=Downloads(), static_dir=tmp_path, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://report.test') as client:
        response = await client.get(f'/reports/v1/workbooks/download/{raw}')

    assert response.status_code == 200
    assert response.headers['content-disposition'] == (
        'attachment; filename="report.xlsx"; filename*=UTF-8\'\''
        '%E5%8C%BB%E9%99%A2%E8%BF%90%E8%90%A5%E5%88%86%E6%9E%90%E6%8A%A5%E5%91%8A_2025.xlsx'
    )


@pytest.mark.anyio
async def test_workbook_file_supplies_trusted_unicode_source_path_for_filename_formulas(tmp_path):
    from urllib.parse import unquote

    context = _context(_bytes()).model_copy(update={"xlsx_path": "报表/智能分析/运营 %.xlsx"})
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context, capabilities={'xlsx_editor': True})

    class Files(Workbooks):
        async def file_for_session(self, _session):
            return context, b'xlsx-bytes'

    app = FastAPI()
    app.include_router(create_report_workbook_editor_router(grants, workbooks=Files(), static_dir=tmp_path, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://report.test') as client:
        opened = await client.get(f'/reports/v1/workbooks/open/{raw}')
        response = await client.get(opened.headers['location'] + '/api/file')
    assert response.status_code == 200
    assert unquote(response.headers['X-Workbook-Path']) == context.xlsx_path
    assert response.headers['X-Workbook-Sha256'] == context.xlsx_sha256
    assert response.content == b'xlsx-bytes'
