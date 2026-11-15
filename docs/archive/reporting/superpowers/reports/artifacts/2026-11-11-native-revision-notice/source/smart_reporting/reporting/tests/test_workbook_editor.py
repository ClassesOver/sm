from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import openpyxl
import pytest

from smart_reporting.report_editor.service import ReportEditorContext, ReportEditorSession
from smart_reporting.reporting.models import ReportingError


def test_manual_workbook_mapping_does_not_reuse_parent_claim_acceptance():
    from zipfile import ZipFile

    from smart_reporting.report_editor.workbook import ReportWorkbookEditorService

    mapping = {'sources': {'cells': [{'cell': 'A1', 'exactValue': '70'}], 'claims': [
        {'support': {'kind': 'recommendation', 'supportStatus': 'supported', 'evidenceRefs': ['old-background'],
            'factRefs': [], 'subjectId': 'original-subject'}}]}}
    content = ReportWorkbookEditorService._mark_sources_unverified(_bytes(), mapping, 'a' * 64)
    with ZipFile(BytesIO(content)) as package:
        revised = json.loads(package.read('smart-reporting/source-mapping.json'))
    support = revised['sources']['claims'][0]['support']
    assert support['supportStatus'] == 'unverified' and not support['evidenceRefs']
    assert support['subjectId'] == 'original-subject'
    assert revised['sources']['cells'][0]['exactValue'] == '70'
    assert revised['sourceWorkbookSha256'] == 'a' * 64
    assert mapping['sources']['claims'][0]['support']['supportStatus'] == 'supported'


def _bytes(value=12):
    book = openpyxl.Workbook()
    book.active.title = '汇总'
    book.active['A1'] = value
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def _context(content):
    return ReportEditorContext(
        reportId='report-xlsx', revision=1, jobId='job', workflowRunId='run',
        markdownPath='reports/report.md',
        job={'jobId': 'job', 'validation': {'ok': True}, 'workbookSources': [{'cell': 'A1', 'datasetId': 'data'}]},
        scope={'database': 'db', 'companyId': 'company', 'userId': 'user', 'sessionId': 'session', 'threadId': 'thread'},
        deliveryFormat='xlsx', xlsxPath='reports/report.xlsx', xlsxSize=len(content),
        xlsxSha256=hashlib.sha256(content).hexdigest(),
    )


def _session(context, capabilities=None):
    return ReportEditorSession(
        report_id=context.report_id, revision=context.revision,
        workflow_run_id=context.workflow_run_id, context_sha256=context.digest(),
        expires_at=datetime.now(UTC), capabilities=capabilities or {'xlsx_editor': True},
    )


def test_workbook_editor_context_requires_complete_format_specific_identity():
    context = _context(_bytes())
    assert context.delivery_format == 'xlsx'
    with pytest.raises(ValueError):
        ReportEditorContext.model_validate({**context.model_dump(by_alias=True), 'xlsxSha256': None})
    with pytest.raises(ValueError):
        ReportEditorContext.model_validate({**context.model_dump(by_alias=True), 'deliveryFormat': 'document'})


