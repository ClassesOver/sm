"""共同数据编辑入口沿用编辑器会话作用域及Origin/CSRF，不接受路径。"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor import InMemoryReportEditorRepository, ReportEditorGrantService
from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router
from smart_reporting.reporting.tests.test_report_data_revision_service import (
    attach_runner,
    service_case,
)
from smart_reporting.reporting.trace.contracts_v1 import canonical_json_bytes
from smart_reporting.reporting.workflow.state import ReportingCommand

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize('anyio_backend', ['asyncio'])]


async def api_case(capabilities=None):
    service, context, _repository, files, editor = service_case()
    attach_runner(service, files)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context, capabilities=capabilities)
    token, _session = await grants.exchange(raw)

    async def restore(session):
        return context

    editor.context_for_session = restore
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, data_revisions=service, cookie_secure=False))
    return app, grants, token, service, context


async def test_data_api_freeze_edit_read_uses_registered_snapshot_without_returning_server_paths():
    app, grants, token, service, context = await api_case()
    prefix = '/reports/v1/editor/report-1/1/api/data-revisions'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', cookies={EDITOR_SESSION_COOKIE: token}) as client:
        headers = {'origin': 'http://test', 'x-csrf-token': grants.csrf_token(token)}
        frozen = await client.post(prefix + '/freeze', headers=headers)
        assert frozen.status_code == 200, frozen.text
        data = frozen.json()
        assert data['tables'][0]['rows'] == [['2026-09', 120], ['2026-10', 150]]
        assert 'path' not in frozen.text and 'script' not in frozen.text
        revised = await client.post(prefix, headers=headers, json={
            'expectedSnapshotId': data['snapshotId'],
            'edits': [{'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180}],
        })
        assert revised.status_code == 200, revised.text
        assert revised.json()['snapshotId'] != data['snapshotId']
        assert 'path' not in revised.text
        stale = await client.post(prefix, headers=headers, json={
            'expectedSnapshotId': data['snapshotId'],
            'edits': [{'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 190}],
        })
        assert stale.status_code == 409
        historical = await client.get(prefix + '/' + data['snapshotId'])
        assert historical.status_code == 200 and historical.json()['tables'][0]['rows'][1][1] == 150


@pytest.mark.parametrize('fault', ['csrf', 'origin', 'scope', 'path'])
async def test_data_api_rejects_unauthorized_edit_without_creating_snapshot(fault):
    app, grants, token, service, context = await api_case()
    prefix = '/reports/v1/editor/report-1/1/api/data-revisions'
    payload = {'expectedSnapshotId': 'missing', 'edits': [
        {'tableId': 'table_a', 'row': 1, 'column': 'value', 'expectedValue': 150, 'value': 180},
    ]}
    headers = {'origin': 'http://test', 'x-csrf-token': grants.csrf_token(token)}
    if fault == 'csrf':
        headers['x-csrf-token'] = 'wrong'
    if fault == 'origin':
        headers['origin'] = 'http://foreign'
    if fault == 'scope':
        prefix = prefix.replace('report-1/1', 'foreign/1')
    if fault == 'path':
        payload['edits'][0]['path'] = '/tmp/foreign.json'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', cookies={EDITOR_SESSION_COOKIE: token}) as client:
        result = await client.post(prefix, headers=headers, json=payload)
    assert result.status_code == {'csrf': 403, 'origin': 403, 'scope': 404, 'path': 422}[fault]
    assert await service._history(context) == {}


async def test_restricted_share_session_cannot_read_or_edit_frozen_data():
    app, grants, token, service, context = await api_case({'download_original': False})
    prefix = '/reports/v1/editor/report-1/1/api/data-revisions'
    headers = {'origin': 'http://test', 'x-csrf-token': grants.csrf_token(token)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', cookies={EDITOR_SESSION_COOKIE: token}) as client:
        frozen = await client.post(prefix + '/freeze', headers=headers)
        read = await client.get(prefix + '/unknown')
    assert frozen.status_code == read.status_code == 403
    assert await service._history(context) == {}


@pytest.mark.parametrize('restricted', [False, True])
async def test_export_endpoint_checks_origin_csrf_and_full_access(restricted):
    app, grants, token, service, _context = await api_case({'download_original': False} if restricted else None)
    calls = []

    async def export(context, snapshot_id):
        calls.append((context.report_id, snapshot_id))
        return {'snapshotId': snapshot_id, 'exportId': 'export-1'}

    service.export = export
    path = '/reports/v1/editor/report-1/1/api/data-revisions/snapshot-1/export'
    headers = {'origin': 'http://test', 'x-csrf-token': grants.csrf_token(token)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', cookies={EDITOR_SESSION_COOKIE: token}) as client:
        assert (await client.post(path, headers=headers | {'origin': 'http://foreign'})).status_code == 403
        assert (await client.post(path, headers=headers | {'x-csrf-token': 'invalid'})).status_code == 403
        response = await client.post(path, headers=headers)
    if restricted:
        assert response.status_code == 403 and calls == []
    else:
        assert response.status_code == 200 and calls == [('report-1', 'snapshot-1')]
        assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('fault', [None, 'restricted', 'tampered', 'wrong_snapshot', 'wrong_report'])
async def test_export_history_uses_registered_manifest_and_hides_file_paths(fault):
    app, _grants, token, service, context = await api_case(
        {'download_original': False} if fault == 'restricted' else None,
    )
    snapshot = await service.freeze(context)
    snapshot_id = snapshot['snapshotId']
    export_id = 'export-1'
    path = f'reports/.data-exports/{export_id}/export-manifest.json'
    manifest = {'schema': 'report-data-export/v1', 'exportId': export_id, 'reportId': context.report_id,
        'baseRevision': context.revision, 'revision': 2, 'snapshotId': snapshot_id,
        'chartRevisions': {'chart_a': 'chart-revision-1'}, 'artifacts': {
            'pdf': {'path': f'reports/.data-exports/{export_id}/report.pdf', 'size': 42, 'sha256': 'a' * 64},
        }, 'validation': {'ok': False, 'issues': [{'code': 'review_pending', 'message': '待复核'}]}}
    identity = await service._write_file(context, path, canonical_json_bytes(manifest))
    repository = service.editor.state_repository
    state = await repository.get(context.workflow_run_id)
    await repository.apply(context.workflow_run_id, ReportingCommand(
        name='record_report_data_export', commandId='test-data-export',
        payload={'export': {key: manifest[key] for key in ('reportId', 'baseRevision', 'revision', 'snapshotId', 'exportId')}
            | {'manifest': identity}},
    ), expected_version=state.state_version)
    if fault == 'tampered':
        await service.editor.workspace.awrite_bytes(context.scope['threadId'], path, b'{}', overwrite=True)
    report_id = 'foreign-report' if fault == 'wrong_report' else context.report_id
    requested = 'foreign-snapshot' if fault == 'wrong_snapshot' else snapshot_id
    url = f'/reports/v1/editor/{report_id}/1/api/data-revisions/{requested}/exports/{export_id}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', cookies={EDITOR_SESSION_COOKIE: token}) as client:
        response = await client.get(url)
    assert response.status_code == {None: 200, 'restricted': 403, 'tampered': 422,
        'wrong_snapshot': 404, 'wrong_report': 404}[fault]
    if fault is None:
        assert response.headers['cache-control'] == 'no-store'
        assert response.json() == {'exportId': export_id, 'snapshotId': snapshot_id, 'revision': 2,
            'chartRevisions': {'chart_a': 'chart-revision-1'},
            'artifacts': {'pdf': {'size': 42, 'sha256': 'a' * 64}}, 'validation': manifest['validation']}
        assert path not in response.text and 'downloadUrl' not in response.text
