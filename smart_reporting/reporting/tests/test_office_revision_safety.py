"""Office 修订并发、参数边界与请求内文件读取回归。"""

import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor import slides, workbook
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.report_editor.slides_api import create_report_slides_editor_router
from smart_reporting.report_editor.workbook_api import create_report_workbook_editor_router
from smart_reporting.reporting.tests.test_slides_editor_service import _context as slides_context
from smart_reporting.reporting.tests.test_slides_editor_service import _session as slides_session
from smart_reporting.reporting.tests.test_workbook_editor import _bytes
from smart_reporting.reporting.tests.test_workbook_editor import _context as workbook_context
from smart_reporting.reporting.tests.test_workbook_editor import _session as workbook_session
from smart_reporting.reporting.workflow.state import (
    ReportingCommand,
    ReportingRunState,
    ReportingStateConflict,
    ReportingStateError,
    ReportingStateReducer,
)


class ConcurrentRepository:
    def __init__(self, context):
        self.state = ReportingRunState.initial(
            report_run_id=context.workflow_run_id, external_run_id=context.workflow_run_id,
            thread_id=context.scope['threadId'], owner_user_id=context.scope['userId'],
            payload={'reportEditorContexts': {'1': context.model_dump(mode='json', by_alias=True)}},
        )
        self.conflicts = 0

    async def get(self, _run):
        state = self.state.model_copy(deep=True)
        await asyncio.sleep(0)
        return state

    async def apply(self, _run, command, *, expected_version):
        await asyncio.sleep(0)
        try:
            result = ReportingStateReducer.apply(self.state, command, expected_version)
        except ReportingStateConflict:
            self.conflicts += 1
            raise
        self.state = result.state
        return result


@pytest.mark.anyio
@pytest.mark.parametrize('kind', ['slides', 'workbook'])
async def test_concurrent_office_saves_register_distinct_revisions_and_keep_downloads(monkeypatch, kind):
    source = _bytes()
    context = slides_context() if kind == 'slides' else workbook_context(source)
    repo = ConcurrentRepository(context)
    files = {context.pptx_path if kind == 'slides' else context.xlsx_path: source}

    async def read(_thread, path):
        return files[path], 'application/octet-stream'

    async def write(_thread, path, content, **kwargs):
        assert path not in files
        files[path] = content

    async def identity(_thread, path):
        data = files[path]
        return {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    cls = slides.ReportSlidesEditorService if kind == 'slides' else workbook.ReportWorkbookEditorService
    service = cls(state_repository=repo, workspace_registry=None,
        workspace=SimpleNamespace(afile_bytes=read, awrite_bytes=write, ahash_file=identity), editor_grants=grants)

    async def current(_session):
        return context

    service.context_for_session = current
    if kind == 'slides':
        async def read_pptx(_context):
            return source

        service._read_verified_pptx = read_pptx
        monkeypatch.setattr(service, '_run_engine', lambda *args, **kw: {'bytes': b'edited', 'issues': []})
        monkeypatch.setattr(service, '_render_pdf', lambda content: b'pdf')
        session = slides_session(context)
        expected = context.pptx_sha256
        artifact = 'pptx'
    else:
        monkeypatch.setattr(workbook, 'patch_workbook', lambda data, ops: data)
        monkeypatch.setattr(workbook, 'inspect_workbook', lambda data: {'sheets': [{'name': 'Sheet1'}]})
        session = workbook_session(context)
        expected = context.xlsx_sha256
        artifact = 'xlsx'

    results = await asyncio.gather(*[
        service.save_revision(session, {
            'expectedSha256': expected,
            **({'edits': [{'slideIndex': 0, 'elementId': 'text1', 'text': '已修改结论'}]} if kind == 'slides' else {}),
        }) for _ in range(4)
    ])
    assert sorted(result['revision'] for result in results) == [2, 3, 4, 5]
    assert set(repo.state.payload['reportEditorContexts']) == {'1', '2', '3', '4', '5'}
    assert repo.conflicts > 0  # 强制交错，必须真正走过 CAS 冲突重试。
    for result in results:
        assert result[artifact]['downloadUrl']
        assert result['editor']['openUrl']
        assert result['validation']['ok'] is False
        assert {issue['code'] for issue in result['validation']['issues']} == {
            f'{artifact if kind == "slides" else "workbook"}_semantic_verification_pending',
        }
        registered = repo.state.payload['reportEditorContexts'][str(result['revision'])]
        assert registered['job']['validation']['ok'] is False
        assert registered[f'{artifact}Path'] == result[artifact]['path']


@pytest.mark.anyio
@pytest.mark.parametrize('field', ['kind', 'effect', 'trigger'])
@pytest.mark.parametrize('value', [[], {}, None])
async def test_slides_enum_shape_errors_return_business_error(tmp_path, field, value):
    context = slides_context()
    service = slides.ReportSlidesEditorService(state_repository=None, workspace_registry=None, workspace=None)

    async def current(_session):
        return context

    service.context_for_session = current
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context, capabilities={'pptx_editor': True})
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(grants, slides=service, static_dir=tmp_path, cookie_secure=False))
    payload = {'expectedSha256': context.pptx_sha256}
    if field == 'kind':
        payload['transitions'] = [{'slideIndex': 0, 'kind': value}]
    else:
        payload['animations'] = [{'slideIndex': 0, 'elementId': 's1', 'effect': 'fade', 'trigger': 'onClick', field: value}]
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        opened = await client.get(f'/reports/v1/slides/open/{raw}')
        response = await client.post(opened.headers['location'] + '/api/save', json=payload,
            headers={'X-CSRF-Token': client.cookies.get('report_slides_csrf')})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'report_slides_edit_invalid'


