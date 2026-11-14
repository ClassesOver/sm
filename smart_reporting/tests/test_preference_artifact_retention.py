"""现有工作区与原生产物仓库的独立留存，不代表 Office 版式验收。"""

import base64
import hashlib
import shutil
from copy import deepcopy
from dataclasses import replace

import pytest

from smart_reporting.reporting.delivery.publishing import ReportArtifactPersistenceService
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.delivery_fakes import InMemoryReportArtifactRepository
from smart_reporting.tests.test_preference_report_preflight import bound_case

pytestmark = pytest.mark.anyio
VERIFICATION_ID = '7b5ce76b-1e39-4f7e-b164-f3f6b2436793'


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def payload(content):
    return {'base64': base64.b64encode(content).decode(), 'size': len(content),
        'sha256': hashlib.sha256(content).hexdigest(), 'filename': '../../ignored'}


async def retention_case(tmp_path):
    from smart_reporting.management.preference_artifact_retention import PreferenceArtifactRetention
    from smart_reporting.report_editor.service import token_hash

    bound, args, _, _, _, _, _ = await bound_case(tmp_path)
    repository = InMemoryReportArtifactRepository()
    bound.editor.artifact_persistence = ReportArtifactPersistenceService(repository, bound.editor.workspace)
    return PreferenceArtifactRetention(bound=bound), repository, token_hash(args['editor_session']), bound


async def test_retains_native_and_pdf_independently_and_never_mutates_inline_artifacts(tmp_path):
    retention, repository, session_hash, bound = await retention_case(tmp_path)
    result = {'formats': {'word': {'artifact': payload(b'word-native'), 'pdf': payload(b'pdf-preview')},
        'pdf': {'artifact': payload(b'pdf-native')}}}
    original = deepcopy(result)
    retained = await retention.retain(result, verification_id=VERIFICATION_ID, editor_session_hash=session_hash)
    assert retained['issues'] == [] and result == original
    references = [retained['formats']['word']['artifact'], retained['formats']['word']['pdf'],
        retained['formats']['pdf']['artifact']]
    assert len({item['reportId'] for item in references}) == 3
    assert len({item['artifactKey'] for item in references}) == 3
    for reference, expected in zip(references, (b'word-native', b'pdf-preview', b'pdf-native'), strict=True):
        stored = await repository.get(reference['artifactKey'])
        assert stored.report_id.startswith('preference-verification:' + VERIFICATION_ID)
        assert stored.path.startswith('reports/preference-verifications/' + VERIFICATION_ID + '/')
        assert b''.join([chunk async for chunk in repository.stream(stored.artifact_key)]) == expected
        assert reference['size'] == len(expected) and reference['sha256'] == hashlib.sha256(expected).hexdigest()
    assert 'base64' not in str(retained) and session_hash not in str(retained)
    assert '../../ignored' not in str(retained)


@pytest.mark.parametrize('fault', ['base64', 'size', 'bool_size', 'sha256'])
async def test_rejects_tampered_inline_identity_but_retains_other_format(tmp_path, fault):
    retention, repository, session_hash, _ = await retention_case(tmp_path)
    bad = payload(b'bad')
    bad[{'base64': 'base64', 'size': 'size', 'bool_size': 'size', 'sha256': 'sha256'}[fault]] = {
        'base64': '%%%not-base64', 'size': 4, 'bool_size': True, 'sha256': '0' * 64}[fault]
    result = {'formats': {'word': {'artifact': bad}, 'md': {'artifact': payload(b'good')}}}
    original = deepcopy(result)
    retained = await retention.retain(result, verification_id=VERIFICATION_ID, editor_session_hash=session_hash)
    assert set(retained['formats']) == {'md'} and len(repository.records) == 1
    assert retained['issues'][0]['format'] == 'word' and retained['issues'][0]['role'] == 'artifact'
    assert result == original


@pytest.mark.parametrize('fault', ['metadata', 'bytes', 'read_failure'])
async def test_requires_independent_repository_readback(tmp_path, monkeypatch, fault):
    retention, repository, session_hash, _ = await retention_case(tmp_path)
    original_put = repository.put

    async def corrupted(artifact, chunks):
        await original_put(artifact, chunks)
        if fault == 'metadata':
            repository.records[artifact.artifact_key] = replace(artifact, report_id='published-report')
        elif fault == 'bytes':
            repository.chunks[artifact.artifact_key] = (b'corrupted',)

    monkeypatch.setattr(repository, 'put', corrupted)
    if fault == 'read_failure':
        async def unavailable(_):
            raise OSError('independent read unavailable')
            yield b''
        monkeypatch.setattr(repository, 'stream', unavailable)
    result = {'formats': {'md': {'artifact': payload(b'good')}}}
    original = deepcopy(result)
    retained = await retention.retain(result, verification_id=VERIFICATION_ID, editor_session_hash=session_hash)
    assert retained['formats'] == {} and len(retained['issues']) == 1
    assert result == original


