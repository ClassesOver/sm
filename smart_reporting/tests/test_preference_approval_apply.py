"""批准应用事务；小型完整合同仅用于真实数据库CAS测试，不代表生产需求完成。"""

import asyncio
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.models import ManagementError
from smart_reporting.management.repository import (
    audit_events,
    configuration_versions,
    preference_approval_receipts,
    preference_verification_results,
)
from smart_reporting.report_editor.repository import report_editor_sessions_v1
from smart_reporting.report_editor.service import token_hash
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_evidence_persistence import run, with_artifact_storage
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def use_sql_reporting_state(editor, engine):
    """仅将固定合成报告种入原生SQL，供批准消费者共享真实行锁验证。"""
    from agno.db.postgres import AsyncPostgresDb
    from sqlalchemy import update
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from smart_reporting.reporting.workflow.repository import ReportingStateRepository

    previous = editor.state_repository
    state = previous.state.model_copy(deep=True)
    registered = await previous.get_run(state.report_run_id)
    native = ReportingStateRepository(AsyncPostgresDb(db_engine=engine))
    await native.initialize()
    # 固定合成run跨节点复用；清除上一故障场景有意留下的身份变更。
    async with engine.begin() as connection:
        await connection.execute(update(native.runs).where(
            native.runs.c.report_run_id == state.report_run_id).values(
                **registered, revision=state.revision, entrypoint='workflow'))
    await native.register_run(**registered, revision=state.revision, entrypoint='workflow')
    values = native._row_values(state)
    async with engine.begin() as connection:
        await connection.execute(pg_insert(native.states).values(**values).on_conflict_do_update(
            index_elements=[native.states.c.report_run_id], set_=values))
    editor.state_repository = native


@pytest.fixture
async def approved(case, monkeypatch, request):
    from smart_reporting.management import preference_approval, preference_evidence
    from smart_reporting.preferences.approval_contract import approval_contract_hash

    # 测试专用registry替换，不在生产加force/skip或伪造完整生产合同。
    contract = {'contractVersion': 1, 'requirementsVersion': 1, 'specDigest': 'a' * 64,
        'fields': [], 'editablePaths': [], 'requirements': [{'id': 'fixture-native-byte-readback',
            'implementation': 'implemented', 'checks': [{'format': 'md', 'role': 'fixture',
                'scenario': 'complete', 'dimensions': ['native']}]}]}
    for module in (preference_evidence, preference_approval):
        monkeypatch.setattr(module, 'approval_contract', lambda: deepcopy(contract))
    missing_runtime = getattr(request, 'param', None) == 'missing_runtime'
    if missing_runtime:
        from smart_reporting.management import preference_verification

        manifest = preference_evidence.executor_manifest()
        manifest = {**manifest, 'runtimeIdentityComplete': False,
            'runtimeIdentityIssues': [{'code': 'font_identity_missing', 'resource': 'fixture-font'}]}
        for module in (preference_evidence, preference_verification, preference_approval):
            monkeypatch.setattr(module, 'executor_manifest', lambda: deepcopy(manifest))
    with_artifact_storage(case)
    evidence = case[0].evidence
    original_insert = evidence._insert

    async def insert_fixture(table, id, document):
        if table is preference_verification_results:
            document = deepcopy(document)
            document['evidence'] = [{'requirementId': 'fixture-native-byte-readback', 'format': 'md',
                'role': 'fixture', 'scenario': 'complete', 'dimension': 'native', 'status': 'passed',
                'objectScope': 'complete', 'authorized': True,
                'sourceArtifact': {'format': 'md', 'role': 'artifact'},
                'binding': {'draftVersion': case[2]['expectedVersion'], 'draftHash': case[2]['expectedHash'],
                    'contractHash': approval_contract_hash(contract),
                    'executorManifestHash': document['executorManifestHash']},
                'artifact': {'sha256': document['result']['formats']['md']['artifact']['sha256'], 'sizeBytes': 4}}]
        return await original_insert(table, id, document)

    monkeypatch.setattr(evidence, '_insert', insert_fixture)
    result = await run(case)
    fixture_id = result['verificationReceipt']['id']
    prepared = await evidence.prepare(case[5], expected_version=1,
        expected_hash=case[2]['expectedHash'], evidence_ids=[fixture_id])
    assert prepared['canApply'] is (not missing_runtime)
    assert prepared['status'] == ('incomplete' if missing_runtime else 'ready')
    # 批准阶段使用真实Reporting状态，合同/字段证据仍是上面的明确测试替身。
    await use_sql_reporting_state(case[0].bound.editor, case[7].engine)
    service = preference_approval.PreferenceApprovalService(evidence=evidence)
    case[0].preferences.approval_service = service
    request = {'expected_version': 1, 'expected_hash': case[2]['expectedHash'],
        'expected_effective_revision': 0, 'approval_id': prepared['id'],
        'expected_approval_hash': prepared['contentHash']}
    return service, request, prepared, fixture_id