@pytest.mark.anyio
async def test_workbook_file_reads_once_and_rechecks_identity_on_next_request(tmp_path, monkeypatch):
    content = _bytes()
    context = workbook_context(content)
    repo = ConcurrentRepository(context)
    reads = 0

    async def read(*args):
        nonlocal reads
        reads += 1
        return content, 'application/octet-stream'

    monkeypatch.setattr(workbook, 'resolve_reporting_workflow_scope', lambda **kw: SimpleNamespace(workspace_key='thread'))
    service = workbook.ReportWorkbookEditorService(state_repository=repo,
        workspace_registry=SimpleNamespace(resolve=lambda scope: None), workspace=SimpleNamespace(afile_bytes=read))
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context, capabilities={'xlsx_editor': True})
    app = FastAPI()
    app.include_router(create_report_workbook_editor_router(grants, workbooks=service, static_dir=tmp_path, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        opened = await client.get(f'/reports/v1/workbooks/open/{raw}')
        reads = 0
        response = await client.get(opened.headers['location'] + '/api/file')
        assert response.status_code == 200
        assert response.content == content
        assert reads == 1
        content = b'tampered'
        response = await client.get(opened.headers['location'] + '/api/file')
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'report_workbook_identity_changed'
        assert reads == 2


def test_revision_reservation_is_idempotent_and_does_not_reuse_unsaved_numbers():
    state = ConcurrentRepository(slides_context()).state
    command = ReportingCommand(name='reserve_report_editor_revision', payload={'minimumRevision': 1}, commandId='first')
    state = ReportingStateReducer.apply(state, command).state
    assert state.payload['reportEditorRevisionCounter'] == 2
    replay = ReportingStateReducer.apply(state, command)
    assert replay.idempotent
    assert replay.state.payload['reportEditorRevisionCounter'] == 2
    following = command.model_copy(update={'command_id': 'second'})
    state = ReportingStateReducer.apply(replay.state, following).state
    assert state.payload['reportEditorRevisionCounter'] == 3
    assert set(state.payload['reportEditorContexts']) == {'1'}


@pytest.mark.parametrize('minimum', [True, 0, '2', None])
def test_revision_reservation_rejects_invalid_minimum_without_mutating_state(minimum):
    state = ConcurrentRepository(slides_context()).state
    command = ReportingCommand(name='reserve_report_editor_revision', payload={'minimumRevision': minimum}, commandId='invalid')
    with pytest.raises(ReportingStateError):
        ReportingStateReducer.apply(state, command)
    assert 'reportEditorRevisionCounter' not in state.payload
