"""服务端显式选择实际可用格式，不用缺失材料阻断其他原生产物。"""
import base64
import hashlib
import json
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

from smart_reporting.management.models import ManagementError
from smart_reporting.tests.test_preference_preflight import _inputs, _run


def _identity(item):
    artifact = item['artifact']
    content = base64.b64decode(artifact['base64'], validate=True)
    assert artifact['size'] == len(content) > 0
    assert artifact['sha256'] == hashlib.sha256(content).hexdigest()
    return content


def _unavailable(item):
    assert item['availability'] == 'unavailable'
    assert item['status'] == 'incomplete'
    assert item['artifact'] is None and item['pdf'] is None
    assert item['readback'] == {'status': 'unavailable', 'checks': []}
    assert item['issues'] and all(value['status'] == 'unavailable' for value in item['capabilities'])


@pytest.fixture(scope='module')
def workbook_preflight(tmp_path_factory):
    draft, materials = _inputs(tmp_path_factory.mktemp('preflight-partial-workbook'))
    materials = replace(materials, slides=())
    return draft, materials, _run(draft, materials, formats=('md', 'xlsx'))


def test_explicit_formats_generate_real_markdown_and_workbook_without_slides(workbook_preflight):
    _, _, result = workbook_preflight
    assert set(result['formats']) == {'md', 'pdf', 'word', 'xlsx', 'pptx'}
    assert result['status'] == 'incomplete' and result['canApply'] is False
    for format in ('md', 'xlsx'):
        assert result['formats'][format]['availability'] == 'available'
        assert result['formats'][format]['readback']['status'] == 'passed'
    assert '冻结业务原值 1234.56' in _identity(result['formats']['md']).decode()
    book = load_workbook(BytesIO(_identity(result['formats']['xlsx'])))
    assert book['业务数据']['B2'].value == 1234.56
    assert book['业务数据']['B4'].value == '=SUM(B2:B3)'
    for format in ('pdf', 'word', 'pptx'):
        _unavailable(result['formats'][format])


def test_missing_selected_native_inputs_do_not_generate_empty_slides_or_workbook(tmp_path, monkeypatch):
    from smart_reporting.management import preference_preflight as module

    draft, materials = _inputs(tmp_path)
    materials = replace(materials, sheets=(), slides=())
    def forbidden(*args, **kwargs):
        pytest.fail('缺少正式材料的格式不得调用生成器')
    monkeypatch.setattr(module, 'build_workbook', forbidden)
    monkeypatch.setattr(module, 'build_editable_pptx', forbidden)
    monkeypatch.setattr(module.ReportRuntime, 'render_markdown', forbidden)
    result = _run(draft, materials, formats=('md', 'xlsx', 'pptx'))
    assert _identity(result['formats']['md'])
    for format in ('pdf', 'word', 'xlsx', 'pptx'):
        _unavailable(result['formats'][format])
    assert result['canApply'] is False


def test_document_formats_use_real_materials_without_workbook_or_slides(tmp_path, monkeypatch):
    from smart_reporting.management import preference_preflight as module

    draft, materials = _inputs(tmp_path)
    materials = replace(materials, sheets=(), slides=())
    def forbidden(*args, **kwargs):
        pytest.fail('未选择的格式不得调用生成器')
    monkeypatch.setattr(module, 'build_workbook', forbidden)
    monkeypatch.setattr(module, 'build_editable_pptx', forbidden)
    result = _run(draft, materials, formats=('pdf', 'word'))
    word = Document(BytesIO(_identity(result['formats']['word'])))
    pdf = PdfReader(BytesIO(_identity(result['formats']['pdf'])))
    assert any('1234.56' in cell.text for table in word.tables for row in table.rows for cell in row.cells)
    assert '1234.56' in ''.join(page.extract_text() for page in pdf.pages)
    for format in ('md', 'xlsx', 'pptx'):
        _unavailable(result['formats'][format])


def test_partial_generation_receipt_failure_retains_actual_selected_files(workbook_preflight, monkeypatch):
    from smart_reporting.management import preference_preflight as module

    draft, materials, baseline = workbook_preflight
    def fail_after_write(root, preferences, frozen):
        for format in ('md', 'xlsx'):
            (root / ('report.' + format)).write_bytes(_identity(baseline['formats'][format]))
        raise RuntimeError('private generation details')
    monkeypatch.setattr(module, '_generate', fail_after_write)
    result = _run(draft, materials, formats=('md', 'xlsx'))
    for format in ('md', 'xlsx'):
        assert _identity(result['formats'][format])
        assert result['formats'][format]['status'] == 'failed'
    for format in ('pdf', 'word', 'pptx'):
        _unavailable(result['formats'][format])
    assert result['canApply'] is False and 'private generation details' not in str(result)


def test_legacy_materials_still_require_complete_native_inputs(tmp_path):
    draft, materials = _inputs(tmp_path)
    with pytest.raises(ManagementError) as caught:
        _run(draft, replace(materials, slides=()))
    assert caught.value.code == 'management_preference_materials_invalid'


@pytest.mark.parametrize('change', ['bytes', 'outside', 'symlink'])
def test_partial_formats_preserve_source_and_static_image_identity_checks(tmp_path, change):
    draft, materials = _inputs(tmp_path)
    if change == 'bytes':
        (tmp_path / 'chart.png').write_bytes(b'changed')
    elif change == 'outside':
        materials.slides[0]['chartPath'] = '../foreign.png'
    else:
        (tmp_path / 'chart.png').unlink()
        (tmp_path / 'chart.png').symlink_to('/etc/hosts')
    with pytest.raises(ManagementError) as caught:
        _run(draft, materials, formats=('md',))
    assert caught.value.code == 'management_preference_materials_invalid'


