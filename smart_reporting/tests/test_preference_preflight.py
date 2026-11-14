"""草稿验收绑定服务端真实材料，失败不得丢弃实际已生成的文件。"""
import base64
import hashlib
import json
from copy import copy, deepcopy
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from openpyxl import load_workbook
from PIL import Image
from pptx import Presentation
from pypdf import PdfReader

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.models import ManagementError
from smart_reporting.preferences.models import FormatPreferences


def _inputs(tmp_path):
    from smart_reporting.management.preference_preflight import PreferencePreflightMaterials

    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), '#345678').save(chart)
    source = tmp_path / 'report.md'
    source.write_text('# 月度业务核对\n\n[[section:overview]]\n## 1. 收支分析\n\n'
        '冻结业务原值 1234.56。\n\n### 1.1 差额说明\n\n正文核对。\n\n#### 1.1.1 复核说明\n\n'
        '| 指标 | 金额 |\n| --- | ---: |\n| 本期收入 | 1234.56 |\n| 本期支出 | -234.56 |\n\n'
        '- 业务清单\n\n```text\n冻结代码\n```\n\n![收支趋势](chart.png)\n\n*图表：收支趋势*\n\n'
        '![第二图](chart.png)\n\n*图表：第二图注*\n\n'
        '受控计算来源[[citation:business-source]]\n', encoding='utf-8')
    context = {'title': '月度业务核对', 'periodLabel': '2026年10月', 'organizationName': '原始组织',
        'generatedByLabel': '', 'watermarkText': '', 'generatedDate': '2026-11-13', 'sectionNumbers': ['1'],
        'sections': [{'code': 'overview', 'sectionNumber': '1', 'title': '收支分析'}],
        'headingNumbers': [{'level': 2, 'number': '1', 'title': '收支分析',
            'sectionCode': 'overview', 'anchor': 'report-section-overview'},
            {'level': 3, 'number': '1.1', 'title': '差额说明', 'sectionCode': 'overview', 'anchor': 'report-heading-h2'},
            {'level': 4, 'number': '1.1.1', 'title': '复核说明', 'sectionCode': 'overview', 'anchor': 'report-heading-h3'}]}
    sources = [{'path': item.name, 'size': item.stat().st_size,
        'sha256': hashlib.sha256(item.read_bytes()).hexdigest()} for item in (source, chart)]
    materials = PreferencePreflightMaterials(workspace=tmp_path, markdown_path='report.md',
        state={'jobId': 'preflight-business-test', 'sources': sources, '_documentContext': context,
            '_citationPresentations': [{'citationId': 'business-source', 'label': '受控收支计算', 'coverageItems': []}]},
        sheets=({'name': '业务数据', 'rows': [['项目', '金额'], ['收入', 1234.56], ['支出', -234.56],
            ['合计', {'formula': 'SUM(B2:B3)', 'value': 1000.0}],
            ['变化率', {'value': 12.5, 'valueType': 'percentPoints'}],
            ['冻结日期', {'value': '2026-10-31', 'valueType': 'date'}]]},),
        slides=({'title': '收支趋势', 'bullets': ['冻结业务原值 1234.56。'],
            'evidenceIds': ['business-source'], 'chartPath': 'chart.png'},))
    document = FormatPreferences.model_validate({'common': {'signer': '草稿验收编制', 'dateFormat': 'iso'},
        'md': {'toc': True, 'listMarker': '*', 'codeFence': 'tildes'},
        'xlsx': {'body': {'size': 13}, 'numbers': {'decimalPlaces': 3}},
        'pptx': {'typography': {'caption': {'size': 14, 'color': '#345678', 'bold': True}}},
        'word': {'cover': False, 'toc': False, 'sources': True, 'typography': {'body': {'size': 12}}},
        'pdf': {'cover': False, 'toc': False, 'sources': True, 'typography': {'body': {'size': 13}}},
    }).model_dump(mode='json', by_alias=True)
    return {'version': 7, 'contentHash': configuration_hash(document), 'document': document}, materials


