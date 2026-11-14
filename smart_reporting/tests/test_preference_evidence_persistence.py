"""实际报告留证持久化；故障不丢已授权文件，撤权不交付来源。"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import delete, select, update

from smart_reporting.management.models import ManagementError
from smart_reporting.report_editor.repository import report_editor_sessions_v1
from smart_reporting.report_editor.service import token_hash
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_verification_handoff import ROOT, begin
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def run(case):
    token = await begin(case)
    response = await case[1].post(ROOT + '/run', json={**case[2], 'handoffToken': token}, headers=case[3])
    assert response.status_code == 200, response.text
    return response.json()


async def test_actual_report_run_persists_private_immutable_receipt_without_bytes_or_sessions(case):
    payload = await run(case)
    receipt = payload['verificationReceipt']
    from smart_reporting.management.repository import preference_verification_results

    async with case[7].engine.connect() as connection:
        row = (await connection.execute(select(preference_verification_results))).mappings().one()
    assert receipt['id'] == row['id'] and receipt['contentHash'] == row['content_hash']
    document = row['document']
    assert document['draft'] == {'version': 1, 'contentHash': case[2]['expectedHash']}
    assert document['authBinding']['adminSessionHash'] == token_hash(case[5])
    assert document['authBinding']['editorSessionHash'] == token_hash(case[6])
    serialized = json.dumps(document)
    assert all(secret not in serialized for secret in (case[5], case[6], 'dGVzdA=='))
    assert payload['formats']['md']['artifact']['base64'] == 'dGVzdA=='
    assert document['result']['formats']['md']['artifact']['size'] == 4
    assert document['assessment']['canApply'] is False
    assert document['assessment']['missingRequirements']
    assert receipt['contractHash'] == document['contractHash']
    assert len(receipt['executorManifestHash']) == 64
    # 和既有配置版本同样由数据库拒绝已写证据被覆盖，而非只靠应用约定。
    with pytest.raises(Exception):
        async with case[7].engine.begin() as connection:
            await connection.execute(update(preference_verification_results).values(content_hash='f' * 64))
    async with case[7].engine.connect() as connection:
        assert await connection.scalar(select(preference_verification_results.c.content_hash)) == receipt['contentHash']


@pytest.mark.parametrize('fault', ['insert', 'independent_readback'])
async def test_evidence_storage_fault_keeps_authorized_artifact_with_specific_failure(case, monkeypatch, fault):
    store = case[0].evidence

    async def fail(*args, **kwargs):
        raise RuntimeError('fixture-storage-failure')

    monkeypatch.setattr(store, '_insert' if fault == 'insert' else '_load', fail)
    payload = await run(case)
    assert payload['formats']['md']['artifact']['base64'] == 'dGVzdA=='
    assert payload['canApply'] is False and payload['status'] == 'failed'
    assert any(issue['code'] == 'management_preference_evidence_persistence_failed' for issue in payload['issues'])
    assert 'verificationReceipt' not in payload


async def test_revocation_during_failed_storage_still_suppresses_artifact(case, monkeypatch):
    async def fail(*args, **kwargs):
        async with case[7].engine.begin() as connection:
            await connection.execute(delete(report_editor_sessions_v1).where(
                report_editor_sessions_v1.c.session_hash == token_hash(case[6])))
        raise RuntimeError('fixture-storage-failure-after-revoke')

    monkeypatch.setattr(case[0].evidence, 'record_result', fail)
    token = await begin(case)
    response = await case[1].post(ROOT + '/run', json={**case[2], 'handoffToken': token}, headers=case[3])
    assert response.status_code == 403 and 'dGVzdA==' not in response.text


async def test_persisted_receipt_reads_require_original_live_dual_authority(case):
    payload = await run(case)
    receipt = payload['verificationReceipt']
    stored = await case[0].evidence.read(case[5], receipt['id'])
    assert stored['id'] == receipt['id'] and stored['assessment']['canApply'] is False
    assert 'authBinding' not in stored and 'binding' not in stored
    async with case[7].engine.begin() as connection:
        await connection.execute(delete(report_editor_sessions_v1).where(
            report_editor_sessions_v1.c.session_hash == token_hash(case[6])))
    with pytest.raises(ManagementError):
        await case[0].evidence.read(case[5], receipt['id'])


async def test_saved_verification_results_can_be_listed_for_the_current_draft_and_session(case):
    payload = await run(case)
    response = await case[1].get(ROOT + '/results', params={
        'expectedVersion': case[2]['expectedVersion'], 'expectedHash': case[2]['expectedHash']})

    assert response.status_code == 200, response.text
    records = response.json()
    assert len(records) == 1
    record = records[0]
    assert record['id'] == payload['verificationReceipt']['id']
    assert record['contentHash'] == payload['verificationReceipt']['contentHash']
    assert record['draft'] == {'version': 1, 'contentHash': case[2]['expectedHash']}
    assert record['report'] == {'reportId': 'report-1', 'revision': 1}
    assert record['assessment']['canApply'] is False
    assert record['assessment']['missingRequirementCount'] > 0
    assert all(secret not in response.text for secret in (case[5], case[6], 'authBinding', 'artifactKey', 'dGVzdA=='))


async def test_saved_verification_result_listing_rejects_stale_draft(case):
    await run(case)
    response = await case[1].get(ROOT + '/results', params={
        'expectedVersion': 2, 'expectedHash': case[2]['expectedHash']})
    assert response.status_code == 409
    assert response.json()['code'] == 'management_version_conflict'


@pytest.mark.parametrize('fault', ['editor_revoke', 'other_admin', 'expired'])
async def test_saved_verification_result_listing_excludes_records_without_original_authority(case, fault):
    from smart_reporting.management.api import SESSION_COOKIE
    from smart_reporting.tests.test_management_persistence import OLD_PASSWORD

    await run(case)
    if fault == 'editor_revoke':
        async with case[7].engine.begin() as connection:
            await connection.execute(delete(report_editor_sessions_v1).where(
                report_editor_sessions_v1.c.session_hash == token_hash(case[6])))
    elif fault == 'other_admin':
        other = (await case[0].auth.login('admin', OLD_PASSWORD, '127.0.0.2')).raw_token
        case[1].cookies.set(SESSION_COOKIE, other, path='/management')
    else:
        case[9][0] += timedelta(minutes=15)
        await case[0].auth.authenticate(case[5])
        case[9][0] += timedelta(minutes=16)
    response = await case[1].get(ROOT + '/results', params={
        'expectedVersion': case[2]['expectedVersion'], 'expectedHash': case[2]['expectedHash']})
    assert response.status_code == 200, response.text
    assert response.json() == []


async def test_prepare_records_unready_contract_and_rejects_stale_draft(case):
    with_artifact_storage(case)
    payload = await run(case)
    store = case[0].evidence
    prepared = await store.prepare(case[5], expected_version=1, expected_hash=case[2]['expectedHash'],
        evidence_ids=[payload['verificationReceipt']['id']])
    assert prepared['canApply'] is False and prepared['status'] == 'incomplete'
    assert prepared['missingRequirements']
    from smart_reporting.management.repository import preference_approval_receipts

    async with case[7].engine.connect() as connection:
        row = (await connection.execute(select(preference_approval_receipts))).mappings().one()
    assert row['id'] == prepared['id'] and row['content_hash'] == prepared['contentHash']
    with pytest.raises(ManagementError, match='management_version_conflict'):
        await store.prepare(case[5], expected_version=2, expected_hash=case[2]['expectedHash'],
            evidence_ids=[payload['verificationReceipt']['id']])


def with_artifact_storage(case):
    from smart_reporting.reporting.delivery.publishing import ReportArtifactPersistenceService
    from smart_reporting.reporting.tests.delivery_fakes import InMemoryReportArtifactRepository

    repository = InMemoryReportArtifactRepository()
    case[0].bound.editor.artifact_persistence = ReportArtifactPersistenceService(repository, case[0].bound.editor.workspace)
    return repository


async def test_receipt_and_prepare_independently_recheck_retained_native_bytes(case, monkeypatch):
    repository = with_artifact_storage(case)
    payload = await run(case)
    from smart_reporting.management.repository import preference_verification_results

    async with case[7].engine.connect() as connection:
        document = await connection.scalar(select(preference_verification_results.c.document))
    reference = document['retained']['formats']['md']['artifact']
    assert document['retained']['issues'] == []
    assert b''.join([chunk async for chunk in repository.stream(reference['artifactKey'])]) == b'test'
    prepared = await case[0].evidence.prepare(case[5], expected_version=1, expected_hash=case[2]['expectedHash'],
        evidence_ids=[payload['verificationReceipt']['id']])
    assert prepared['canApply'] is False and prepared['missingRequirements']
    repository.chunks[reference['artifactKey']] = (b'forged',)
    with pytest.raises(ManagementError, match='management_preference_retained_artifact_changed'):
        await case[0].evidence.prepare(case[5], expected_version=1, expected_hash=case[2]['expectedHash'],
            evidence_ids=[payload['verificationReceipt']['id']])
    # 后续留证故障不能清除之前已交付的实际文件。
    assert payload['formats']['md']['artifact']['base64'] == 'dGVzdA=='


async def test_prepare_rejects_executor_drift_and_client_evidence_injection(case, monkeypatch):
    from smart_reporting.management import preference_evidence

    with_artifact_storage(case)
    payload = await run(case)
    receipt_id = payload['verificationReceipt']['id']
    read = await case[1].get(ROOT + '/results/' + receipt_id)
    assert read.status_code == 200 and read.json()['id'] == receipt_id
    assert all(value not in read.text for value in ('authBinding', 'artifactKey', case[5], case[6]))
    body = {**case[2], 'evidenceIds': [receipt_id]}
    assert (await case[1].post(ROOT + '/prepare', json=body)).status_code == 403
    injected = await case[1].post(ROOT + '/prepare', json={**body, 'canApply': True}, headers=case[3])
    assert injected.status_code == 422
    duplicate = await case[1].post(ROOT + '/prepare', json={**body, 'evidenceIds': [receipt_id, receipt_id]}, headers=case[3])
    assert duplicate.status_code == 422
    original = preference_evidence.executor_manifest()
    monkeypatch.setattr(preference_evidence, 'executor_manifest', lambda: {**original, 'fixtureDrift': True})
    changed = await case[1].post(ROOT + '/prepare', json=body, headers=case[3])
    assert changed.status_code == 409
    assert changed.json()['code'] == 'management_preference_evidence_stale'
