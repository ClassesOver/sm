"""数字回读故障在真实HTTP/SQL留证链保持原件及失败状态。"""

import base64
import json
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from smart_reporting.management import preference_preflight, preference_report_preflight
from smart_reporting.management.configuration_store import configuration_hash
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
from smart_reporting.tests.test_preference_workbook_signature_native import changed_package

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
OUTPUT = Path('output/system-config-preferences/xlsx-number-readback')


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('scenario', ['configured', 'format', 'value', 'cache', 'date', 'namespace'])
async def test_number_readback_failures_retain_real_artifact_and_failed_receipt(case, monkeypatch, scenario):
    service, client, _, _, path, admin, editor_token, repository, grants, _, _ = case
    editor = service.bound.editor
    context = await editor.context_for_session(await grants.lookup_session(editor_token))
    workspace = editor.workspace_registry.get(context.scope['threadId']).root
    _, materials = _inputs(workspace)
    sheets = deepcopy(list(materials.sheets))
    sheets[0]['rows'][1][1] = {'value': 1234.56, 'style': {'bold': True}}
    sheets[0]['rows'][4][1]['style'] = {'fontColor': '#334455'}
    if scenario == 'date':
        sheets[0]['rows'][5][1]['value'] = '1900-02-28'
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
        if scenario == 'namespace':
            def foreign_date(node):
                node.find('.//{*}c[@r="B6"]/{*}v').tag = '{urn:foreign}v'
            target.write_bytes(changed_package(target.read_bytes(), foreign_date, part='xl/worksheets/sheet1.xml'))
        elif scenario != 'configured':
            changes = {'format': {'number_format': True}, 'value': {'raw_value': '1234.57'},
                'cache': {'raw_value': '1000.01'}, 'date': {'raw_value': '60'}}
            address = {'cache': 'B4', 'date': 'B6'}.get(scenario, 'B2')
            target.write_bytes(_mutate(target.read_bytes(), address, **changes[scenario]))
        return issues

    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', actual_xlsx)
    monkeypatch.setattr(preference_preflight, '_generate', generate)
    before = executor_manifest()
    payload = await run(active)
    assert payload['bindingValid'] is True and payload['canApply'] is False
    entry = payload['formats']['xlsx']
    assert entry['artifact'] is not None
    assert entry['readback']['status'] == ('passed' if scenario == 'configured' else 'failed')
    if scenario != 'configured':
        failures = [c for c in entry['readback']['checks'] if not c['passed']]
        expected_path = 'xlsx.numbers.decimalPlaces' if scenario == 'format' else None
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
    assert book['业务数据']['B2'].value == (1234.57 if scenario == 'value' else 1234.56)
    assert book['业务数据']['B4'].value == '=SUM(B2:B3)'
    assert load_workbook(BytesIO(content), data_only=True)['业务数据']['B4'].value == (1000.01 if scenario == 'cache' else 1000)
    prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
        expected_hash=draft['contentHash'], evidence_ids=[payload['verificationReceipt']['id']])
    assert prepared['status'] == 'incomplete' and prepared['canApply'] is False
    assert record['executorManifest'] == before == executor_manifest()
    directory = OUTPUT / ('sql-' + scenario)
    directory.mkdir()
    (directory / 'actual.xlsx').write_bytes(content)
    (directory / 'inputs.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2))
    (directory / 'result.json').write_text(json.dumps({
        'scope': 'real_xlsx_http_sql_with_synthetic_business_and_workflow',
        'artifact': {'sizeBytes': len(content), 'sha256': sha256(content).hexdigest()},
        'executorManifestHash': configuration_hash(before), 'executorManifest': before,
        'readback': entry['readback'], 'prepared': prepared,
        'independentSqlStreamMatchesReturnedBytes': True,
        'boundary': '不新增字段mapper，不证明完整场景/视觉/生命周期或完整生产批准。',
    }, ensure_ascii=False, indent=2))
