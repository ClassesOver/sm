"""完整数字native证据经真实HTTP/SQL留存与prepare验证。"""

import base64
import json
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path

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
from smart_reporting.tests.test_preference_workbook_number_readback import _mutate

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
OUTPUT = Path('output/system-config-preferences/xlsx-number-native-evidence')
MARKER = 'xlsx_native_number_fields_v1'
FIELDS = {'xlsx.numbers.' + field for field in ('decimalPlaces', 'thousandsSeparator', 'negativeStyle', 'percentPlaces', 'dateFormat')}


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('scenario', ['configured', 'format', 'source_drift', 'only_overrides', 'retained_drift'])
async def test_number_native_fields_persist_without_approving_full_contract(case, monkeypatch, scenario):
    service, client, _, _, path, admin, editor_token, repository, grants, _, _ = case
    editor = service.bound.editor
    context = await editor.context_for_session(await grants.lookup_session(editor_token))
    workspace = editor.workspace_registry.get(context.scope['threadId']).root
    _, materials = _inputs(workspace)
    sheets = deepcopy(list(materials.sheets))
    sheets[0]['rows'][1][1] = {'value': 1234.56, 'style': {'bold': True}}
    sheets[0]['rows'][4][1]['style'] = {'fontColor': '#334455'}
    sheets.append({'name': '日期明细', 'rows': [['项目', '值'],
        ['日期', {'value': '2026-10-30', 'valueType': 'date'}],
        ['百分点', {'value': 7.5, 'valueType': 'percentPoints'}]]})
    if scenario == 'only_overrides':
        for sheet in sheets:
            for row in sheet['rows']:
                for index, raw in enumerate(row):
                    value = raw if isinstance(raw, dict) else {'value': raw}
                    if type(value.get('value')) in (int, float) or value.get('valueType') == 'date':
                        row[index] = {**value, 'style': {**value.get('style', {}), 'numberFormat': '0.00'}}
    document_context = context.job['_documentContext']
    spec = {'title': document_context['title'], 'period': document_context['periodLabel'],
        'generatedDate': document_context['generatedDate'], 'sheets': sheets,
        'sourceMapping': {'cells': [{'sheetName': '业务数据', 'cell': 'B2', 'exactValue': 1234.56}]}}
    built = build_workbook(output_path=workspace / 'native/report.xlsx', title=spec['title'],
        period=spec['period'], generated_date=spec['generatedDate'], sheets=sheets,
        source_mapping=spec['sourceMapping'])
    artifact = {'path': 'native/report.xlsx', 'size': built.size, 'sha256': built.sha256}
    spec_identity = _register(workspace, 'native/numbers-spec.json', json.dumps(spec).encode())
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
    document['common'].update(signer='数字格式核验', dateFormat='iso')
    document['xlsx']['numbers'].update(decimalPlaces=3, percentPlaces=1,
        negativeStyle='parentheses', thousandsSeparator=True, dateFormat='slash')
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
        target = root / 'report.xlsx'
        if scenario == 'format':
            target.write_bytes(_mutate(target.read_bytes(), 'B2', number_format=True))
        elif scenario == 'source_drift':
            target.write_bytes(_mutate(target.read_bytes(), 'B4', raw_value='1000.00000000000000001'))
        return issues

    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', actual_xlsx)
    monkeypatch.setattr(preference_preflight, '_generate', generate)
    before = executor_manifest()
    payload = await run(active)
    assert payload['bindingValid'] is True and payload['canApply'] is False
    entry = payload['formats']['xlsx']
    assert entry['artifact'] is not None
    if 'verificationReceipt' not in payload:
        directory = OUTPUT / ('unrecorded-' + scenario)
        directory.mkdir(exist_ok=True)
        (directory / 'actual.xlsx').write_bytes(base64.b64decode(entry['artifact']['base64'], validate=True))
        (directory / 'inputs.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2))
        (directory / 'result.json').write_text(json.dumps({'issues': payload.get('issues'),
            'readback': entry['readback'], 'beforeManifest': before, 'afterManifest': executor_manifest(),
            'boundary': '已返回文件但无验收回执，不是SQL留证通过。'}, ensure_ascii=False, indent=2))
    assert 'verificationReceipt' in payload, payload.get('issues')
    assert entry['readback']['status'] == ('failed' if scenario in ('format', 'source_drift') else 'passed')
    if scenario in ('format', 'source_drift'):
        failures = [c for c in entry['readback']['checks'] if not c['passed']]
        expected_path = 'xlsx.numbers.decimalPlaces' if scenario == 'format' else 'xlsx.numbers.nativeStructure'
        assert any(c['path'] == expected_path for c in failures), failures
    async with repository.engine.connect() as connection:
        record = await connection.scalar(select(preference_verification_results.c.document).where(
            preference_verification_results.c.id == payload['verificationReceipt']['id']))
    reference = record['retained']['formats']['xlsx']['artifact']
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
    assert content == base64.b64decode(entry['artifact']['base64'], validate=True)
    assert len(content) == reference['size'] == entry['artifact']['size']
    assert sha256(content).hexdigest() == reference['sha256'] == entry['artifact']['sha256']
    book = load_workbook(BytesIO(content))
    assert book['业务数据']['B2'].value == 1234.56
    assert book['业务数据']['B4'].value == '=SUM(B2:B3)'
    assert load_workbook(BytesIO(content), data_only=True)['业务数据']['B4'].value == 1000
    prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
        expected_hash=draft['contentHash'], evidence_ids=[payload['verificationReceipt']['id']])
    assert prepared['status'] == 'incomplete' and prepared['canApply'] is False
    rows = [r for r in record['evidence'] if r.get('readerGroup') == MARKER]
    assert {r['path'] for r in rows} == (set() if scenario in ('source_drift', 'only_overrides') else FIELDS)
    failed = {'xlsx.numbers.' + f for f in ('decimalPlaces', 'thousandsSeparator', 'negativeStyle')} if scenario == 'format' else set()
    assert {r['path'] for r in rows if r['status'] == 'failed'} == failed
    assert all(r['dimension'] == 'native' and r['scenario'] == 'configured_field'
        and r['artifact'] == {'sizeBytes': len(content), 'sha256': sha256(content).hexdigest()} for r in rows)
    gaps = {g['path'] for g in prepared['missingRequirements']
        if g.get('path') in FIELDS and g.get('scenario') == 'configured_field'}
    assert gaps == (FIELDS if scenario in ('source_drift', 'only_overrides') else failed)
    drift_code = None
    if scenario == 'retained_drift':
        async with repository.engine.begin() as connection:
            await connection.execute(update(report_artifact_chunks_v1).where(
                report_artifact_chunks_v1.c.artifact_key == reference['artifactKey'],
                report_artifact_chunks_v1.c.chunk_index == 0).values(content=b'changed-number-retention'))
        with pytest.raises(ManagementError) as changed:
            await service.evidence.prepare(admin, expected_version=draft['version'],
                expected_hash=draft['contentHash'], evidence_ids=[payload['verificationReceipt']['id']])
        drift_code = changed.value.code
        assert drift_code == 'management_preference_retained_artifact_changed'
    assert record['executorManifest'] == before == executor_manifest()
    directory = OUTPUT / ('sql-' + scenario)
    directory.mkdir()
    (directory / 'actual.xlsx').write_bytes(content)
    (directory / 'inputs.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2))
    (directory / 'result.json').write_text(json.dumps({
        'scope': 'real_xlsx_http_sql_with_synthetic_business_and_workflow',
        'artifact': {'sizeBytes': len(content), 'sha256': sha256(content).hexdigest()},
        'executorManifestHash': configuration_hash(before), 'executorManifest': before,
        'readback': entry['readback'], 'prepared': prepared, 'nativeEvidence': rows, 'retainedDriftRejected': drift_code,
        'independentSqlStreamMatchesReturnedBytes': True,
        'boundary': '最多五项configured_field/native；不证明worksheet完整场景/视觉/生命周期或完整生产批准。',
    }, ensure_ascii=False, indent=2))