async def test_missing_persistence_returns_issue_without_dropping_inline_artifact(tmp_path):
    retention, _, session_hash, bound = await retention_case(tmp_path)
    bound.editor.artifact_persistence = None
    result = {'formats': {'md': {'artifact': payload(b'good')}}}
    original = deepcopy(result)
    retained = await retention.retain(result, verification_id=VERIFICATION_ID, editor_session_hash=session_hash)
    assert retained['formats'] == {} and retained['issues']
    assert result == original


async def test_revoked_editor_is_not_converted_to_storage_issue(tmp_path):
    retention, repository, session_hash, bound = await retention_case(tmp_path)
    bound.grants.repository.sessions.clear()
    with pytest.raises(ReportingError, match='report_editor_session_invalid'):
        await retention.retain({'formats': {'md': {'artifact': payload(b'good')}}},
            verification_id=VERIFICATION_ID, editor_session_hash=session_hash)
    assert not repository.records


async def test_storage_failure_keeps_other_reference_and_existing_publication(tmp_path, monkeypatch):
    from smart_reporting.report_editor.service import token_hash
    from smart_reporting.reporting.delivery.publishing import (
        ReportArtifactSpec,
        ReportDownloadScope,
    )

    retention, repository, session_hash, bound = await retention_case(tmp_path)
    session = await bound.grants.lookup_registered_session(session_hash)
    context = await bound.editor.context_for_session(session)
    scope = ReportDownloadScope(database=context.scope['database'], company_id=context.scope['companyId'],
        user_id=context.scope['userId'], session_id=context.scope['sessionId'],
        thread_id=context.scope['threadId'], workflow_run_id=context.workflow_run_id)
    await bound.editor.workspace.awrite_bytes(scope.thread_id, 'reports/published.pdf', b'published')
    await bound.editor.artifact_persistence.persist(scope=scope, report_id=context.report_id,
        revision=context.revision, artifacts=(ReportArtifactSpec(artifact='pdf', path='reports/published.pdf',
            size=9, sha256=hashlib.sha256(b'published').hexdigest()),))
    previous_records, previous_chunks = dict(repository.records), dict(repository.chunks)
    original_put = repository.put

    async def unavailable_word(artifact, chunks):
        if artifact.artifact == 'word':
            raise OSError('word storage unavailable')
        await original_put(artifact, chunks)

    monkeypatch.setattr(repository, 'put', unavailable_word)
    retained = await retention.retain({'formats': {'word': {'artifact': payload(b'word'),
        'pdf': payload(b'preview')}}}, verification_id=VERIFICATION_ID, editor_session_hash=session_hash)
    assert set(retained['formats']['word']) == {'pdf'}
    assert retained['issues'][0]['stage'] == 'persist'
    for key, record in previous_records.items():
        assert repository.records[key] == record and repository.chunks[key] == previous_chunks[key]
    grant, _ = await bound.grants.issue(context, capabilities={})
    restricted, _ = await bound.grants.exchange(grant)
    with pytest.raises(ReportingError, match='dataset_access_denied'):
        await retention.retain({'formats': {'md': {'artifact': payload(b'good')}}},
            verification_id=VERIFICATION_ID, editor_session_hash=token_hash(restricted))


async def recheck_case(tmp_path):
    retention, repository, session_hash, bound = await retention_case(tmp_path)
    retained = await retention.retain({'formats': {'word': {'artifact': payload(b'word'),
        'pdf': payload(b'preview')}}}, verification_id=VERIFICATION_ID, editor_session_hash=session_hash)
    session = await bound.grants.lookup_registered_session(session_hash)
    return retention, repository, session_hash, bound, retained, session.context_sha256


async def test_recheck_reads_complete_native_and_preview_bytes_without_mutating_references(tmp_path):
    retention, repository, session_hash, _, retained, context_sha256 = await recheck_case(tmp_path)
    original = deepcopy(retained)
    verified = await retention.recheck(retained, verification_id=VERIFICATION_ID,
        editor_session_hash=session_hash, expected_context_sha256=context_sha256)
    assert verified == original and retained == original
    assert 'base64' not in str(verified) and session_hash not in str(verified)
    assert len(repository.records) == 2