async def count_publications(case):
    async with case[7].engine.connect() as connection:
        versions = await connection.scalar(select(func.count()).select_from(configuration_versions).where(
            configuration_versions.c.kind == 'preferences'))
        audits = await connection.scalar(select(func.count()).select_from(audit_events).where(
            audit_events.c.action == 'format_preferences_published'))
    return versions, audits


async def test_preferences_publish_without_approval_is_closed(case):
    with pytest.raises(ManagementError, match='management_preference_approval_required'):
        await case[0].preferences.publish(case[5], 1)
    assert await count_publications(case) == (0, 0)


async def test_approved_apply_concurrent_retry_creates_one_immutable_version(case, approved):
    _, request, prepared, _ = approved
    first, second = await asyncio.gather(*(
        case[0].preferences.apply_approved(case[5], **request) for _ in range(2)))
    assert first['revision'] == second['revision'] == 1
    assert first['contentHash'] == second['contentHash'] == case[2]['expectedHash']
    assert first['approvalId'] == second['approvalId'] == prepared['id']
    assert await count_publications(case) == (1, 1)
    detail = await case[0].preferences.detail(case[5])
    assert detail['effective']['approvalId'] == prepared['id']
    assert (await case[0].preferences.version(case[5], 1))['approvalId'] == prepared['id']
    assert (await case[0].preferences.apply_approved(case[5], **request))['revision'] == 1
    assert await count_publications(case) == (1, 1)


@pytest.mark.parametrize('fault', ['draft', 'effective', 'approval_hash', 'expired', 'executor',
    'contract', 'material', 'retained', 'admin_logout', 'editor_revoke'])
async def test_apply_rejects_drift_or_revocation_without_partial_version(case, approved, monkeypatch, fault):
    service, request, _, _ = approved
    if fault == 'draft':
        document = deepcopy((await service.preferences.detail(case[5]))['draft']['document'])
        document['common']['signer'] = '竞争保存'
        await service.preferences.save_draft(case[5], document, 1)
    elif fault == 'effective':
        request = {**request, 'expected_effective_revision': 9}
    elif fault == 'approval_hash':
        request = {**request, 'expected_approval_hash': '0' * 64}
    elif fault == 'expired':
        case[9][0] += timedelta(minutes=31)
    elif fault == 'executor':
        from smart_reporting.management import preference_approval
        original = preference_approval.executor_manifest()
        monkeypatch.setattr(preference_approval, 'executor_manifest', lambda: {**original, 'fixtureDrift': True})
    elif fault == 'contract':
        from smart_reporting.management import preference_approval
        original = preference_approval.approval_contract()
        monkeypatch.setattr(preference_approval, 'approval_contract', lambda: {**original, 'fixtureDrift': True})
    elif fault == 'material':
        context = await service.handoff.bound.editor.context_for_session(
            await service.handoff.bound.grants.lookup_session(case[6]))
        workspace = service.handoff.bound.editor.workspace_registry.get(context.scope['threadId'])
        (workspace.root / context.markdown_path).write_bytes(b'changed source after approval')
    elif fault == 'retained':
        document = (await service.evidence._load(preference_verification_results, approved[3]))['document']
        key = document['retained']['formats']['md']['artifact']['artifactKey']
        service.handoff.bound.editor.artifact_persistence.repository.chunks[key] = (b'forged retained bytes',)
    elif fault == 'admin_logout':
        await service.auth.logout(case[5])
    else:
        async with case[7].engine.begin() as connection:
            await connection.execute(delete(report_editor_sessions_v1).where(
                report_editor_sessions_v1.c.session_hash == token_hash(case[6])))
    with pytest.raises(ManagementError):
        await service.preferences.apply_approved(case[5], **request)
    assert await count_publications(case) == (0, 0)