def test_partial_preflight_rejects_unknown_formats_before_generation(tmp_path):
    draft, materials = _inputs(tmp_path)
    with pytest.raises(ManagementError) as caught:
        _run(draft, materials, formats=('html',))
    assert caught.value.code == 'management_preference_formats_invalid'


def test_explicit_empty_formats_return_unavailable_without_running_generators(tmp_path, monkeypatch):
    from smart_reporting.management import preference_preflight as module

    draft, materials = _inputs(tmp_path)
    materials = replace(materials, sheets=(), slides=())
    def forbidden(*args, **kwargs):
        pytest.fail('空选择不得运行正式生成器')
    monkeypatch.setattr(module, 'build_workbook', forbidden)
    monkeypatch.setattr(module, 'build_editable_pptx', forbidden)
    monkeypatch.setattr(module.ReportRuntime, 'render_markdown', forbidden)
    result = _run(draft, materials, formats=())
    assert result['status'] == 'incomplete' and result['canApply'] is False
    for item in result['formats'].values():
        _unavailable(item)


def test_unselected_physical_output_is_not_returned_or_read_back(tmp_path, monkeypatch):
    from smart_reporting.management import preference_preflight as module

    draft, materials = _inputs(tmp_path)
    def additional_output(root, preferences, frozen):
        (root / 'report.md').write_text('已选择的实际输出', encoding='utf-8')
        (root / 'report.pdf').write_bytes(b'unselected physical output')
        return {format: [] for format in module.FORMATS}
    original = module._readback
    def selected_readback(content, format, resolved, frozen):
        assert format == 'md', '未选择的物理产物不得进入回读'
        return original(content, format, resolved, frozen)
    monkeypatch.setattr(module, '_generate', additional_output)
    monkeypatch.setattr(module, '_readback', selected_readback)
    result = _run(draft, materials, formats=('md',))
    assert _identity(result['formats']['md']).decode() == '已选择的实际输出'
    _unavailable(result['formats']['pdf'])


def test_native_workbook_consumes_frozen_source_mapping_without_document_only_context(tmp_path):
    from smart_reporting.management.preference_preflight import _generate, _verify_materials
    from smart_reporting.management.preference_preflight_readback import readback
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences

    draft, materials = _inputs(tmp_path)
    state = dict(materials.state)
    state['_documentContext'] = {key: state['_documentContext'][key]
        for key in ('title', 'periodLabel', 'generatedDate')}
    mapping = {'cells': [{'sheetName': '业务数据', 'cell': 'B2', 'exactValue': 1234.56,
        'datasetId': 'business-source'}], 'snapshotId': 'frozen-native-input'}
    state['_workbookSourceMapping'] = mapping
    materials = replace(materials, state=state, slides=())
    _, frozen, first_hash = _verify_materials(materials, formats=('xlsx',))
    preferences = FormatPreferences.model_validate(draft['document'])
    issues = _generate(tmp_path, preferences, frozen)
    assert issues['xlsx'] == []
    content = (tmp_path / 'report.xlsx').read_bytes()
    with ZipFile(BytesIO(content)) as package:
        embedded = json.loads(package.read('smart-reporting/source-mapping.json'))
    assert embedded['sources'] == mapping
    evidence = readback(content, 'xlsx', resolve_format_preferences(preferences, 'xlsx'), frozen)
    assert evidence['status'] == 'passed'
    state['_workbookSourceMapping'] = {**mapping, 'snapshotId': 'changed-native-input'}
    _, _, changed_hash = _verify_materials(replace(materials, state=state), formats=('xlsx',))
    assert changed_hash != first_hash


def test_native_workbook_uses_its_frozen_title_period_and_date_while_markdown_keeps_document_context(tmp_path):
    from smart_reporting.management.preference_preflight import _verify_materials

    draft, materials = _inputs(tmp_path)
    native = {'title': '已登记工作簿专用标题', 'periodLabel': '2026-10', 'generatedDate': '2026-11-12'}
    mapping = {'cells': [{'sheetName': '业务数据', 'cell': 'B2', 'exactValue': 1234.56}],
        'snapshotId': 'different-native-context'}
    state = {**materials.state, '_nativeDocumentContexts': {'xlsx': native}, '_workbookSourceMapping': mapping}
    materials = replace(materials, state=state, slides=())
    _, _, original_hash = _verify_materials(materials, formats=('md', 'xlsx'))
    result = _run(draft, materials, formats=('md', 'xlsx'))
    workbook = result['formats']['xlsx']
    with ZipFile(BytesIO(_identity(workbook))) as package:
        embedded = json.loads(package.read('smart-reporting/source-mapping.json'))
    assert embedded['title'] == '已登记工作簿专用标题'
    assert embedded['period'] == '2026-10'
    assert embedded['sources'] == mapping
    assert workbook['readback']['status'] == 'passed', workbook['issues']
    native_date = next(check for check in workbook['readback']['checks'] if check['path'] == 'xlsx.common.dateFormat')
    assert native_date['actual'] == '2026-11-12' and native_date['passed'] is True
    markdown = result['formats']['md']
    assert markdown['readback']['status'] == 'passed'
    markdown_date = next(check for check in markdown['readback']['checks'] if check['path'] == 'md.common.dateFormat')
    assert markdown_date['passed'] is True
    assert '2026\\-11\\-13' in _identity(markdown).decode()
    changed = {**state, '_nativeDocumentContexts': {'xlsx': {**native, 'periodLabel': '2026-09'}}}
    _, _, changed_hash = _verify_materials(replace(materials, state=changed), formats=('md', 'xlsx'))
    assert changed_hash != original_hash