def _run(draft, materials, **kwargs):
    from smart_reporting.management.preference_preflight import run_preference_preflight

    return run_preference_preflight(draft, materials, expected_version=7,
        expected_content_hash=draft['contentHash'], **kwargs)


@pytest.mark.parametrize('change', ['version', 'hash', 'document'])
def test_preflight_rejects_stale_or_corrupt_draft_before_any_generation(tmp_path, monkeypatch, change):
    from smart_reporting.management import preference_preflight as module

    draft, materials = _inputs(tmp_path)
    monkeypatch.setattr(module, '_generate', lambda *args: pytest.fail('身份校验前不得生成'))
    if change == 'version':
        draft['version'] = 8
    elif change == 'hash':
        draft['contentHash'] = '0' * 64
    else:
        draft['document']['common']['signer'] = '篡改'
    with pytest.raises(ManagementError):
        _run(draft, materials)


@pytest.mark.parametrize('change', ['bytes', 'outside', 'symlink'])
def test_preflight_rejects_unregistered_or_changed_materials(tmp_path, change):
    draft, materials = _inputs(tmp_path)
    if change == 'bytes':
        (tmp_path / 'chart.png').write_bytes(b'changed')
    elif change == 'outside':
        materials.slides[0]['chartPath'] = '../foreign.png'
    else:
        (tmp_path / 'chart.png').unlink()
        (tmp_path / 'chart.png').symlink_to('/etc/hosts')
    with pytest.raises(ManagementError) as caught:
        _run(draft, materials)
    assert caught.value.code == 'management_preference_materials_invalid'


