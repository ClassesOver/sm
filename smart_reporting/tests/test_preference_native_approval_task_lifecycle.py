"""三项真实原生证据的测试合同桥接；不代表完整生产合同已批准。"""

import base64
import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from smart_reporting.management import (
    preference_approval,
    preference_evidence,
    preference_report_preflight,
)
from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.models import INSTANCE_SCOPE, ManagementError
from smart_reporting.management.repository import (
    configuration_versions,
    preference_verification_results,
    run_configuration_snapshots,
)
from smart_reporting.management.runtime import ManagedConfigurationProvider
from smart_reporting.management.scopes import ScopeService
from smart_reporting.preferences.approval_contract import approval_contract, approval_contract_hash
from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    SqlAlchemyReportArtifactRepository,
    report_artifact_chunks_v1,
    report_artifact_files_v1,
)
from smart_reporting.reporting.delivery.xlsx import build_workbook
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_approval_apply import use_sql_reporting_state
from smart_reporting.tests.test_preference_evidence_persistence import run
from smart_reporting.tests.test_preference_preflight import _inputs
from smart_reporting.tests.test_preference_preflight_bound_generation import _register
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
OUTPUT = Path('output/system-config-preferences/approval-task-native-lifecycle')
FIELDS = {'xlsx.common.signer', 'xlsx.common.dateFormat', 'xlsx.signature.description'}


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_actual_native_evidence_applies_then_freezes_new_restart_and_derived_tasks(case, monkeypatch):
    service, client, _, _, path, admin, editor_token, repository, grants, clock, _ = case
    full_contract = approval_contract()
    # 独立测试合同只验三项真实native内容，不修改生产合同或注入证据行。
    contract = {**deepcopy(full_contract), 'fixtureScope': 'three-native-xlsx-content-fields-only',
        'fields': [deepcopy(field) for field in full_contract['fields'] if field['path'] in FIELDS],
        'editablePaths': [], 'requirements': [{'id': 'signature-content-and-layout',
            'implementation': 'implemented', 'checks': [{'format': 'xlsx', 'role': 'terminal_signature',
                'scenario': 'configured_field', 'path': field, 'dimensions': ['native']} for field in sorted(FIELDS)]}]}
    for module in (preference_evidence, preference_approval):
        monkeypatch.setattr(module, 'approval_contract', lambda: deepcopy(contract))
    startup = AgentSettings.from_environment({}, load_env_file=False)
    scopes = ScopeService(service.auth)
    vault = CredentialVault('test:' + CredentialVault.generate_key())
    provider = ManagedConfigurationProvider(scopes, vault, startup_settings=startup)

    async def register(provider, run_id):
        return await provider.register_run(run_id, INSTANCE_SCOPE, user_id='lifecycle-user',
            thread_id='lifecycle-thread', entrypoint='cli')

    old = await register(provider, 'before-application')
    assert old['preferenceRevision'] is None
    assert old['resolvedFormats']['xlsx']['common']['signer'] == '验收署名'
    draft = (await service.preferences.detail(admin))['draft']
    document = deepcopy(draft['document'])
    document['common'].update(signer='正式应用署名', dateFormat='iso')
    document['xlsx']['signature']['description'] = '版本已核验\n保持冻结口径'
    await service.preferences.save_draft(admin, document, draft['version'])
    draft = (await service.preferences.detail(admin))['draft']
    pending = await register(provider, 'draft-only-task')
    assert pending['preferences'] == old['preferences']

    editor = service.bound.editor
    context = await editor.context_for_session(await grants.lookup_session(editor_token))
    workspace = editor.workspace_registry.get(context.scope['threadId']).root
    _, materials = _inputs(workspace)
    document_context = context.job['_documentContext']
    spec = {'title': document_context['title'], 'period': document_context['periodLabel'],
        'generatedDate': document_context['generatedDate'], 'sheets': list(materials.sheets),
        'sourceMapping': {'datasets': {}, 'cells': [], 'claims': []}}
    native_path = 'native/report.xlsx'
    original = build_workbook(output_path=workspace / native_path, title=spec['title'], period=spec['period'],
        sheets=materials.sheets, source_mapping=spec['sourceMapping'], generated_date=spec['generatedDate'])
    artifact = {'path': native_path, 'size': original.size, 'sha256': original.sha256}
    spec_identity = _register(workspace, 'native/lifecycle-spec.json', json.dumps(spec).encode())
    receipt_identity = _register(workspace, 'native/report.xlsx.receipt.json', json.dumps({
        'artifact': artifact, 'spec': spec_identity}).encode())
    context = context.model_copy(update={'delivery_format': 'xlsx', 'xlsx_path': native_path,
        'xlsx_size': original.size, 'xlsx_sha256': original.sha256})
    editor.state_repository.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    editor.state_repository.state.payload.update(artifacts=[artifact, spec_identity, receipt_identity],
        workflowCheckpoint={'files': [spec_identity, receipt_identity]})
    await use_sql_reporting_state(editor, repository.engine)
    grant, _ = await grants.issue(context)
    editor_token, _ = await grants.exchange(grant)
    client.cookies.set(EDITOR_SESSION_COOKIE, editor_token, path=path)
    active = list(case)
    active[2] = {'expectedVersion': draft['version'], 'expectedHash': draft['contentHash']}
    active[6] = editor_token
    async with repository.engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    editor.artifact_persistence = ReportArtifactPersistenceService(
        SqlAlchemyReportArtifactRepository(repository.engine), editor.workspace)

    async def actual_xlsx(function, *args, **kwargs):
        return function(*args, **{**kwargs, 'formats': ('xlsx',)})

    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', actual_xlsx)
    payload = await run(active)
    receipt = payload['verificationReceipt']
    async with repository.engine.connect() as connection:
        record = await connection.scalar(select(preference_verification_results.c.document).where(
            preference_verification_results.c.id == receipt['id']))
    assert {row['path'] for row in record['evidence']} == FIELDS
    assert all(row['readerGroup'] == 'xlsx_native_signature_content_v1' and row['status'] == 'passed'
        for row in record['evidence'])
    reference = record['retained']['formats']['xlsx']['artifact']
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    retained = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
    assert retained == base64.b64decode(payload['formats']['xlsx']['artifact']['base64'], validate=True)
    assert sha256(retained).hexdigest() == reference['sha256']
    prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
        expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
    assert prepared['canApply'] is True and prepared['status'] == 'ready'
    approval = preference_approval.PreferenceApprovalService(evidence=service.evidence)
    request = {'expected_version': draft['version'], 'expected_hash': draft['contentHash'],
        'expected_effective_revision': 0, 'approval_id': prepared['id'],
        'expected_approval_hash': prepared['contentHash']}
    published = await approval.preferences.apply_approved(admin, **request)
    assert published['revision'] == 1 and published['approvalId'] == prepared['id']

    # 局部合同批准不能在恢复后的完整生产合同下再次通过应用。
    for module in (preference_evidence, preference_approval):
        monkeypatch.setattr(module, 'approval_contract', lambda: deepcopy(full_contract))
    with pytest.raises(ManagementError) as rejected:
        await approval.preferences.apply_approved(admin, **request)
    assert rejected.value.code == 'management_preference_approval_stale'
    new = await register(provider, 'after-application')
    assert new['preferenceRevision'] == 1 and new['preferenceHash'] == draft['contentHash']
    assert new['generatedDate'] == '2026-11-06'
    assert all(value['common']['signer'] == '正式应用署名' for value in new['resolvedFormats'].values())
    later_document = deepcopy(draft['document'])
    later_document['common']['signer'] = '后续未发布署名'
    await service.preferences.save_draft(admin, later_document, draft['version'])
    clock[0] += timedelta(days=4)
    restarted = ManagedConfigurationProvider(scopes, vault,
        startup_settings=replace(startup, model_timeout_seconds=123))
    assert await register(restarted, 'before-application') == old
    assert await register(restarted, 'draft-only-task') == pending
    assert await register(restarted, 'after-application') == new
    derived = await restarted.inherit_run_preferences('before-application', 'derived-task', INSTANCE_SCOPE,
        user_id='lifecycle-user', thread_id='lifecycle-thread', entrypoint='report_revision')
    assert derived['preferences'] == old['preferences']
    assert derived['resolvedFormats'] == old['resolvedFormats']
    assert derived['preferenceRevision'] is None and derived['preferenceHash'] == old['preferenceHash']
    assert derived['generatedDate'] == '2026-11-10'
    assert derived['parentConfigurationHash'] == old['contentHash']
    assert derived['systemValues'] == old['systemValues']
    future = await register(restarted, 'future-task')
    assert future['generatedDate'] == '2026-11-10'
    assert future['preferenceHash'] == new['preferenceHash']
    assert future['resolvedFormats'] == new['resolvedFormats']
    clock[0] += timedelta(days=1)
    assert await restarted.inherit_run_preferences('before-application', 'derived-task', INSTANCE_SCOPE,
        user_id='lifecycle-user', thread_id='lifecycle-thread', entrypoint='report_revision') == derived
    assert await register(restarted, 'future-task') == future
    snapshots = {'old': old, 'pending': pending, 'new': new, 'derived': derived, 'future': future}
    expected = {'old': ('验收署名', '2026年11月6日', []),
        'pending': ('验收署名', '2026年11月6日', []),
        'new': ('正式应用署名', '2026-11-06', ['版本已核验', '保持冻结口径']),
        'derived': ('验收署名', '2026年11月10日', []),
        'future': ('正式应用署名', '2026-11-10', ['版本已核验', '保持冻结口径'])}
    artifacts = {}
    for name, snapshot in snapshots.items():
        target = OUTPUT / (name + '.xlsx')
        assert not target.exists()
        built = build_workbook(output_path=target, title='任务冻结核验', period='2026年11月',
            sheets=materials.sheets, preferences=snapshot['resolvedFormats']['xlsx'],
            generated_date=snapshot['generatedDate'], source_mapping=spec['sourceMapping'])
        assert not built.issues
        book = load_workbook(target)
        assert book['业务数据']['B2'].value == 1234.56
        assert book['业务数据']['B3'].value == -234.56
        assert book['业务数据']['B4'].value == '=SUM(B2:B3)'
        assert load_workbook(target, data_only=True)['业务数据']['B4'].value == 1000
        signer, date, description = expected[name]
        assert book['说明']['A2'].value == signer
        assert book['说明']['A3'].value == date
        assert [row[0].value for row in list(book['说明'].rows)[3:]] == description
        artifacts[name] = {'path': target.name, 'size': built.size, 'sha256': built.sha256}
    async with repository.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(run_configuration_snapshots)) == 5
        versions = (await connection.execute(select(configuration_versions).where(
            configuration_versions.c.kind == 'preferences'))).mappings().all()
        stored_snapshots = (await connection.execute(select(run_configuration_snapshots))).mappings().all()
    assert len(versions) == 1 and versions[0]['content_hash'] == draft['contentHash']
    assert versions[0]['preference_approval_id'] == prepared['id']
    for snapshot in snapshots.values():
        stored = next(row for row in stored_snapshots if row['run_id'] == snapshot['runId'])
        assert stored['content_hash'] == snapshot['contentHash'] == configuration_hash(stored['document'])
        assert stored['document'] == {key: value for key, value in snapshot.items() if key != 'contentHash'}
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / 'retained-preflight.xlsx').write_bytes(retained)
    (OUTPUT / 'proof.json').write_text(json.dumps({'fixtureScope': contract['fixtureScope'],
        'testContractHash': approval_contract_hash(contract), 'productionContractHash': approval_contract_hash(full_contract),
        'productionContractRejectsFixtureApproval': rejected.value.code,
        'executorManifestHash': record['executorManifestHash'], 'executorManifest': record['executorManifest'],
        'nativeEvidence': record['evidence'], 'prepared': prepared,
        'published': {key: published[key] for key in ('revision', 'contentHash', 'approvalId')},
        'retainedArtifact': {'size': len(retained), 'sha256': sha256(retained).hexdigest()},
        'snapshots': snapshots, 'artifacts': artifacts,
        'boundary': '独立三项native测试合同的实际工程桥接，不是完整生产批准或业务E2E；无伪造evidence行。'},
        ensure_ascii=False, indent=2))
