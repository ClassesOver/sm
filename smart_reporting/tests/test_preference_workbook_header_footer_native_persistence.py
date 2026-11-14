"""正式XLSX的原生字段证据、SQL留存和prepare边界。"""

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
from smart_reporting.preferences.models import resolve_format_preferences
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

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
OUTPUT = Path('output/system-config-preferences/xlsx-header-footer-native-evidence')
FIELDS = ('enabled', 'header.left', 'header.center', 'header.right', 'footer.left', 'footer.center',
    'footer.right', 'style.font', 'style.size', 'style.color', 'style.bold', 'headerDistance', 'footerDistance')


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('scenario', ['configured', 'tail_footer', 'disabled', 'retained_drift', 'invalid_worksheet_type'])
async def test_native_header_footer_fields_persist_only_with_current_retained_artifact(case, monkeypatch, scenario):
    service, client, _, _, path, admin, editor_token, repository, grants, _, _ = case
    editor = service.bound.editor
    context = await editor.context_for_session(await grants.lookup_session(editor_token))
    workspace = editor.workspace_registry.get(context.scope['threadId']).root
    _, materials = _inputs(workspace)
    document_context = context.job['_documentContext']
    mapping = {'datasets': {}, 'cells': [], 'claims': []}
    spec = {'title': document_context['title'], 'period': document_context['periodLabel'],
        'generatedDate': document_context['generatedDate'], 'sheets': list(materials.sheets),
        'sourceMapping': mapping}
    original_artifact = build_workbook(output_path=workspace / 'native/report.xlsx', title=spec['title'],
        period=spec['period'], generated_date=spec['generatedDate'], sheets=materials.sheets, source_mapping=mapping)
    artifact = {'path': 'native/report.xlsx', 'size': original_artifact.size, 'sha256': original_artifact.sha256}
    spec_identity = _register(workspace, 'native/header-footer-spec.json', json.dumps(spec).encode())
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
    document['xlsx']['print']['headerFooter'].update(enabled=scenario != 'disabled', headerDistance=8, footerDistance=9,
        header={'left': '{signer}', 'center': 'R&D {title}', 'right': '{date}'},
        footer={'left': '{period}', 'center': '', 'right': '{page}/{pages}'})
    document['xlsx']['print']['headerFooter']['style'].update(
        font='serif', size=14, color='#345678', bold=True)
    await service.preferences.save_draft(admin, document, draft['version'])
    draft = (await service.preferences.detail(admin))['draft']
    active = list(case)
    active[2] = {'expectedVersion': draft['version'], 'expectedHash': draft['contentHash']}
    active[6] = editor_token
    async with repository.engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    service.bound.editor.artifact_persistence = ReportArtifactPersistenceService(
        SqlAlchemyReportArtifactRepository(repository.engine), service.bound.editor.workspace)

    async def actual_xlsx(function, *args, **kwargs):
        return function(*args, **{**kwargs, 'formats': ('xlsx',)})

    original = preference_preflight._generate
    readback_input = {}

    def generate(root, preferences, frozen):
        readback_input.update(resolved=resolve_format_preferences(preferences, 'xlsx'), frozen={
            'sheets': deepcopy(frozen['sheets']), 'state': {'_documentContext': deepcopy(
                frozen['state'].get('_nativeDocumentContexts', {}).get('xlsx', frozen['state']['_documentContext']))}})
        issues = original(root, preferences, frozen)
        if scenario in ('tail_footer', 'invalid_worksheet_type'):
            target = root / 'report.xlsx'
            modified = BytesIO()
            with ZipFile(target) as source, ZipFile(modified, 'w') as output:
                for item in source.infolist():
                    data = source.read(item.filename)
                    if item.filename == 'xl/worksheets/sheet2.xml' and scenario == 'tail_footer':
                        node = ElementTree.fromstring(data)
                        footer = node.find('{*}headerFooter/{*}oddFooter')
                        assert footer is not None and footer.text
                        footer.text += '尾页损坏'
                        data = ElementTree.tostring(node, encoding='utf-8', xml_declaration=True)
                    elif item.filename == '[Content_Types].xml' and scenario == 'invalid_worksheet_type':
                        node = ElementTree.fromstring(data)
                        sheet = next(part for part in node if part.get('PartName') == '/xl/worksheets/sheet2.xml')
                        sheet.set('ContentType', 'application/xml')
                        data = ElementTree.tostring(node, encoding='utf-8', xml_declaration=True)
                    output.writestr(item, data)
            target.write_bytes(modified.getvalue())
        return issues

    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', actual_xlsx)
    monkeypatch.setattr(preference_preflight, '_generate', generate)
    before = executor_manifest()
    payload = await run(active)
    assert payload['bindingValid'] is True and payload['canApply'] is False
    assert 'verificationReceipt' in payload, payload.get('issues')
    entry = payload['formats']['xlsx']
    checks = [item for item in entry['readback']['checks']
        if (item['path'] or '').startswith('xlsx.print.headerFooter.')]
    capabilities = {item['path']: item['status'] for item in entry['capabilities']}
    failed = {'footer.right'} if scenario == 'tail_footer' else set()
    unverified = scenario == 'invalid_worksheet_type'
    for field in FIELDS:
        expected = 'not_verified' if scenario == 'disabled' and field.startswith('style.') else ('failed' if field in failed else 'verified')
        assert capabilities['xlsx.print.headerFooter.' + field] == expected
    assert entry['readback']['status'] == ('failed' if failed or unverified else 'passed')
    if failed or unverified:
        assert entry['status'] == 'failed'
        assert any(issue['code'] == 'management_preference_native_mismatch' for issue in entry['issues'])
    receipt = payload['verificationReceipt']
    async with repository.engine.connect() as connection:
        record = await connection.scalar(select(preference_verification_results.c.document).where(
            preference_verification_results.c.id == receipt['id']))
    assert record['assessment']['canApply'] is False
    reference = record['retained']['formats']['xlsx']['artifact']
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
    assert content == base64.b64decode(entry['artifact']['base64'], validate=True)
    assert len(content) == reference['size'] == entry['artifact']['size']
    assert sha256(content).hexdigest() == reference['sha256'] == entry['artifact']['sha256']
    book = load_workbook(BytesIO(content), data_only=True)
    assert book.sheetnames == ['业务数据', '说明']
    assert book['业务数据']['B4'].value == 1000
    assert (book['说明'].oddFooter.right.text or '') == ('' if scenario == 'disabled' else '&P/&N' + ('尾页损坏' if failed else ''))
    rows = [row for row in record['evidence'] if row.get('readerGroup') == 'xlsx_native_header_footer_fields_v1']
    expected_fields = {field for field in FIELDS if scenario != 'disabled' or not field.startswith('style.')}
    if unverified:
        expected_fields = set()
    assert {row['path'] for row in rows} == {'xlsx.print.headerFooter.' + field for field in expected_fields}
    assert len(rows) == len(expected_fields)
    assert {row['path'] for row in rows if row['status'] == 'failed'} == {'xlsx.print.headerFooter.' + field for field in failed}
    assert all(row['dimension'] == 'native' and row['scenario'] == 'configured_field'
        and row['artifact'] == {'sizeBytes': len(content), 'sha256': sha256(content).hexdigest()} for row in rows)
    prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
        expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
    assert prepared['status'] == 'incomplete' and prepared['canApply'] is False
    field_gaps = [gap for gap in prepared['missingRequirements']
        if gap.get('scenario') == 'configured_field' and gap.get('path', '').startswith('xlsx.print.headerFooter.')
        and gap['path'].removeprefix('xlsx.print.headerFooter.') in FIELDS]
    expected_gaps = failed | ({field for field in FIELDS if field.startswith('style.')} if scenario == 'disabled' else set())
    if unverified:
        expected_gaps = set(FIELDS)
    assert {gap['path'] for gap in field_gaps} == {'xlsx.print.headerFooter.' + field for field in expected_gaps}
    drift_code = None
    if scenario == 'retained_drift':
        async with repository.engine.begin() as connection:
            await connection.execute(update(report_artifact_chunks_v1).where(
                report_artifact_chunks_v1.c.artifact_key == reference['artifactKey'],
                report_artifact_chunks_v1.c.chunk_index == 0).values(content=b'changed-header-footer-retention'))
        with pytest.raises(ManagementError) as changed:
            await service.evidence.prepare(admin, expected_version=draft['version'],
                expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
        drift_code = changed.value.code
        assert drift_code == 'management_preference_retained_artifact_changed'
        # 已返回的真实原件仍可独立读取；损坏的留存不能用于新批准。
        assert base64.b64decode(entry['artifact']['base64'], validate=True) == content
    assert record['executorManifest'] == before == executor_manifest()
    directory = OUTPUT / scenario
    directory.mkdir()
    (directory / 'actual.xlsx').write_bytes(content)
    (directory / 'readback-input.json').write_text(json.dumps(readback_input, ensure_ascii=False, indent=2))
    if entry.get('pdf'):
        (directory / 'preview.pdf').write_bytes(base64.b64decode(entry['pdf']['base64'], validate=True))
    (directory / 'readback.json').write_text(json.dumps({
        'scope': 'real_xlsx_http_sql_retention_with_synthetic_business_and_workflow',
        'artifact': {'sizeBytes': len(content), 'sha256': sha256(content).hexdigest()},
        'executorManifestHash': configuration_hash(before), 'executorStableWithinScenario': True,
        'readbackStatus': entry['readback']['status'], 'formatStatus': entry['status'],
        'checks': checks, 'capabilities': {field: capabilities['xlsx.print.headerFooter.' + field] for field in FIELDS},
        'assessmentCanApply': record['assessment']['canApply'], 'canApply': payload['canApply'],
        'formulaCachePreserved': True, 'independentSqlStreamMatchesReturnedBytes': True,
        'nativeEvidence': rows, 'prepared': prepared, 'retainedDriftRejected': drift_code,
        'boundary': '仅configured_field/native；无视觉、生命周期或完整批准；预览非SQL独立流读。',
    }, ensure_ascii=False, indent=2))
