"""全部 Word 表格字段经过真实 HTTP、SQL 留存和独立 prepare 的验证。"""

import base64
import json
import traceback
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from sqlalchemy import select, update

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.models import ManagementError
from smart_reporting.management.preference_executor import executor_manifest
from smart_reporting.management.repository import preference_verification_results
from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    SqlAlchemyReportArtifactRepository,
    report_artifact_chunks_v1,
    report_artifact_files_v1,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_evidence_persistence import run
from smart_reporting.tests.test_preference_verification_handoff import case as case
from smart_reporting.tests.test_preference_word_table_readback import FIELDS

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
OUTPUT = Path('output/system-config-preferences/word-table-native-evidence')
PATHS = {'word.' + path for path in FIELDS}


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('scenario', ['configured', 'opposite', 'late_cell', 'retained_drift'])
async def test_real_word_table_fields_retain_precise_native_evidence_and_identity(case, monkeypatch, scenario):
    from docx.shared import Pt

    from smart_reporting.management import preference_preflight, preference_report_preflight

    service, client, _, _, path, admin, editor_token, repository, grants, _, _ = case
    editor = service.bound.editor
    context = await editor.context_for_session(await grants.lookup_session(editor_token))
    root = editor.workspace_registry.get(context.scope['threadId']).root
    text = (root / context.markdown_path).read_text() + '\n\n| 业务（单位） | 数值 |\n| --- | ---: |\n' + ''.join(
        f'| 尾表第{index}行 | {index}.5600 |\n' for index in range(1, 31)) + '| 空值 | |\n'
    raw = text.encode()
    (root / context.markdown_path).write_bytes(raw)
    identity = {'path': context.markdown_path, 'size': len(raw), 'sha256': sha256(raw).hexdigest()}
    job = deepcopy(context.job)
    job['sources'] = [identity if item['path'] == context.markdown_path else item for item in job['sources']]
    job['render']['markdown'] = identity
    context = context.model_copy(update={'job': job})
    editor.state_repository.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    grant, _ = await grants.issue(context)
    editor_token, _ = await grants.exchange(grant)
    client.cookies.set(EDITOR_SESSION_COOKIE, editor_token, path=path)
    draft = (await service.preferences.detail(admin))['draft']
    document = deepcopy(draft['document'])
    alternate = scenario == 'opposite'
    document['word'].update(cover=False, toc=False)
    document['word']['tables'].update(repeatHeader=alternate, splitRows=not alternate,
        borders='none' if alternate else 'light', striped=not alternate)
    document['word']['typography']['table'].update(font='sans' if alternate else 'serif', size=12,
        color='#123456', bold=not alternate, lineHeight=1.25, spaceBefore=2, spaceAfter=3, indent=6)
    await service.preferences.save_draft(admin, document, draft['version'])
    draft = (await service.preferences.detail(admin))['draft']
    active = list(case)
    active[2] = {'expectedVersion': draft['version'], 'expectedHash': draft['contentHash']}
    active[6] = editor_token
    async with repository.engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    editor.artifact_persistence = ReportArtifactPersistenceService(
        SqlAlchemyReportArtifactRepository(repository.engine), editor.workspace)

    async def actual_word(function, *args, **kwargs):
        return function(*args, **{**kwargs, 'formats': ('word',)})

    original = preference_preflight._generate

    def generate(directory, preferences, frozen):
        issues = original(directory, preferences, frozen)
        if scenario == 'late_cell':
            target = directory / 'inputs/revision/report.docx'
            native = Document(target)
            # 最后一格为空，但仍应保存字体并纳入独立证据。
            native.tables[-1].cell(31, 1).paragraphs[0].runs[-1].font.size = Pt(9)
            native.save(target)
        return issues

    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', actual_word)
    monkeypatch.setattr(preference_preflight, '_generate', generate)
    original_record = service.evidence.record_result

    async def record_result(*args, **kwargs):
        try:
            return await original_record(*args, **kwargs)
        except Exception:
            directory = OUTPUT / scenario
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'record-error.txt').write_text(traceback.format_exc())
            raise

    monkeypatch.setattr(service.evidence, 'record_result', record_result)
    before = executor_manifest()
    assert before['runtimeIdentityComplete'] is True
    payload = await run(active)
    assert payload['bindingValid'] is True and payload['canApply'] is False
    assert 'verificationReceipt' in payload, payload.get('issues')
    receipt = payload['verificationReceipt']
    async with repository.engine.connect() as connection:
        stored = (await connection.execute(select(preference_verification_results).where(
            preference_verification_results.c.id == receipt['id']))).mappings().one()
    record = stored['document']
    assert stored['content_hash'] == receipt['contentHash'] == configuration_hash(record)
    assert record['retained']['issues'] == []
    rows = [item for item in record['evidence'] if item['path'] in PATHS]
    entry = payload['formats']['word']
    # 失败也保留原件和详细回读，便于诊断；不将预览视为SQL流读证明。
    directory = OUTPUT / scenario
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'generation-readback.json').write_text(json.dumps({
        'readback': entry.get('readback'), 'issues': entry.get('issues'), 'evidence': rows,
        'executorManifestHash': configuration_hash(before), 'recordedManifestHash': record['executorManifestHash']},
        ensure_ascii=False, indent=2))
    assert len(rows) == 12, entry.get('readback')
    assert all(row['scenario'] == 'configured_field' and row['dimension'] == 'native' for row in rows)
    assert {row['path'] for row in rows if row['status'] == 'failed'} == (
        {'word.typography.table.size'} if scenario == 'late_cell' else set())
    reference = record['retained']['formats']['word']['artifact']
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
    assert content == base64.b64decode(entry['artifact']['base64'], validate=True)
    assert len(content) == reference['size'] and sha256(content).hexdigest() == reference['sha256']
    assert all(row['artifact'] == {'sizeBytes': len(content), 'sha256': reference['sha256']} for row in rows)
    native = Document(BytesIO(content))
    assert len(native.tables) == 2 and len(native.tables[-1].rows) == 32
    assert native.tables[-1].cell(30, 1).text == '30.5600' and native.tables[-1].cell(31, 1).text == ''
    (directory / 'actual.docx').write_bytes(content)
    if entry.get('pdf'):
        (directory / 'preview.pdf').write_bytes(base64.b64decode(entry['pdf']['base64'], validate=True))
    prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
        expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
    assert prepared['status'] == 'incomplete' and prepared['canApply'] is False
    gaps = [gap for gap in prepared['missingRequirements'] if gap.get('path') in PATHS
        and gap.get('scenario') == 'configured_field']
    assert {gap['path'] for gap in gaps} == ({'word.typography.table.size'} if scenario == 'late_cell' else set())
    if gaps:
        assert gaps[0]['reason'] == 'check_failed'
    if scenario == 'retained_drift':
        async with repository.engine.begin() as connection:
            await connection.execute(update(report_artifact_chunks_v1).where(
                report_artifact_chunks_v1.c.artifact_key == reference['artifactKey'],
                report_artifact_chunks_v1.c.chunk_index == 0).values(content=b'changed-native-table-retention'))
        with pytest.raises(ManagementError, match='management_preference_retained_artifact_changed'):
            await service.evidence.prepare(admin, expected_version=draft['version'],
                expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
    after = executor_manifest()
    assert before == after == record['executorManifest']
    (directory / 'readback.json').write_text(json.dumps({'scope': 'fixture_workflow_real_http_word_sql_readback',
        'artifact': {'sizeBytes': len(content), 'sha256': reference['sha256']}, 'executorStable': True,
        'executorManifestHash': configuration_hash(before), 'tableReadback': entry['readback']['tableReadback'],
        'evidence': rows, 'prepared': prepared, 'retainedDriftRejected': scenario == 'retained_drift'},
        ensure_ascii=False, indent=2))