@pytest.fixture(scope='module')
def actual_preflight(tmp_path_factory):
    root = tmp_path_factory.mktemp('preference-preflight')
    draft, materials = _inputs(root)
    before = deepcopy(draft), deepcopy(materials.state)
    result = _run(draft, materials)
    assert (draft, materials.state) == before
    evidence = Path('output/system-config-preferences/preference-preflight')
    evidence.mkdir(exist_ok=True)
    (evidence / 'run.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for format, item in result['formats'].items():
        if item['artifact']:
            (evidence / item['artifact']['filename']).write_bytes(base64.b64decode(item['artifact']['base64']))
    return draft, materials, result


def test_preflight_generates_and_independently_reads_five_real_formats(actual_preflight):
    draft, materials, result = actual_preflight
    assert result['draftVersion'] == 7 and result['contentHash'] == draft['contentHash']
    assert result['materialHash'] and result['scope'] == 'server_bound_report_materials'
    assert set(result['formats']) == {'md', 'xlsx', 'pptx', 'pdf', 'word'}
    evidence = Path('output/system-config-preferences/preference-preflight')
    evidence.mkdir(exist_ok=True)
    for format, item in result['formats'].items():
        assert item['artifact'], item['issues']
        artifact = item['artifact']
        content = base64.b64decode(artifact['base64'], validate=True)
        assert artifact['size'] == len(content)
        assert artifact['sha256'] == hashlib.sha256(content).hexdigest()
        assert item['readback']['status'] == 'passed', item
        assert item['capabilities'] and any(value['status'] == 'verified' for value in item['capabilities'])
        (evidence / artifact['filename']).write_bytes(content)
        if item['pdf']:
            (evidence / (format + '-preview.pdf')).write_bytes(base64.b64decode(item['pdf']['base64']))
        if format == 'md':
            text = content.decode()
            assert '1234.56' in text and '* 业务清单' in text and '~~~text' in text
        elif format == 'xlsx':
            book = load_workbook(BytesIO(content))
            assert book['业务数据']['B2'].value == 1234.56
            assert book['业务数据']['B4'].value == '=SUM(B2:B3)'
            assert book['业务数据']['B2'].font.sz == 13
            assert book['业务数据']['B2'].number_format == '#,##0.000;-#,##0.000'
        elif format == 'pptx':
            deck = Presentation(BytesIO(content))
            assert any(shape.has_text_frame and shape.text == '图 1 收支趋势'
                for slide in deck.slides for shape in slide.shapes)
        elif format == 'word':
            doc = Document(BytesIO(content))
            assert doc.styles['Normal'].font.size.pt == 12
            assert len(doc.inline_shapes) == 2 and doc.tables
        else:
            assert '1234.56' in ''.join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
    # 完整草稿仍有未消费/未独立核验字段，五格式生成成功不能伪装为可应用。
    assert result['canApply'] is False and result['status'] == 'incomplete'
    for format in ('pptx', 'word', 'pdf'):
        assert any(item['path'] == format + '.charts.imageDpi' and item['status'] == 'verified'
            for item in result['formats'][format]['capabilities'])
        from smart_reporting.management.preference_preflight_readback import (
            CHART_IMAGE_DPI_EVIDENCE,
        )

        dpi_check = next(item for item in result['formats'][format]['readback']['checks']
            if item['path'] == format + '.charts.imageDpi')
        dpi_objects = dpi_check['evidenceObjects']
        assert dpi_check['evidenceKind'] == CHART_IMAGE_DPI_EVIDENCE
        assert dpi_check['coverage'] == 'complete'
        assert dpi_objects['expectedImages'] == dpi_objects['readImages'] == len(dpi_objects['images']) > 0
        assert all(len(image['mediaSha256']) == 64 and
            max(image['effectiveDpi'].values()) <= dpi_objects['targetDpi'] + .05
            for image in dpi_objects['images'])
    assert any(item['path'] == 'word.charts.captionNumbering' and item['status'] == 'verified'
        for item in result['formats']['word']['capabilities'])
    assert materials.state['sources'][0]['sha256'] == hashlib.sha256((materials.workspace / 'report.md').read_bytes()).hexdigest()


def test_actual_preflight_dpi_readback_maps_to_three_bound_native_evidence_rows(actual_preflight):
    from smart_reporting.management.preference_native_evidence import (
        map_native_chart_image_dpi_evidence,
    )
    from smart_reporting.preferences.approval_contract import (
        approval_contract,
        approval_contract_hash,
        evaluate_required_coverage,
    )

    _draft, _materials, result = actual_preflight
    assert result['canApply'] is False
    contract = approval_contract()
    binding = {'draftVersion': result['draftVersion'], 'draftHash': result['contentHash'],
        'contractHash': approval_contract_hash(contract), 'executorManifestHash': 'b' * 64}
    result = {**result, 'binding': {'valid': True, 'artifactAccessAuthorized': True}}
    retained = {'issues': [], 'formats': {
        format: {'artifact': {'size': item['artifact']['size'], 'sha256': item['artifact']['sha256']}}
        for format, item in result['formats'].items() if item.get('artifact')}}

    evidence = map_native_chart_image_dpi_evidence(result, contract, binding, retained)
    dpi_evidence = [row for row in evidence if row['path'].endswith('.charts.imageDpi')]

    assert {row['format'] for row in dpi_evidence} == {'pdf', 'word', 'pptx'}
    assert all(row['status'] == 'passed' and row['objectScope'] == 'complete' for row in dpi_evidence)
    gaps = evaluate_required_coverage({**contract, 'expectedBinding': binding}, evidence)
    assert gaps


def test_preflight_generator_failure_keeps_real_native_bytes_and_other_formats(actual_preflight, monkeypatch):
    from smart_reporting.management import preference_preflight as module

    draft, materials, baseline = actual_preflight
    def fail_after_write(root, preferences, frozen):
        for format, item in baseline['formats'].items():
            (root / ('report.docx' if format == 'word' else 'report.' + format)).write_bytes(
                base64.b64decode(item['artifact']['base64']))
        return {format: [{'code': 'injected_post_write_failure', 'message': '写入完成后回执失败'}]
            if format == 'xlsx' else [] for format in baseline['formats']}
    monkeypatch.setattr(module, '_generate', fail_after_write)
    result = _run(draft, materials)
    assert result['formats']['xlsx']['artifact']['sha256'] == baseline['formats']['xlsx']['artifact']['sha256']
    assert result['formats']['xlsx']['status'] == 'failed'
    assert result['formats']['word']['artifact'] and result['formats']['pdf']['artifact']
    assert any(item['code'] == 'injected_post_write_failure' for item in result['formats']['xlsx']['issues'])
    assert result['canApply'] is False


def test_preflight_readback_failure_preserves_identity_and_conversion_failure_keeps_native(actual_preflight, monkeypatch):
    from smart_reporting.management import preference_preflight as module

    draft, materials, baseline = actual_preflight
    def existing(root, preferences, frozen):
        for format, item in baseline['formats'].items():
            (root / ('report.docx' if format == 'word' else 'report.' + format)).write_bytes(
                base64.b64decode(item['artifact']['base64']))
        return {format: [] for format in baseline['formats']}
    def broken(*args, **kwargs):
        raise RuntimeError('private secret details')
    monkeypatch.setattr(module, '_generate', existing)
    monkeypatch.setattr(module, '_readback', broken)
    monkeypatch.setattr(module, 'libreoffice_to_pdf', broken)
    result = _run(draft, materials)
    assert all(item['artifact'] for item in result['formats'].values())
    assert all(item['readback']['status'] == 'failed' for item in result['formats'].values())
    assert result['formats']['xlsx']['pdf'] is None
    assert 'private secret details' not in str(result)
    assert result['canApply'] is False


def test_preflight_unexpected_post_write_failure_still_collects_actual_file(tmp_path, monkeypatch):
    from smart_reporting.management import preference_preflight as module

    draft, materials = _inputs(tmp_path)
    def partial(root, preferences, frozen):
        (root / 'report.md').write_text('实际已写出的报告', encoding='utf-8')
        raise OSError('private filesystem details')
    monkeypatch.setattr(module, '_generate', partial)
    result = _run(draft, materials)
    artifact = result['formats']['md']['artifact']
    assert base64.b64decode(artifact['base64']).decode() == '实际已写出的报告'
    assert result['formats']['md']['status'] == 'failed'
    assert result['status'] == 'failed' and result['canApply'] is False
    assert 'private filesystem details' not in str(result)


def test_preflight_material_changed_during_generation_keeps_output_but_invalidates_receipt(tmp_path, monkeypatch):
    from smart_reporting.management import preference_preflight as module

    draft, materials = _inputs(tmp_path)
    def mutate(root, preferences, frozen):
        (root / 'report.md').write_text('已读取冻结材料后生成', encoding='utf-8')
        (materials.workspace / 'chart.png').write_bytes(b'changed during generation')
        return {format: [] for format in module.FORMATS}
    monkeypatch.setattr(module, '_generate', mutate)
    result = _run(draft, materials)
    assert result['formats']['md']['artifact']
    assert all(any(issue['code'] == 'management_preference_materials_changed' for issue in item['issues'])
        for item in result['formats'].values())
    assert result['canApply'] is False


def test_capabilities_enumerates_every_field_and_does_not_approve_future_or_unexercised_options(tmp_path):
    from smart_reporting.management.preference_preflight import _capabilities
    from smart_reporting.preferences.models import resolve_format_preferences

    draft, materials = _inputs(tmp_path)
    resolved = resolve_format_preferences(FormatPreferences.model_validate(draft['document']), 'pptx')
    resolved['futureCapability'] = True
    frozen = {'slides': ({'title': '无图正文', 'bullets': []},), 'markdown': '# 无列表正文'}
    capabilities = _capabilities('pptx', resolved, {'checks': []}, frozen)
    by_path = {item['path']: item for item in capabilities}
    assert by_path['pptx.futureCapability']['status'] == 'not_verified'
    assert by_path['pptx.charts.captionNumbering']['status'] == 'not_exercised'
    assert by_path['pptx.typography.caption.size']['status'] == 'not_exercised'
    assert by_path['pptx.charts.imageDpi']['status'] == 'not_exercised'
    assert not any(item['status'] == 'verified' for item in capabilities)


@pytest.mark.parametrize(('passed', 'coverage', 'expected'), [
    (True, 'sample', 'not_verified'), (False, 'sample', 'failed'),
    (True, None, 'not_verified'), (True, 'complete', 'verified')])
def test_capabilities_does_not_promote_sample_evidence_or_hide_sample_failure(passed, coverage, expected):
    from smart_reporting.management.preference_preflight import _capabilities

    checks = [{'path': 'xlsx.body.size', 'passed': passed, 'coverage': coverage,
        'message': '首个正文单元格回读。'}]
    result = _capabilities('xlsx', {'body': {'size': 13}}, {'checks': checks}, {})
    assert result[0]['status'] == expected


@pytest.mark.parametrize('format', ['xlsx', 'pptx'])
def test_preflight_sample_does_not_verify_tampered_second_cell_or_second_slide(actual_preflight, format):
    from smart_reporting.management.preference_preflight import _capabilities, _verify_materials
    from smart_reporting.management.preference_preflight_readback import readback
    from smart_reporting.preferences.models import resolve_format_preferences

    draft, materials, baseline = actual_preflight
    content = base64.b64decode(baseline['formats'][format]['artifact']['base64'])
    output = BytesIO()
    if format == 'xlsx':
        book = load_workbook(BytesIO(content))
        cell = book['业务数据']['B2']
        font = copy(cell.font)
        font.sz = 99
        cell.font = font
        book.save(output)
        field = 'xlsx.body.size'
    else:
        deck = Presentation(BytesIO(content))
        title = next(shape for shape in deck.slides[1].shapes
            if shape.has_text_frame and shape.text == materials.slides[0]['title'])
        from pptx.util import Pt

        title.text_frame.paragraphs[0].runs[0].font.size = Pt(99)
        deck.save(output)
        field = 'pptx.typography.h1.size'
    resolved = resolve_format_preferences(FormatPreferences.model_validate(draft['document']), format)
    _, frozen, _ = _verify_materials(materials)
    evidence = readback(output.getvalue(), format, resolved, frozen)
    sampled = [check for check in evidence['checks'] if check['path'] == field]
    assert sampled and all(check['passed'] for check in sampled)
    capability = next(item for item in _capabilities(format, resolved, evidence, frozen)
        if item['path'] == field)
    assert capability['status'] == 'not_verified'
    assert all(check.get('coverage') == 'sample' for check in sampled)


@pytest.mark.parametrize('format', ['word', 'pdf'])
def test_preflight_detects_tampered_second_document_caption(actual_preflight, format):
    from smart_reporting.management.preference_preflight import _capabilities, _verify_materials
    from smart_reporting.management.preference_preflight_readback import readback
    from smart_reporting.preferences.models import resolve_format_preferences

    draft, materials, baseline = actual_preflight
    content = base64.b64decode(baseline['formats'][format]['artifact']['base64'])
    if format == 'word':
        doc = Document(BytesIO(content))
        captions = [paragraph for paragraph in doc.paragraphs if paragraph.style.name == 'Caption']
        assert len(captions) == 2
        captions[-1].text = '篡改第二图注'
        output = BytesIO()
        doc.save(output)
        changed = output.getvalue()
    else:
        import pymupdf

        pdf = pymupdf.open(stream=content, filetype='pdf')
        hits = 0
        for page in pdf:
            for rectangle in page.search_for('第二图注'):
                page.add_redact_annot(rectangle)
                hits += 1
            page.apply_redactions()
        assert hits > 0
        changed = pdf.tobytes()
        pdf.close()
    resolved = resolve_format_preferences(FormatPreferences.model_validate(draft['document']), format)
    _, frozen, _ = _verify_materials(materials)
    evidence = readback(changed, format, resolved, frozen)
    capability = next(item for item in _capabilities(format, resolved, evidence, frozen)
        if item['path'] == format + '.charts.captionNumbering')
    assert capability['status'] == 'failed'