async def test_recheck_restores_existing_workspace_after_process_registry_is_cleared(tmp_path):
    retention, _, session_hash, bound, retained, context_sha256 = await recheck_case(tmp_path)
    await bound.editor.workspace_registry.aclose()
    verified = await retention.recheck(retained, verification_id=VERIFICATION_ID,
        editor_session_hash=session_hash, expected_context_sha256=context_sha256)
    assert verified == retained and verified['issues'] == []


@pytest.mark.parametrize('fault', ['metadata', 'bytes', 'missing', 'stream_error', 'cross_reference', 'bool_size'])
async def test_recheck_rejects_changed_reference_but_keeps_other_artifact(tmp_path, monkeypatch, fault):
    retention, repository, session_hash, _, retained, context_sha256 = await recheck_case(tmp_path)
    reference = retained['formats']['word']['artifact']
    key = reference['artifactKey']
    if fault == 'metadata':
        repository.records[key] = replace(repository.records[key], report_id='other-report')
    elif fault == 'bytes':
        repository.chunks[key] = (b'wor', b'x')  # 同长且首块相同，必须读完后核摘要。
    elif fault == 'missing':
        del repository.records[key]
    elif fault == 'cross_reference':
        reference.update(retained['formats']['word']['pdf'])
    elif fault == 'bool_size':
        reference['size'] = True
    else:
        original_stream = repository.stream
        async def unavailable(artifact_key):
            if artifact_key == key:
                raise OSError('unavailable')
            async for chunk in original_stream(artifact_key):
                yield chunk
        monkeypatch.setattr(repository, 'stream', unavailable)
    original = deepcopy(retained)
    verified = await retention.recheck(retained, verification_id=VERIFICATION_ID,
        editor_session_hash=session_hash, expected_context_sha256=context_sha256)
    assert set(verified['formats']['word']) == {'pdf'}
    assert verified['issues'][0]['code'] == 'management_preference_artifact_recheck_failed'
    assert verified['issues'][0]['format'] == 'word' and verified['issues'][0]['role'] == 'artifact'
    assert retained == original


@pytest.mark.parametrize('fault', ['revoked', 'context', 'workspace'])
async def test_recheck_authority_failure_is_not_soft_storage_issue(tmp_path, fault):
    retention, _, session_hash, bound, retained, context_sha256 = await recheck_case(tmp_path)
    if fault == 'revoked':
        bound.grants.repository.sessions.clear()
    elif fault == 'context':
        context_sha256 = '0' * 64
    else:
        identity = next(iter(bound.editor.workspace_registry._entries.values()))
        shutil.rmtree(identity.root)
        await bound.editor.workspace_registry.aclose()
    with pytest.raises(ReportingError):
        await retention.recheck(retained, verification_id=VERIFICATION_ID,
            editor_session_hash=session_hash, expected_context_sha256=context_sha256)


async def test_recheck_preserves_previous_retention_failure_without_creating_evidence(tmp_path):
    retention, _, session_hash, _, retained, context_sha256 = await recheck_case(tmp_path)
    retained['issues'].append({'code': 'previous_failure', 'message': '原文件留存失败'})
    retained['formats']['unsupported'] = {'artifact': {'artifactKey': 'foreign'}}
    verified = await retention.recheck(retained, verification_id=VERIFICATION_ID,
        editor_session_hash=session_hash, expected_context_sha256=context_sha256)
    assert verified['issues'][0]['code'] == 'previous_failure'
    assert verified['issues'][1]['code'] == 'management_preference_artifact_recheck_failed'
    assert set(verified['formats']) == {'word'}


async def test_recheck_never_echoes_unrecognized_reference_fields(tmp_path):
    retention, _, session_hash, _, retained, context_sha256 = await recheck_case(tmp_path)
    retained['formats']['word']['artifact']['base64'] = 'private-inline-bytes'
    retained['formats']['word']['artifact']['session'] = 'private-session'
    checked = await retention.recheck(retained, verification_id=VERIFICATION_ID,
        editor_session_hash=session_hash, expected_context_sha256=context_sha256)
    assert checked['issues'] == []
    assert 'base64' not in str(checked) and 'private-session' not in str(checked)
    assert retained['formats']['word']['artifact']['base64'] == 'private-inline-bytes'
