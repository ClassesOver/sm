"""真实Word表题逐对象证据经HTTP、SQL留存及汇总，不替代完整批准。"""

import base64
import json
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
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    SqlAlchemyReportArtifactRepository,
    report_artifact_chunks_v1,
    report_artifact_files_v1,
)
from smart_reporting.reporting.tests.test_document_table_caption_numbering import (
    caption_input,
    sample_markdown,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_evidence_persistence import run
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
OUTPUT = Path('output/system-config-preferences/word-table-caption-evidence')
CAPTION_PATH = 'word.tables.captionNumbering'


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('scenario', ['numbered', 'unnumbered', 'hidden_character', 'retained_drift'])
async def test_real_word_captions_produce_only_retained_native_field_evidence(case, monkeypatch, scenario):
    from docx.enum.style import WD_STYLE_TYPE

    from smart_reporting.management import preference_preflight, preference_report_preflight

    service, client, _, _, path, admin, editor_token, repository, grants, _, _ = case
    editor = service.bound.editor
    context = await editor.context_for_session(await grants.lookup_session(editor_token))
    root = editor.workspace_registry.get(context.scope['threadId']).root
    text = (root / context.markdown_path).read_text() + '\n\n' + sample_markdown()
    value = caption_input(text)
    index = json.loads(value['traceIndexText'])
    index['workflowRunId'] = context.workflow_run_id
    raw_index = json.dumps(index, ensure_ascii=False).encode()
    value['manifest']['traceIndex'].update(size=len(raw_index), sha256=sha256(raw_index).hexdigest())
    (root / context.markdown_path).write_bytes(text.encode())
    (root / 'trace-index.json').write_bytes(raw_index)
    manifest_bytes = json.dumps(value['manifest'], ensure_ascii=False).encode()
    (root / 'artifact-manifest.json').write_bytes(manifest_bytes)
    manifest_identity = ArtifactFile(path='artifact-manifest.json', mediaType='application/json',
        size=len(manifest_bytes), sha256=sha256(manifest_bytes).hexdigest())
    job = deepcopy(context.job)
    md = {key: value['manifest']['markdown'][key] for key in ('path', 'size', 'sha256')}
    job['sources'] = [md if item['path'] == context.markdown_path else item for item in job['sources']]
    job['render']['markdown'] = md
    context = context.model_copy(update={'job': job, 'artifact_manifest': manifest_identity})
    editor.state_repository.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    grant, _ = await grants.issue(context)
    editor_token, _ = await grants.exchange(grant)
    client.cookies.set(EDITOR_SESSION_COOKIE, editor_token, path=path)
    draft = (await service.preferences.detail(admin))['draft']
    document = deepcopy(draft['document'])
    numbered = scenario != 'unnumbered'
    document['word']['tables']['captionNumbering'] = numbered
    document['word']['cover'] = False
    document['word']['toc'] = False
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

    original_generate = preference_preflight._generate

    def generate(directory, preferences, frozen):
        issues = original_generate(directory, preferences, frozen)
        if scenario == 'hidden_character':
            # 只篡改实际末表题的原生字符样式；绑定、reader、mapper、留存均为生产实现。
            native_path = directory / 'inputs/revision/report.docx'
            native = Document(native_path)
            caption = [p for p in native.paragraphs
                if p._p.xpath('./w:bookmarkStart[starts-with(@w:name,"tblcap_")]')][-1]
            style = native.styles.add_style('Hidden caption fault', WD_STYLE_TYPE.CHARACTER)
            style.font.hidden = True
            for run in caption.runs:
                run.style = style
            native.save(native_path)
        return issues

    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', actual_word)
    monkeypatch.setattr(preference_preflight, '_generate', generate)
    before = executor_manifest()
    assert before['runtimeIdentityComplete'] is True
    payload = await run(active)
    assert payload['bindingValid'] is True and payload['canApply'] is False
    receipt = payload['verificationReceipt']
    async with repository.engine.connect() as connection:
        stored = (await connection.execute(select(preference_verification_results).where(
            preference_verification_results.c.id == receipt['id']))).mappings().one()
    record = stored['document']
    assert stored['content_hash'] == receipt['contentHash'] == configuration_hash(record)
    assert record['retained']['issues'] == []
    rows = [item for item in record['evidence'] if item['path'] == CAPTION_PATH]
    assert len(rows) == 1
    assert rows[0]['status'] == ('failed' if scenario == 'hidden_character' else 'passed')
    assert rows[0]['dimension'] == 'native' and rows[0]['scenario'] == 'configured_field'
    assert not any(item['format'] == 'pdf' and item['path'].endswith('tables.captionNumbering')
        for item in record['evidence'])
    entry = payload['formats']['word']
    reference = record['retained']['formats']['word']['artifact']
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
    assert content == base64.b64decode(entry['artifact']['base64'], validate=True)
    assert len(content) == reference['size'] and sha256(content).hexdigest() == reference['sha256']
    assert rows[0]['artifact'] == {'sizeBytes': len(content), 'sha256': reference['sha256']}
    native = Document(BytesIO(content))
    captions = [p.text for p in native.paragraphs if p._p.xpath('./w:bookmarkStart[starts-with(@w:name,"tblcap_")]')]
    assert captions == (['表 1：收支明细 1234.5600', '表 2：收支明细 1234.5600'] if numbered
        else ['收支明细 1234.5600', '收支明细 1234.5600'])
    assert any(cell.text == '1234.5600' for table in native.tables for row in table.rows for cell in row.cells)
    prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
        expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
    assert prepared['status'] == 'incomplete' and prepared['canApply'] is False
    gaps = [gap for gap in prepared['missingRequirements'] if gap.get('path') == CAPTION_PATH
        and gap.get('scenario') == 'configured_field']
    assert bool(gaps) is (scenario == 'hidden_character')
    if gaps:
        assert gaps[0]['reason'] == 'check_failed'
    # 原材料改变使旧留证失效，原生文件仍保留。
    (root / 'trace-index.json').write_bytes(raw_index + b' ')
    try:
        with pytest.raises(ManagementError) as changed:
            await service.evidence.prepare(admin, expected_version=draft['version'],
                expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
        assert changed.value.status == 409
        assert b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])]) == content
    finally:
        (root / 'trace-index.json').write_bytes(raw_index)
    if scenario == 'retained_drift':
        async with repository.engine.begin() as connection:
            await connection.execute(update(report_artifact_chunks_v1).where(
                report_artifact_chunks_v1.c.artifact_key == reference['artifactKey'],
                report_artifact_chunks_v1.c.chunk_index == 0).values(content=b'changed-caption-retention'))
        with pytest.raises(ManagementError, match='management_preference_retained_artifact_changed'):
            await service.evidence.prepare(admin, expected_version=draft['version'],
                expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
    after = executor_manifest()
    assert before == after == record['executorManifest']
    directory = OUTPUT / scenario
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'actual.docx').write_bytes(content)
    if entry.get('pdf'):
        (directory / 'preview.pdf').write_bytes(base64.b64decode(entry['pdf']['base64'], validate=True))
    (directory / 'readback.json').write_text(json.dumps({'scope': 'fixture_workflow_real_http_word_sql_readback',
        'artifact': rows[0]['artifact'], 'executorManifestHash': configuration_hash(before),
        'executorStable': True, 'readback': entry['readback']['tableCaptionReadback'], 'evidence': rows,
        'prepared': prepared, 'sourceDriftRejected': changed.value.code,
        'retainedDriftRejected': scenario == 'retained_drift'}, ensure_ascii=False, indent=2))