async def test_apply_rejects_other_receipt_and_restored_draft_old_receipt(case, approved):
    service, request, prepared, fixture_id = approved
    other = await case[0].evidence.prepare(case[5], expected_version=1,
        expected_hash=case[2]['expectedHash'], evidence_ids=[fixture_id])
    await service.preferences.apply_approved(case[5], **request)
    with pytest.raises(ManagementError):
        await service.preferences.apply_approved(case[5], **{**request,
            'approval_id': other['id'], 'expected_approval_hash': other['contentHash']})
    restored = await service.preferences.restore_draft(case[5], 1, 1)
    assert restored['version'] == 2
    with pytest.raises(ManagementError):
        await service.preferences.apply_approved(case[5], **request)
    assert await count_publications(case) == (1, 1)
    assert prepared['id'] != other['id']


async def test_apply_audit_failure_rolls_back_version_and_approval_use(case, approved, monkeypatch):
    service, request, _, _ = approved
    original = service.preferences._audit

    async def fail(connection, action, **details):
        if action == 'format_preferences_published':
            raise RuntimeError('fixture-audit-insert-failure')
        return await original(connection, action, **details)

    monkeypatch.setattr(service.preferences, '_audit', fail)
    with pytest.raises(RuntimeError, match='fixture-audit'):
        await service.preferences.apply_approved(case[5], **request)
    assert await count_publications(case) == (0, 0)
    monkeypatch.setattr(service.preferences, '_audit', original)
    assert (await service.preferences.apply_approved(case[5], **request))['revision'] == 1
    assert await count_publications(case) == (1, 1)


async def test_incomplete_production_receipt_cannot_apply(case):
    from smart_reporting.management.preference_approval import PreferenceApprovalService

    with_artifact_storage(case)
    result = await run(case)
    prepared = await case[0].evidence.prepare(case[5], expected_version=1,
        expected_hash=case[2]['expectedHash'], evidence_ids=[result['verificationReceipt']['id']])
    assert prepared['canApply'] is False
    case[0].preferences.approval_service = PreferenceApprovalService(evidence=case[0].evidence)
    with pytest.raises(ManagementError, match='management_preference_approval_incomplete'):
        await case[0].preferences.apply_approved(case[5], expected_version=1,
            expected_hash=case[2]['expectedHash'], expected_effective_revision=0,
            approval_id=prepared['id'], expected_approval_hash=prepared['contentHash'])
    assert await count_publications(case) == (0, 0)


async def test_approval_foreign_key_and_unique_reference_exist(case, approved):
    _, request, prepared, _ = approved
    await case[0].preferences.apply_approved(case[5], **request)
    async with case[7].engine.connect() as connection:
        row = (await connection.execute(select(configuration_versions).where(
            configuration_versions.c.kind == 'preferences'))).mappings().one()
        receipt = await connection.scalar(select(preference_approval_receipts.c.content_hash).where(
            preference_approval_receipts.c.id == row['preference_approval_id']))
    assert row['preference_approval_id'] == prepared['id'] and receipt == prepared['contentHash']
    assert configuration_hash(row['document']) == request['expected_hash']


async def test_apply_api_requires_current_authority_csrf_and_strict_server_ids(case, approved):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.runtime.settings import AgentSettings
    from smart_reporting.tests.test_preference_verification_handoff import ORIGIN

    service, request, _, _ = approved
    app = FastAPI()
    app.state.preference_approval = service
    app.include_router(create_management_router(service.auth,
        ManagementSettings(public_origin=ORIGIN, allow_local_http=True),
        startup_settings=AgentSettings.from_environment({}, load_env_file=False)))
    payload = {'expectedVersion': request['expected_version'], 'expectedHash': request['expected_hash'],
        'expectedEffectiveRevision': request['expected_effective_revision'], 'approvalId': request['approval_id'],
        'expectedApprovalHash': request['expected_approval_hash']}
    path = '/management/api/v1/configuration/preferences/apply'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        assert (await client.post(path, json=payload)).status_code == 401
        client.cookies.set(SESSION_COOKIE, case[5], path='/management')
        assert (await client.post(path, json=payload)).status_code == 403
        for changes in ({'canApply': True}, {'workspace': '/tmp/client-path'}, {'checks': []},
            {'expectedVersion': True}, {'expectedEffectiveRevision': True}):
            assert (await client.post(path, json={**payload, **changes}, headers=case[3])).status_code == 422
        applied = await client.post(path, json=payload, headers=case[3])
        assert applied.status_code == 200, applied.text
        assert applied.json()['approvalId'] == request['approval_id']
        assert all(secret not in applied.text for secret in (case[5], case[6], 'authBinding', 'artifactKey'))
    assert await count_publications(case) == (1, 1)


