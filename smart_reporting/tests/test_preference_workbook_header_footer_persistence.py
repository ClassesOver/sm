"""正式XLSX/HTTP/SQL回读：说明页损坏不丢原件，也不能被业务页覆盖。"""

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
from sqlalchemy import select

from smart_reporting.management import preference_preflight, preference_report_preflight
from smart_reporting.management.configuration_store import configuration_hash
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
OUTPUT = Path('output/system-config-preferences/xlsx-header-footer-readback')
FIELDS = ('enabled', 'header.left', 'header.center', 'header.right', 'footer.left', 'footer.center',
    'footer.right', 'style.font', 'style.size', 'style.color', 'style.bold', 'headerDistance', 'footerDistance')


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('scenario', ['configured', 'tail_footer'])
async def test_real_xlsx_checks_signature_footer_and_retains_failed_validation_artifact(case, monkeypatch, scenario):
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
    document['xlsx']['print']['headerFooter'].update(enabled=True, headerDistance=8, footerDistance=9,
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
        if scenario == 'tail_footer':
            target = root / 'report.xlsx'
            modified = BytesIO()
            with ZipFile(target) as source, ZipFile(modified, 'w') as output:
                for item in source.infolist():
                    data = source.read(item.filename)
                    if item.filename == 'xl/worksheets/sheet2.xml':
                        node = ElementTree.fromstring(data)
                        footer = node.find('{*}headerFooter/{*}oddFooter')
                        assert footer is not None and footer.text
                        footer.text += '尾页损坏'
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
    for field in FIELDS:
        assert capabilities['xlsx.print.headerFooter.' + field] == ('failed' if field in failed else 'verified')
    assert entry['readback']['status'] == ('failed' if failed else 'passed')
    if failed:
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
    assert book['说明'].oddFooter.right.text == '&P/&N' + ('尾页损坏' if failed else '')
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
        'boundary': '无新字段mapper或视觉/生命周期批准；预览非SQL独立流读。',
    }, ensure_ascii=False, indent=2))
