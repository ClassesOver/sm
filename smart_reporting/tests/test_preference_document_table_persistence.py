"""双授权、真实表题生成和SQL回读；不将字段回读冒充完整批准。"""
import base64
import json
import shutil
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from sqlalchemy import select

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.models import ManagementError
from smart_reporting.management.preference_executor import executor_manifest
from smart_reporting.management.repository import preference_verification_results
from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.office_engine import run_office_engine
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
from smart_reporting.tests.test_preference_verification_handoff import ROOT, begin
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_document_table_caption_save_generate_sql_readback_and_source_drift(case, monkeypatch, tmp_path):
    import traceback

    from smart_reporting.management import (
        preference_evidence,
        preference_report_preflight,
        preference_verification,
    )
    from smart_reporting.reporting.delivery.office_engine import engine_dir
    from smart_reporting.tests.test_preference_pptx_table_evidence_persistence import manifest_diff

    # 复用正式引擎目录覆盖机制；依赖实体复制，workspace链接不能逃回共享源码。
    snapshot_output = Path('output/system-config-preferences/document-table-captions/engine-snapshot')
    snapshot_output.mkdir(parents=True, exist_ok=True)
    original_manifest = executor_manifest()
    selections = {}
    for engine in ('slides', 'workbook', 'pdf', 'doc'):
        original = engine_dir(engine)
        target = tmp_path / 'engines' / original.name
        shutil.copytree(original, target, symlinks=False,
            ignore=shutil.ignore_patterns('.git', '__pycache__', '.cache'))
        assert not any(item.is_symlink() for item in target.rglob('*'))
        selections[engine] = target
    source_after = executor_manifest()
    source_changes = manifest_diff(original_manifest, source_after)
    (snapshot_output / 'source-copy-differences.json').write_text(json.dumps(source_changes, ensure_ascii=False, indent=2))
    assert not source_changes, '复制期间来源引擎已变化，未将混合版本当作冻结执行器。'
    for engine, target in selections.items():
        monkeypatch.setenv('AGENT_REPORTING_' + engine.upper() + '_ENGINE_DIR', str(target))
    selected_manifest = executor_manifest()
    for engine in selections:
        assert selected_manifest['officeBridges'][engine]['sourcesAndLocks'] == original_manifest['officeBridges'][engine]['sourcesAndLocks']
        assert selected_manifest['officeBridges'][engine]['entrypoint'] == original_manifest['officeBridges'][engine]['entrypoint']
    (snapshot_output / 'selection.json').write_text(json.dumps({'scope': 'engineering_only_not_shared_workspace_deployment',
        'copiedNodeModulesWithDereferencedWorkspaceLinks': True,
        'sourceManifestHash': configuration_hash(original_manifest),
        'snapshotManifestHash': configuration_hash(selected_manifest),
        'selections': {engine: str(target) for engine, target in selections.items()}}, ensure_ascii=False, indent=2))

    service, client, _, headers, path, admin, editor_token, repository, grants, _, _ = case
    editor = service.bound.editor
    context = await editor.context_for_session(await grants.lookup_session(editor_token))
    root = editor.workspace_registry.get(context.scope['threadId']).root
    text = (root / context.markdown_path).read_bytes().decode() + '\n\n' + sample_markdown()
    value = caption_input(text)
    index = json.loads(value['traceIndexText'])
    index['workflowRunId'] = context.workflow_run_id
    raw_index = json.dumps(index, ensure_ascii=False).encode()
    value['manifest']['traceIndex'].update(size=len(raw_index), sha256=sha256(raw_index).hexdigest())
    (root / context.markdown_path).write_bytes(text.encode())
    (root / 'trace-index.json').write_bytes(raw_index)
    manifest_bytes = json.dumps(value['manifest'], ensure_ascii=False).encode()
    manifest_path = 'artifact-manifest.json'
    (root / manifest_path).write_bytes(manifest_bytes)
    manifest_identity = ArtifactFile(path=manifest_path, mediaType='application/json',
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
    initial = (await service.preferences.detail(admin))['draft']
    document = deepcopy(initial['document'])
    # 维护两格式的相反值、关闭与恢复，均由正式草稿保存/回读。
    versions = []
    for word, pdf in ((False, True), (True, False)):
        document['word']['tables']['captionNumbering'] = word
        document['pdf']['tables']['captionNumbering'] = pdf
        saved = await service.preferences.save_draft(admin, document, initial['version'])
        initial = (await service.preferences.detail(admin))['draft']
        assert saved['version'] == initial['version']
        assert initial['document'] == document
        versions.append(saved['version'])
    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', run_office_engine)
    async with repository.engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    artifacts = SqlAlchemyReportArtifactRepository(repository.engine)
    editor.artifact_persistence = ReportArtifactPersistenceService(artifacts, editor.workspace)
    originals = {name: (root / name).read_bytes() for name in (context.markdown_path, 'trace-index.json', manifest_path, 'chart.png')}
    audit = Path('output/system-config-preferences/document-table-captions/sql-executor-audit')
    audit.mkdir(parents=True, exist_ok=True)
    manifests = []
    def capture_manifest():
        current = executor_manifest()
        manifests.append(current)
        (audit / f'manifest-{len(manifests)}.json').write_text(json.dumps(current, ensure_ascii=False, indent=2))
        (audit / 'differences.json').write_text(json.dumps([manifest_diff(manifests[0], item)
            for item in manifests[1:]], ensure_ascii=False, indent=2))
        return current
    monkeypatch.setattr(preference_verification, 'executor_manifest', capture_manifest)
    monkeypatch.setattr(preference_evidence, 'executor_manifest', capture_manifest)
    record_result = service.evidence.record_result
    async def record(*args, **kwargs):
        try:
            return await record_result(*args, **kwargs)
        except Exception:
            (audit / 'record-error.log').write_text(traceback.format_exc())
            raise
    monkeypatch.setattr(service.evidence, 'record_result', record)
    before_executor = executor_manifest()
    active = list(case)
    active[2] = {'expectedVersion': initial['version'], 'expectedHash': initial['contentHash']}
    active[6] = editor_token
    token = await begin(active)
    response = await client.post(ROOT + '/run', json={**active[2], 'handoffToken': token}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    (audit / 'generation-result.json').write_text(json.dumps({'issues': payload.get('issues'),
        'bindingValid': payload.get('bindingValid'), 'hasReceipt': 'verificationReceipt' in payload}, ensure_ascii=False, indent=2))
    assert payload['bindingValid'] is True and payload['canApply'] is False
    receipt = payload['verificationReceipt']
    async with repository.engine.connect() as connection:
        row = (await connection.execute(select(preference_verification_results).where(
            preference_verification_results.c.id == receipt['id']))).mappings().one()
    stored = row['document']
    assert row['content_hash'] == receipt['contentHash'] == configuration_hash(stored)
    assert stored['retained']['issues'] == []
    binding = stored['binding']
    assert any(item['path'] == 'trace-index.json' for item in binding['identities'])
    assert binding['valid'] is binding['artifactAccessAuthorized'] is True
    output = Path('output/system-config-preferences/document-table-captions/sql')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'executor-before.json').write_text(json.dumps(before_executor, ensure_ascii=False, indent=2))
    native = {}
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    identities = []
    for format in ('word', 'pdf'):
        entry = payload['formats'][format]
        assert entry['artifact'] is not None and entry['pdf'] is not None
        caption = entry['readback']['tableCaptionReadback']
        assert caption['status'] == ('passed' if format == 'word' else 'sampled')
        assert caption['coverage'] == ('complete' if format == 'word' else 'sample')
        capability = next(item for item in entry['capabilities'] if item['path'] == format + '.tables.captionNumbering')
        assert capability['status'] == ('verified' if format == 'word' else 'not_verified')
        for role in ('artifact', 'pdf'):
            reference = stored['retained']['formats'][format][role]
            raw = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
            inline = entry[role]
            assert raw == base64.b64decode(inline['base64'], validate=True)
            assert len(raw) == reference['size'] == inline['size']
            assert sha256(raw).hexdigest() == reference['sha256'] == inline['sha256']
            filename = format + '-' + role + ('.docx' if format == 'word' and role == 'artifact' else '.pdf')
            (output / filename).write_bytes(raw)
            identities.append({'path': filename, 'size': len(raw), 'sha256': sha256(raw).hexdigest()})
            if role == 'artifact':
                native[format] = raw
    word = Document(BytesIO(native['word']))
    assert [p.text for p in word.paragraphs if p._p.xpath('.//w:bookmarkStart[starts-with(@w:name,"tblcap_")]')] == [
        '表 1：收支明细 1234.5600', '表 2：收支明细 1234.5600']
    prepared = await service.evidence.prepare(admin, expected_version=initial['version'],
        expected_hash=initial['contentHash'], evidence_ids=[receipt['id']])
    assert prepared['status'] == 'incomplete' and prepared['canApply'] is False
    assert not any(item.get('fieldPath') == 'pdf.tables.captionNumbering' and item.get('coverage') == 'complete'
        for item in stored['evidence'])
    try:
        (root / 'trace-index.json').write_bytes(raw_index + b' ')
        with pytest.raises(ManagementError) as changed:
            await service.evidence.prepare(admin, expected_version=initial['version'],
                expected_hash=initial['contentHash'], evidence_ids=[receipt['id']])
        assert changed.value.status == 409
        for format in ('word', 'pdf'):
            key = stored['retained']['formats'][format]['artifact']['artifactKey']
            assert b''.join([chunk async for chunk in independent.stream(key)]) == native[format]
    finally:
        (root / 'trace-index.json').write_bytes(raw_index)
    assert all((root / name).read_bytes() == raw for name, raw in originals.items())
    after_executor = capture_manifest()
    (audit / 'before-final-differences.json').write_text(json.dumps(
        manifest_diff(before_executor, after_executor), ensure_ascii=False, indent=2))
    assert before_executor == after_executor
    (output / 'executor-after.json').write_text(json.dumps(after_executor, ensure_ascii=False, indent=2))
    (output / 'readback.json').write_text(json.dumps({'scope': 'fixture_workflow_real_auth_render_sql_frozen_engine_snapshot_not_shared_workspace_deployment',
        'draftVersions': versions, 'bindingHash': binding['bindingHash'], 'formats': {
            format: {'tableCaptionReadback': payload['formats'][format]['readback']['tableCaptionReadback'],
                'capability': next(item for item in payload['formats'][format]['capabilities']
                    if item['path'] == format + '.tables.captionNumbering')} for format in ('word', 'pdf')},
        'artifacts': identities, 'executorStable': True, 'sourceDriftRejected': changed.value.code,
        'retainedAfterDrift': True, 'originalsUnchanged': True, 'canApply': prepared['canApply'],
        'missingRequirementCount': len(prepared['missingRequirements'])}, ensure_ascii=False, indent=2))