@pytest.mark.anyio
async def test_workbook_save_preserves_source_and_publishes_when_context_and_persistence_fail(monkeypatch):
    from smart_reporting.report_editor import workbook

    original, modified = _bytes(), _bytes(99)
    context = _context(original)
    files = {context.xlsx_path: original}

    class Workspace:
        async def afile_bytes(self, _thread, path):
            return files[path], 'application/octet-stream'
        async def awrite_bytes(self, _thread, path, content, **_kwargs):
            assert path not in files
            files[path] = content
        async def ahash_file(self, _thread, path):
            data = files[path]
            return {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    async def get(_run):
        return SimpleNamespace(payload={}, state_version=1)
    async def fail(*_args, **_kwargs):
        raise RuntimeError('fault injection')
    issued = []
    class Grants:
        async def issue(self, *args, **kwargs):
            issued.append((args, kwargs))
            return 'download-token', datetime.now(UTC)

    service = workbook.ReportWorkbookEditorService(
        state_repository=SimpleNamespace(get=get, apply=fail), workspace_registry=None,
        workspace=Workspace(), artifact_persistence=SimpleNamespace(persist_available=fail),
        download_grants=Grants(), public_base_url='https://report.test',
    )
    async def current(_session):
        return context
    service.context_for_session = current
    monkeypatch.setattr(workbook, 'patch_workbook', lambda _bytes, _ops: modified)
    monkeypatch.setattr(workbook, 'inspect_workbook', lambda _bytes: {'sheets': [{'name': '汇总', 'cells': {'A1': {'value': 99}}}]})

    result = await service.save_revision(_session(context), {
        'expectedSha256': context.xlsx_sha256,
        'operations': [{'kind': 'applyCellEdits', 'edits': [{'sheetName': '汇总', 'row': 0, 'column': 0, 'writeValue': True, 'cell': {'value': 99}}]}],
    })

    assert files[context.xlsx_path] == original
    saved = openpyxl.load_workbook(BytesIO(files[result['xlsx']['path']]))
    assert saved['汇总']['A1'].value == 99
    assert saved.worksheets[0]['A1'].value == '本修订待核验'
    assert result['revision'] == 2
    assert result['xlsx']['downloadUrl'].endswith('/xlsx')
    assert result['validation']['ok'] is False
    assert {'workbook_sources_need_verification', 'report_workbook_context_failed', 'report_workbook_persistence_failed'} <= {item['code'] for item in result['validation']['issues']}
    assert issued


@pytest.mark.anyio
async def test_workbook_save_rejects_stale_file_identity_before_writing():
    from smart_reporting.report_editor.workbook import ReportWorkbookEditorService
    context = _context(_bytes())
    service = ReportWorkbookEditorService(state_repository=None, workspace_registry=None, workspace=None)
    async def current(_session):
        return context
    service.context_for_session = current
    with pytest.raises(ReportingError, match='变化'):
        await service.save_revision(_session(context), {'expectedSha256': 'b' * 64, 'operations': []})


@pytest.mark.anyio
async def test_workbook_ai_uses_unsaved_snapshot_and_rejects_stale_acceptance():
    from smart_reporting.report_editor.workbook_ai import (
        ReportWorkbookAIService,
        WorkbookAIProposal,
    )
    context = _context(_bytes())
    prompts = []
    class Workbooks:
        async def context_for_session(self, _session):
            return context
        async def snapshot_for_session(self, _session, operations):
            assert operations[0]['kind'] == 'applyCellEdits'
            return {'snapshotSha256': 'c' * 64, 'workbook': {'sheets': [{'name': '汇总', 'cells': {'A1': {'value': 99}}}]}}
        async def preview_operations(self, _session, operations, proposed):
            assert proposed[0]['kind'] == 'applyCellEdits'
            return {'snapshotSha256': 'd' * 64}
    class Planner:
        async def __call__(self, prompt, **_kwargs):
            prompts.append(prompt)
            return WorkbookAIProposal.model_validate({'summary': '更新值', 'operations': [{'kind': 'applyCellEdits', 'arguments': {'edits': [{'sheetName': '汇总', 'row': 0, 'column': 0, 'writeValue': True, 'cell': {'value': 100}}]}}]})
    service = ReportWorkbookAIService(Workbooks(), planner=Planner())
    session = _session(context)
    start = await service.start_edit(session, '更新值', [{'kind': 'applyCellEdits', 'edits': []}])
    result = await service.wait_edit_status(session, start['editId'], wait_ms=1000)
    assert result['status'] == 'succeeded'
    assert '99' in prompts[0]
    assert result['snapshotSha256'] == 'c' * 64
    with pytest.raises(ReportingError, match='变化'):
        await service.mark_accepted(session, start['editId'], snapshot_sha256='e' * 64)
    accepted = await service.mark_accepted(session, start['editId'], snapshot_sha256='c' * 64)
    assert accepted['accepted'] is True
    # 结构化输出 {kind, arguments} 还原为引擎原生操作。
    assert accepted['proposal']['operations'] == [{'kind': 'applyCellEdits', 'edits': [
        {'sheetName': '汇总', 'row': 0, 'column': 0, 'writeValue': True, 'cell': {'value': 100}}]}]


@pytest.mark.anyio
async def test_workbook_ai_failure_retains_manual_snapshot():
    from smart_reporting.report_editor.workbook_ai import (
        ReportWorkbookAIService,
        WorkbookAIProposal,
    )
    context = _context(_bytes())
    class Workbooks:
        async def context_for_session(self, _session):
            return context
        async def snapshot_for_session(self, _session, _operations):
            return {'snapshotSha256': 'c' * 64, 'workbook': {'sheets': []}}
    class Planner:
        async def __call__(self, *_args, **_kwargs):
            return WorkbookAIProposal.model_validate_json('not-json')
    service = ReportWorkbookAIService(Workbooks(), planner=Planner())
    started = await service.start_edit(_session(context), '修改', [])
    result = await service.wait_edit_status(_session(context), started['editId'], wait_ms=1000)
    assert result['status'] == 'failed'
    assert result['snapshotSha256'] == 'c' * 64
    assert not result['accepted']


def test_workbook_edit_marks_embedded_sources_unverified_without_changing_original_evidence():
    from zipfile import ZipFile

    from smart_reporting.report_editor.workbook import ReportWorkbookEditorService
    source = _bytes()
    mapping = {'sources': {'cells': [{'sheet': '汇总', 'cell': 'A1', 'datasetId': 'original-data'}]}}
    output = ReportWorkbookEditorService._mark_sources_unverified(source, mapping, 'a' * 64)
    with ZipFile(BytesIO(output)) as package:
        revised_mapping = json.loads(package.read('smart-reporting/source-mapping.json'))
    assert revised_mapping['verificationStatus'] == 'needs_verification'
    assert revised_mapping['sources']['cells'][0]['datasetId'] == 'original-data'
    assert revised_mapping['sources']['cells'][0]['verificationStatus'] == 'needs_verification'
    assert 'verificationStatus' not in mapping
    assert openpyxl.load_workbook(BytesIO(output)).active['A1'].value == 12


@pytest.mark.anyio
async def test_noop_workbook_revision_does_not_turn_semantic_failure_into_pass(monkeypatch):
    from smart_reporting.report_editor import workbook

    content = _bytes()
    context = _context(content)
    context.job['validation'] = {'ok': False, 'issues': [{'code': 'ambiguous_metric', 'message': '指标口径待确认'}]}
    files = {context.xlsx_path: content}
    registered = []

    async def get(_run):
        return SimpleNamespace(payload={}, state_version=1)
    async def apply(_run, command, **_kwargs):
        registered.append(command.payload['context'])
    class Workspace:
        async def afile_bytes(self, _thread, path):
            return files[path], 'application/octet-stream'
        async def awrite_bytes(self, _thread, path, revised, **_kwargs):
            files[path] = revised
        async def ahash_file(self, _thread, path):
            return {'size': len(files[path]), 'sha256': hashlib.sha256(files[path]).hexdigest()}

    service = workbook.ReportWorkbookEditorService(
        state_repository=SimpleNamespace(get=get, apply=apply), workspace_registry=None, workspace=Workspace(),
    )
    async def current(_session):
        return context
    service.context_for_session = current
    monkeypatch.setattr(workbook, 'patch_workbook', lambda source, _operations: source)
    monkeypatch.setattr(workbook, 'inspect_workbook', lambda _source: {'sheets': [{'name': '汇总'}]})
    result = await service.save_revision(_session(context), {'expectedSha256': context.xlsx_sha256, 'operations': []})
    assert result['revision'] == 2
    assert result['validation']['ok'] is False
    assert 'workbook_semantic_verification_pending' in {issue['code'] for issue in result['validation']['issues']}
    assert registered[0]['job']['validation']['ok'] is False
