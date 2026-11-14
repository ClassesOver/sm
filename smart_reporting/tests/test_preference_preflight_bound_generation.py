"""真实授权类/工作区/绑定器与正式生成器集成；账号和状态持久层使用内存夹具。"""
import base64
import hashlib
import json
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from pptx import Presentation

from smart_reporting.report_editor.service import ReportEditorContext
from smart_reporting.reporting.delivery.pptx import build_editable_pptx
from smart_reporting.reporting.delivery.xlsx import build_workbook
from smart_reporting.tests.test_preference_preflight import _inputs
from smart_reporting.tests.test_preference_report_preflight import bound_case, native_case


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def _register(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {'path': path, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}


@pytest.mark.anyio
async def test_bound_native_workbook_replays_verified_spec_with_real_authorization_and_generators(tmp_path):
    service, args, _, repository, context, root, _ = await bound_case(tmp_path)
    _, materials = _inputs(root)
    document = context.job['_documentContext']
    mapping = {'cells': [{'sheetName': '业务数据', 'cell': 'B2', 'sourcePath': 'report.md',
        'exactValue': 1234.56}], 'snapshotId': 'server-bound-native-source'}
    spec = {'title': document['title'], 'period': document['periodLabel'],
        'generatedDate': document['generatedDate'], 'sheets': list(materials.sheets), 'sourceMapping': mapping}
    path = 'native/report.xlsx'
    original = build_workbook(output_path=root / path, title=spec['title'], period=spec['period'],
        generated_date=spec['generatedDate'], sheets=tuple(spec['sheets']), source_mapping=mapping)
    artifact = {'path': path, 'size': original.size, 'sha256': original.sha256}
    spec_bytes = json.dumps(spec, ensure_ascii=False, sort_keys=True).encode()
    spec_identity = _register(root, 'native/workbook-spec-' + hashlib.sha256(spec_bytes).hexdigest() + '.json', spec_bytes)
    receipt = {'artifact': artifact, 'spec': spec_identity}
    receipt_identity = _register(root, 'native/report.xlsx.receipt.json', json.dumps(receipt).encode())
    job = deepcopy(context.job)
    job.pop('_documentContext')  # 原生修订只允许从已登记spec恢复真实公共上下文。
    native = ReportEditorContext.model_validate({**context.model_dump(by_alias=True), 'job': job,
        'deliveryFormat': 'xlsx', 'xlsxPath': path, 'xlsxSize': original.size, 'xlsxSha256': original.sha256})
    repository.state.payload['reportEditorContexts']['1'] = native.model_dump(mode='json', by_alias=True)
    repository.state.payload['workflowCheckpoint'] = {'files': [spec_identity, receipt_identity]}
    grant, _ = await service.grants.issue(native)
    args['editor_session'], _ = await service.grants.exchange(grant)
    args['expected_context_hash'] = native.digest()

    result = await service.run(**args)

    assert result['binding']['valid'] is True and result['binding']['artifactAccessAuthorized'] is True
    assert result['status'] == 'incomplete' and result['canApply'] is False
    item = result['formats']['xlsx']
    assert item['availability'] == 'available' and item['readback']['status'] == 'passed'
    output = item['artifact']
    content = base64.b64decode(output['base64'], validate=True)
    assert len(content) == output['size'] > 0
    assert hashlib.sha256(content).hexdigest() == output['sha256']
    book = load_workbook(BytesIO(content))
    assert book['业务数据']['B2'].value == 1234.56
    assert book['业务数据']['B4'].value == '=SUM(B2:B3)'
    assert book['业务数据']['B2'].font.sz == 13
    with ZipFile(BytesIO(content)) as package:
        embedded = json.loads(package.read('smart-reporting/source-mapping.json'))
    assert embedded['sources'] == mapping
    assert embedded['title'] == '月度业务核对' and embedded['period'] == '2026年10月'
    assert result['binding']['nativeSources']['xlsx']['sourceMapping'] == mapping
    for format in ('md', 'pdf', 'word', 'pptx'):
        assert result['formats'][format]['availability'] == 'unavailable'
        assert result['formats'][format]['artifact'] is None
    destination = tmp_path / 'verified-native.xlsx'
    destination.write_bytes(content)
    evidence = {'fixtureOnly': True,
        'realComponents': ['ReportEditorGrantService', 'ReportEditorService', 'ReportingWorkspaceRegistry',
            'ReportingWorkspaceRouter', 'BoundPreferencePreflightService', 'run_preference_preflight', 'build_workbook'],
        'fixtureComponents': ['management authentication/preferences', 'in-memory workflow state repository'],
        'nativeFile': str(destination), 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
        'bindingHash': result['binding']['bindingHash'], 'materialHash': result['materialHash'],
        'bindingValid': result['binding']['valid'], 'readbackStatus': item['readback']['status'],
        'status': result['status'], 'canApply': result['canApply'], 'sourceMapping': embedded['sources']}
    (tmp_path / 'verified-native-identity.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))


@pytest.mark.anyio
async def test_bound_native_slides_replay_verified_initial_spec_with_real_authorization_and_generators(tmp_path):
    service, args, repository, context, root, spec, spec_identity, _ = await native_case(tmp_path, 'pptx')
    slides = deepcopy(spec['slides'])
    for slide in slides:
        if 'chartPath' in slide:
            slide['chartPath'] = str(root / slide['chartPath'])
    path = 'report.pptx'
    original = build_editable_pptx(output_path=root / path, title=spec['title'], period=spec['period'],
        theme='executive', slides=tuple(slides), generated_date=spec['generatedDate'])
    source_content = (root / path).read_bytes()
    assert len(Presentation(BytesIO(source_content)).slides) > 0
    artifact = {'path': path, 'size': original.size, 'sha256': original.sha256}
    binding = spec['binding']
    receipt = {'schemaVersion': 'pptx-native-receipt/1', 'binding': binding,
        'artifact': artifact, 'spec': spec_identity}
    receipt_identity = _register(root, 'report.pptx.receipt.json', json.dumps(receipt).encode())
    job = deepcopy(context.job)
    job['pptxNativeInput'] = {'binding': binding, 'artifact': artifact, 'spec': spec_identity, 'receipt': receipt_identity}
    native = ReportEditorContext.model_validate({**context.model_dump(by_alias=True), 'job': job,
        'pptxSize': original.size, 'pptxSha256': original.sha256})
    repository.state.payload['reportEditorContexts']['1'] = native.model_dump(mode='json', by_alias=True)
    repository.state.payload['artifacts'] = [artifact, spec_identity, receipt_identity]
    grant, _ = await service.grants.issue(native)
    args['editor_session'], _ = await service.grants.exchange(grant)
    args['expected_context_hash'] = native.digest()

    result = await service.run(**args)

    assert result['binding']['valid'] is True and result['binding']['artifactAccessAuthorized'] is True
    assert result['status'] == 'incomplete' and result['canApply'] is False
    item = result['formats']['pptx']
    assert item['availability'] == 'available' and item['readback']['status'] == 'passed'
    output = item['artifact']
    content = base64.b64decode(output['base64'], validate=True)
    assert len(content) == output['size'] > 0
    assert hashlib.sha256(content).hexdigest() == output['sha256']
    deck = Presentation(BytesIO(content))
    text = '\n'.join(shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
    assert '冻结业务原值 1234.56' in text and '月度业务核对' in text and '图 1 收支趋势' in text
    for format in ('md', 'pdf', 'word', 'xlsx'):
        assert result['formats'][format]['availability'] == 'unavailable'
        assert result['formats'][format]['artifact'] is None
    assert result['binding']['nativeSources']['pptx']['artifact'] == artifact
    destination = tmp_path / 'verified-native.pptx'
    destination.write_bytes(content)
    evidence = {'fixtureOnly': True,
        'realComponents': ['ReportEditorGrantService', 'ReportEditorService', 'ReportingWorkspaceRegistry',
            'ReportingWorkspaceRouter', 'BoundPreferencePreflightService', 'run_preference_preflight', 'build_editable_pptx'],
        'fixtureComponents': ['management authentication/preferences', 'in-memory workflow state repository'],
        'initialNativeArtifact': artifact, 'nativeFile': str(destination),
        'size': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
        'bindingHash': result['binding']['bindingHash'], 'materialHash': result['materialHash'],
        'bindingValid': result['binding']['valid'], 'readbackStatus': item['readback']['status'],
        'status': result['status'], 'canApply': result['canApply']}
    (tmp_path / 'verified-native-identity.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))