async def test_apply_uses_one_database_connection_while_holding_management_transaction(case, approved):
    from sqlalchemy.ext.asyncio import create_async_engine

    service, request, _, _ = approved
    repository, grants = case[7], case[8]
    engine = create_async_engine(repository.engine.url, pool_size=1, max_overflow=0, pool_timeout=0.2)
    original = repository.engine
    repository.engine = grants.repository.engine = engine
    try:
        result = await asyncio.wait_for(service.preferences.apply_approved(case[5], **request), 10)
        assert result['revision'] == 1
        assert await count_publications(case) == (1, 1)
    finally:
        repository.engine = grants.repository.engine = original
        await engine.dispose()


async def test_database_rejects_unknown_reused_or_missing_approval_references(case, approved):
    from uuid import uuid4

    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    _, request, _, _ = approved
    await case[0].preferences.apply_approved(case[5], **request)
    async with case[7].engine.connect() as connection:
        row = dict((await connection.execute(select(configuration_versions).where(
            configuration_versions.c.kind == 'preferences'))).mappings().one())
    for reference in (request['approval_id'], str(uuid4()), None):
        with pytest.raises(IntegrityError):
            async with case[7].engine.begin() as connection:
                await connection.execute(insert(configuration_versions).values(**{
                    **row, 'revision': 2, 'preference_approval_id': reference}))
    assert await count_publications(case) == (1, 1)


@pytest.mark.parametrize('fault', ['expiry', 'editor_revoke'])
async def test_apply_rechecks_authority_after_retained_bytes_readback(case, approved, monkeypatch, fault):
    service, request, _, _ = approved
    original = service.evidence._current_artifacts

    async def changed(*args):
        result = await original(*args)
        if fault == 'expiry':
            case[9][0] += timedelta(minutes=31)
        else:
            async with case[7].engine.begin() as connection:
                await connection.execute(delete(report_editor_sessions_v1).where(
                    report_editor_sessions_v1.c.session_hash == token_hash(case[6])))
        return result

    monkeypatch.setattr(service.evidence, '_current_artifacts', changed)
    with pytest.raises(ManagementError):
        await service.preferences.apply_approved(case[5], **request)
    assert await count_publications(case) == (0, 0)


async def test_apply_editor_authority_check_serializes_revocation_until_commit(case, approved, monkeypatch):
    service, request, _, _ = approved
    checked, release, delete_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = service.handoff._check_editor_in_transaction

    async def paused(*args, **kwargs):
        await original(*args, **kwargs)
        checked.set()
        await release.wait()

    async def revoke():
        async with case[7].engine.begin() as connection:
            delete_started.set()
            await connection.execute(delete(report_editor_sessions_v1).where(
                report_editor_sessions_v1.c.session_hash == token_hash(case[6])))

    monkeypatch.setattr(service.handoff, '_check_editor_in_transaction', paused)
    applying = asyncio.create_task(service.preferences.apply_approved(case[5], **request))
    revoking = None
    try:
        await asyncio.wait_for(checked.wait(), 10)
        revoking = asyncio.create_task(revoke())
        await asyncio.wait_for(delete_started.wait(), 5)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(revoking), .15)
        release.set()
        assert (await asyncio.wait_for(applying, 10))['revision'] == 1
        await asyncio.wait_for(revoking, 5)
    finally:
        release.set()
        await asyncio.gather(applying, *([revoking] if revoking else []), return_exceptions=True)
    assert await count_publications(case) == (1, 1)


