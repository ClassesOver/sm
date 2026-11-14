"""正式XLSX落款内容在真实管理HTTP、SQL独立留存和prepare中的边界。"""

import base64
import json
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from sqlalchemy import select, update

from smart_reporting.management import preference_preflight, preference_report_preflight
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
from smart_reporting.reporting.delivery.xlsx import build_workbook
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_evidence_persistence import run
from smart_reporting.tests.test_preference_preflight import _inputs
from smart_reporting.tests.test_preference_preflight_bound_generation import _register
from smart_reporting.tests.test_preference_verification_handoff import case as case
from smart_reporting.tests.test_preference_workbook_signature_native import changed_package

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
OUTPUT = Path('output/system-config-preferences/xlsx-signature-native-evidence')
FIELDS = {'xlsx.common.signer', 'xlsx.common.dateFormat', 'xlsx.signature.description'}


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('scenario', ['configured', 'changed_description', 'hidden_row', 'retained_drift',
    'escaped_signer', 'escape_unprotected', 'zero_default_width'])
async def test_native_signature_persists_exact_content_without_approving_full_contract(case, monkeypatch, scenario):
    service, client, _, _, path, admin, editor_token, repository, grants, _, _ = case
    editor = service.bound.editor
    context = await editor.context_for_session(await grants.lookup_session(editor_token))
    workspace = editor.workspace_registry.get(context.scope['threadId']).root
    _, materials = _inputs(workspace)
    document_context = context.job['_documentContext']
    spec = {'title': document_context['title'], 'period': document_context['periodLabel'],
        'generatedDate': document_context['generatedDate'], 'sheets': list(materials.sheets),
        'sourceMapping': {'datasets': {}, 'cells': [], 'claims': []}}
    original_artifact = build_workbook(output_path=workspace / 'native/report.xlsx', title=spec['title'],
        period=spec['period'], generated_date=spec['generatedDate'], sheets=materials.sheets,
        source_mapping=spec['sourceMapping'])
    artifact = {'path': 'native/report.xlsx', 'size': original_artifact.size, 'sha256': original_artifact.sha256}
    spec_identity = _register(workspace, 'native/signature-spec.json', json.dumps(spec).encode())
    receipt_identity = _register(workspace, 'native/report.xlsx.receipt.json', json.dumps({
        'artifact': artifact, 'spec': spec_identity}).encode())
    context = context.model_copy(update={'delivery_format': 'xlsx', 'xlsx_path': artifact['path'],
        'xlsx_size': artifact['size'], 'xlsx_sha256': artifact['sha256']})
    editor.state_repository.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    editor.state_repository.state.payload.update(artifacts=[artifact, spec_identity, receipt_identity],
        workflowCheckpoint={'files': [spec_identity, receipt_identity]})
    grant, _ = await grants.issue(context)
    editor_token, _ = await grants.exchange(grant)
    client.cookies.set(EDITOR_SESSION_COOKIE, editor_token, path=path)
    draft = (await service.preferences.detail(admin))['draft']
    document = deepcopy(draft['document'])
    escaped = scenario in ('escaped_signer', 'escape_unprotected')
    document['common'].update(signer='_x0041_' if escaped else '编制 & 复核', dateFormat='iso')
    if escaped:
        # 隔离单元格转义；页眉页脚的独立兼容性不作为此测试的替代证据。
        document['xlsx']['print']['headerFooter']['enabled'] = False
    document['xlsx']['signature']['description'] = '仅供内部核验\n\n请复核冻结口径'
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

    async def actual_xlsx(function, *args, **kwargs):
        return function(*args, **{**kwargs, 'formats': ('xlsx',)})

    original = preference_preflight._generate
    inputs = {}

    def generate(root, preferences, frozen):
        inputs.update(preferences=preferences.model_dump(mode='json', by_alias=True), frozen=deepcopy(frozen))
        issues = original(root, preferences, frozen)
        if scenario in ('changed_description', 'hidden_row', 'escape_unprotected', 'zero_default_width'):
            def mutate(node):
                data = node.find('{*}sheetData')
                if scenario == 'hidden_row':
                    data[1].set('hidden', '1')
                elif scenario == 'escape_unprotected':
                    data[1][0].find('{*}is/{*}t').text = '_x0041_'
                elif scenario == 'zero_default_width':
                    prop = ElementTree.Element('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetFormatPr',
                        defaultColWidth='0')
                    node.insert(3, prop)
                    node.remove(node.find('{*}cols'))
                else:
                    data[-1][0].find('{*}is/{*}t').text = '注入的错误说明'
            target = root / 'report.xlsx'
            target.write_bytes(changed_package(target.read_bytes(), mutate))
        return issues

    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', actual_xlsx)
    monkeypatch.setattr(preference_preflight, '_generate', generate)
    before = executor_manifest()
    payload = await run(active)
    assert payload['bindingValid'] is True and payload['canApply'] is False
    assert 'verificationReceipt' in payload, payload.get('issues')
    entry = payload['formats']['xlsx']
    assert entry['artifact'] is not None
    assert entry['readback']['status'] == ('failed' if scenario in (
        'changed_description', 'hidden_row', 'escape_unprotected', 'zero_default_width') else 'passed')
    receipt = payload['verificationReceipt']
    async with repository.engine.connect() as connection:
        record = await connection.scalar(select(preference_verification_results.c.document).where(
            preference_verification_results.c.id == receipt['id']))
    reference = record['retained']['formats']['xlsx']['artifact']
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
    assert content == base64.b64decode(entry['artifact']['base64'], validate=True)
    assert len(content) == reference['size'] == entry['artifact']['size']
    assert sha256(content).hexdigest() == reference['sha256'] == entry['artifact']['sha256']
    book = load_workbook(BytesIO(content))
    assert book['业务数据']['B4'].value == '=SUM(B2:B3)'
    assert load_workbook(BytesIO(content), data_only=True)['业务数据']['B4'].value == 1000
    assert book['说明']['A2'].value == ('_x0041_' if scenario == 'escape_unprotected'
        else '_x005F_x0041_' if escaped else '编制 & 复核')
    assert book['说明']['A3'].value == '2026-11-13'
    assert book['说明']['A5'].value == ''
    assert book['说明']['A6'].value == ('注入的错误说明' if scenario == 'changed_description' else '请复核冻结口径')
    with ZipFile(BytesIO(content)) as package:
        assert json.loads(package.read('smart-reporting/source-mapping.json'))['sources'] == spec['sourceMapping']
    rows = [row for row in record['evidence'] if row.get('readerGroup') == 'xlsx_native_signature_content_v1']
    assert {row['path'] for row in rows} == (set() if scenario in ('hidden_row', 'zero_default_width') else FIELDS)
    expected_failed = ({'xlsx.signature.description'} if scenario == 'changed_description'
        else {'xlsx.common.signer'} if scenario == 'escape_unprotected' else set())
    assert {row['path'] for row in rows if row['status'] == 'failed'} == expected_failed
    assert all(row['dimension'] == 'native' and row['scenario'] == 'configured_field'
        and row['artifact'] == {'sizeBytes': len(content), 'sha256': sha256(content).hexdigest()} for row in rows)
    prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
        expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
    assert prepared['status'] == 'incomplete' and prepared['canApply'] is False
    field_gaps = {gap['path'] for gap in prepared['missingRequirements']
        if gap.get('scenario') == 'configured_field' and gap.get('path') in FIELDS}
    expected_gaps = FIELDS if scenario in ('hidden_row', 'zero_default_width') else expected_failed
    assert field_gaps == expected_gaps
    drift_code = None
    if scenario == 'retained_drift':
        async with repository.engine.begin() as connection:
            await connection.execute(update(report_artifact_chunks_v1).where(
                report_artifact_chunks_v1.c.artifact_key == reference['artifactKey'],
                report_artifact_chunks_v1.c.chunk_index == 0).values(content=b'changed-signature-retention'))
        with pytest.raises(ManagementError) as changed:
            await service.evidence.prepare(admin, expected_version=draft['version'],
                expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
        drift_code = changed.value.code
        assert drift_code == 'management_preference_retained_artifact_changed'
    assert record['executorManifest'] == before == executor_manifest()
    directory = OUTPUT / scenario
    directory.mkdir()
    (directory / 'actual.xlsx').write_bytes(content)
    (directory / 'readback-input.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2))
    if entry.get('pdf'):
        (directory / 'preview.pdf').write_bytes(base64.b64decode(entry['pdf']['base64'], validate=True))
    (directory / 'readback.json').write_text(json.dumps({
        'scope': 'real_xlsx_http_sql_retention_with_synthetic_business_and_workflow',
        'artifact': {'sizeBytes': len(content), 'sha256': sha256(content).hexdigest()},
        'executorManifestHash': configuration_hash(before), 'executorStableWithinScenario': True,
        'readback': entry['readback'], 'nativeEvidence': rows, 'prepared': prepared,
        'independentSqlStreamMatchesReturnedBytes': True, 'retainedDriftRejected': drift_code,
        'boundary': '仅三项configured_field/native；不证明视觉、生命周期或完整批准。',
    }, ensure_ascii=False, indent=2))