async def test_approved_apply_freezes_new_tasks_without_changing_restarted_or_child_tasks(case, approved):
    from dataclasses import replace

    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.models import INSTANCE_SCOPE
    from smart_reporting.management.runtime import ManagedConfigurationProvider
    from smart_reporting.management.scopes import ScopeService
    from smart_reporting.runtime.settings import AgentSettings

    service, request, prepared, _ = approved
    startup = AgentSettings.from_environment({}, load_env_file=False)
    provider = ManagedConfigurationProvider(ScopeService(service.auth),
        CredentialVault('test:' + CredentialVault.generate_key()), startup_settings=startup)
    owner = {'user_id': 'approval-user', 'thread_id': 'approval-thread'}
    task_a = await provider.register_run('approval-before', INSTANCE_SCOPE, entrypoint='cli', **owner)
    assert task_a['preferenceRevision'] is None
    assert task_a['resolvedFormats']['word']['common']['signer'] == '验收署名'
    changed = deepcopy((await service.preferences.detail(case[5]))['draft']['document'])
    changed['common']['signer'] = '应用后验收署名'
    saved = await service.preferences.save_draft(case[5], changed, 1)
    case[2].update(expectedVersion=2, expectedHash=saved['contentHash'])
    result = await run(case)
    prepared = await service.evidence.prepare(case[5], expected_version=2,
        expected_hash=saved['contentHash'], evidence_ids=[result['verificationReceipt']['id']])
    assert prepared['canApply'] is True
    request = {**request, 'expected_version': 2, 'expected_hash': saved['contentHash'],
        'approval_id': prepared['id'], 'expected_approval_hash': prepared['contentHash']}
    published = await service.preferences.apply_approved(case[5], **request)
    assert published['approvalId'] == prepared['id']
    task_b = await provider.register_run('approval-after', INSTANCE_SCOPE, entrypoint='cli', **owner)
    assert task_b['preferenceRevision'] == published['revision'] == 1
    assert task_b['preferenceHash'] == request['expected_hash']
    assert task_b['resolvedFormats']['word']['common']['signer'] == '应用后验收署名'
    case[9][0] += timedelta(days=1)
    restarted = ManagedConfigurationProvider(provider.scope_service, provider.vault,
        startup_settings=replace(startup, model_timeout_seconds=123))
    restored = await restarted.register_run('approval-before', INSTANCE_SCOPE, entrypoint='cli', **owner)
    assert restored == task_a
    child = await restarted.inherit_run_preferences('approval-before', 'approval-child', INSTANCE_SCOPE,
        entrypoint='report_revision', **owner)
    assert child['resolvedFormats'] == task_a['resolvedFormats'] != task_b['resolvedFormats']
    assert child['preferenceHash'] == task_a['preferenceHash']
    assert child['parentConfigurationHash'] == task_a['contentHash']
    assert child['generatedDate'] != task_a['generatedDate']
    for _ in range(2):
        assert await restarted.load_run_preferences('approval-before', INSTANCE_SCOPE, **owner) == task_a
        assert await restarted.load_run_preferences('approval-child', INSTANCE_SCOPE, **owner) == child


@pytest.mark.parametrize('approved', ['missing_runtime'], indirect=True)
async def test_stably_missing_runtime_resources_cannot_prepare_or_apply(case, approved):
    service, request, prepared, _ = approved
    assert prepared['canApply'] is False
    assert any(item['reason'] == 'executor_identity_unavailable' for item in prepared['missingRequirements'])
    with pytest.raises(ManagementError, match='management_preference_executor_identity_unavailable'):
        await service.preferences.apply_approved(case[5], **request)
    assert await count_publications(case) == (0, 0)


async def test_apply_maps_source_authority_race_to_controlled_management_error():
    from types import SimpleNamespace

    from smart_reporting.management.format_preferences import FormatPreferenceService
    from smart_reporting.preferences.models import FormatPreferences
    from smart_reporting.reporting.models import ReportingError

    async def revoked(*args, **kwargs):
        raise ReportingError('report_editor_scope_mismatch', '报告权限在文件复核期间已变化。')

    service = FormatPreferenceService(SimpleNamespace(repository=object()),
        FormatPreferences.model_validate({'common': {'signer': '错误边界测试'}}))
    service.approval_service = SimpleNamespace(apply=revoked)
    with pytest.raises(ManagementError) as caught:
        await service.apply_approved('test-only-session', expected_version=1, expected_hash='a' * 64,
            expected_effective_revision=0, approval_id='test-only-id', expected_approval_hash='b' * 64)
    assert caught.value.code == 'report_editor_scope_mismatch' and caught.value.status == 403
