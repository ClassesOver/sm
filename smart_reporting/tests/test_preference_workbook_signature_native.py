"""原生落款内容逐行回读，保留空行语义并拒绝隐藏或歧义结构。"""

from copy import deepcopy
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.xlsx import build_workbook


def test_workbook_signature_description_preserves_interior_blank_lines(tmp_path):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '编制人员', 'dateFormat': 'iso'},
        'xlsx': {'signature': {'description': '第一行说明\n\n最后一行说明'}}}), 'xlsx')
    sheets = ({'name': '数据', 'rows': [['项目', '金额'], ['收入', 1000]]},)
    frozen = {'markdown': '# 报告', 'sheets': sheets, 'state': {'_documentContext': {
        'title': '报告', 'periodLabel': '2026年10月', 'generatedDate': '2026-11-13'}}}
    output = tmp_path / 'signature.xlsx'
    result = build_workbook(output_path=output, title='报告', period='2026年10月',
        sheets=sheets, preferences=prefs, generated_date='2026-11-13')
    assert not result.issues
    checked = readback(output.read_bytes(), 'xlsx', prefs, frozen)
    description = [item for item in checked['checks'] if item['path'] == 'xlsx.signature.description']
    assert description and all(item['passed'] for item in description), description
    assert checked['status'] == 'passed'


@pytest.fixture(scope='module')
def native_signature(tmp_path_factory):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '编制人员 & <复核>', 'dateFormat': 'iso'},
        'xlsx': {'signature': {'description': '第一行说明\n\n最后一行说明'}}}), 'xlsx')
    sheets = ({'name': '说明', 'rows': [['项目', '金额'], ['收入', 1000],
        ['合计', {'value': 1000, 'formula': 'B2'}]]},)
    frozen = {'markdown': '# 报告', 'sheets': sheets, 'state': {'_documentContext': {
        'title': '报告', 'periodLabel': '2026年10月', 'generatedDate': '2026-11-13'}}}
    output = tmp_path_factory.mktemp('signature') / 'signature.xlsx'
    build_workbook(output_path=output, title='报告', period='2026年10月',
        sheets=sheets, preferences=prefs, generated_date='2026-11-13')
    return output.read_bytes(), prefs, frozen


def changed_package(content, mutate, part='xl/worksheets/sheet2.xml'):
    result = BytesIO()
    with ZipFile(BytesIO(content)) as original, ZipFile(result, 'w') as output:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == part:
                node = ET.fromstring(data)
                mutate(node)
                data = ET.tostring(node, encoding='utf-8', xml_declaration=True)
            output.writestr(item, data)
    return result.getvalue()


def test_unique_terminal_signature_group_covers_exact_cells_and_empty_line(native_signature):
    content, prefs, frozen = native_signature
    checked = readback(content, 'xlsx', prefs, frozen)
    group = checked['signatureReadback']
    assert group['status'] == 'passed' and group['sourceStatus'] == 'verified'
    assert group['sheet'] == '说明2' and group['part'] == 'xl/worksheets/sheet2.xml'
    assert group['expectedRows'] == group['nativeRows'] == group['checkedRows'] == 6
    assert group['cells'] == ['A1', 'A2', 'A3', 'A4', 'A5', 'A6']
    fields = [item for item in checked['checks'] if item.get('evidenceKind') == 'xlsx_native_signature_content_v1'
        and item['path'] != 'xlsx.signature.nativeStructure']
    assert {item['path'] for item in fields} == {
        'xlsx.common.signer', 'xlsx.common.dateFormat', 'xlsx.signature.description'}
    assert all(item['passed'] and item['coverage'] == 'complete' for item in fields)
    assert next(item for item in fields if item['path'] == 'xlsx.signature.description')['actual'] == '第一行说明\n\n最后一行说明'


@pytest.mark.parametrize('fault', ['hidden_row', 'zero_height', 'hidden_column', 'duplicate_cell',
    'extra_cell', 'formula', 'rich_text', 'merged_cells', 'extra_drawing', 'duplicate_rows'])
def test_hidden_or_ambiguous_signature_never_passes_native_readback(native_signature, fault):
    content, prefs, frozen = native_signature

    def mutate(node):
        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        data = node.find(ns + 'sheetData')
        row = data[1]
        cell = row[0]
        if fault == 'hidden_row':
            row.set('hidden', '1')
        elif fault == 'zero_height':
            row.set('ht', '0')
        elif fault == 'hidden_column':
            node.find(ns + 'cols')[0].set('hidden', '1')
        elif fault == 'duplicate_cell':
            row.append(deepcopy(cell))
        elif fault == 'extra_cell':
            extra = deepcopy(cell)
            extra.set('r', 'B2')
            row.append(extra)
        elif fault == 'formula':
            ET.SubElement(cell, ns + 'f').text = '"编制人员 & <复核>"'
        elif fault == 'rich_text':
            inline = cell.find(ns + 'is')
            text = inline[0]
            inline.remove(text)
            ET.SubElement(inline, ns + 'r').append(text)
        elif fault == 'merged_cells':
            ET.SubElement(ET.SubElement(node, ns + 'mergeCells'), ns + 'mergeCell', ref='A2:B2')
        elif fault == 'extra_drawing':
            ET.SubElement(node, ns + 'drawing')
        else:
            data.append(deepcopy(row))

    checked = readback(changed_package(content, mutate), 'xlsx', prefs, frozen)
    assert checked['status'] == 'failed', fault
    assert checked['signatureReadback']['sourceStatus'] == 'unverified'


def test_changed_description_fails_only_its_content_field(native_signature):
    content, prefs, frozen = native_signature

    def mutate(node):
        node.find('{*}sheetData')[-1][0].find('{*}is/{*}t').text = '被替换的说明'

    checked = readback(changed_package(content, mutate), 'xlsx', prefs, frozen)
    assert checked['signatureReadback']['sourceStatus'] == 'verified'
    fields = [item for item in checked['checks'] if item.get('evidenceKind') == 'xlsx_native_signature_content_v1'
        and item['path'] != 'xlsx.signature.nativeStructure']
    assert {item['path'] for item in fields if not item['passed']} == {'xlsx.signature.description'}


def test_empty_optional_description_has_complete_empty_native_coverage(tmp_path):
    prefs = resolve_format_preferences(FormatPreferences(common={'signer': '编制人员'}), 'xlsx')
    sheets = ({'name': '数据', 'rows': [['项目'], ['收入']]},)
    frozen = {'sheets': sheets, 'state': {'_documentContext': {
        'title': '报告', 'periodLabel': '2026年10月', 'generatedDate': '2026-11-13'}}}
    output = tmp_path / 'empty.xlsx'
    build_workbook(output_path=output, title='报告', period='2026年10月',
        sheets=sheets, preferences=prefs, generated_date='2026-11-13')
    checked = readback(output.read_bytes(), 'xlsx', prefs, frozen)
    assert checked['status'] == 'passed'
    assert checked['signatureReadback']['checkedRows'] == 3
    description = next(item for item in checked['checks'] if item['path'] == 'xlsx.signature.description')
    assert description['actual'] == description['expected'] == ''
    assert description['evidenceObjects']['cells'] == []


def test_unverified_package_identity_cannot_grant_signature_group(native_signature):
    content, prefs, frozen = native_signature

    def mutate(node):
        node.find('{*}sheets')[-1].set('sheetId', '1')

    checked = readback(changed_package(content, mutate, 'xl/workbook.xml'), 'xlsx', prefs, frozen)
    assert checked['signatureReadback']['sourceStatus'] == 'unverified'
    assert all(not item['passed'] and item['coverage'] == 'sample' for item in checked['checks']
        if item.get('evidenceKind') == 'xlsx_native_signature_content_v1')


@pytest.mark.parametrize('unprotected', [False, True])
def test_spreadsheetml_escape_semantics_distinguish_literal_from_encoded_text(tmp_path, unprotected):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '_x0041_'}, 'xlsx': {'print': {'headerFooter': {'enabled': False}}}}), 'xlsx')
    sheets = ({'name': '数据', 'rows': [['项目'], ['收入']]},)
    frozen = {'sheets': sheets, 'state': {'_documentContext': {
        'title': '报告', 'periodLabel': '2026年10月', 'generatedDate': '2026-11-13'}}}
    output = tmp_path / 'escape.xlsx'
    build_workbook(output_path=output, title='报告', period='2026年10月',
        sheets=sheets, preferences=prefs, generated_date='2026-11-13')
    content = output.read_bytes()
    if unprotected:
        def mutate(node):
            node.find('{*}sheetData')[1][0].find('{*}is/{*}t').text = '_x0041_'
        content = changed_package(content, mutate)
    checked = readback(content, 'xlsx', prefs, frozen)
    signer = next(item for item in checked['checks'] if item['path'] == 'xlsx.common.signer')
    assert signer['passed'] is (not unprotected)
    assert signer['actual'] == ('A' if unprotected else '_x0041_')


@pytest.mark.parametrize('fault', ['zero_default_height', 'zero_default_width', 'text_tail', 'inline_text',
    'cell_tail', 'row_text'])
def test_effective_zero_dimensions_and_unconsumed_xml_text_cannot_grant_complete_group(native_signature, fault):
    content, prefs, frozen = native_signature

    def mutate(node):
        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        row = node.find(ns + 'sheetData')[1]
        cell = row[0]
        if fault in ('zero_default_height', 'zero_default_width'):
            prop = ET.Element(ns + 'sheetFormatPr')
            node.insert(3, prop)
            if fault == 'zero_default_height':
                prop.set('defaultRowHeight', '0')
                row.attrib.pop('ht')
                row.attrib.pop('customHeight')
            else:
                prop.set('defaultColWidth', '0')
                node.remove(node.find(ns + 'cols'))
        elif fault == 'text_tail':
            cell[0][0].tail = '未读取的额外文本'
        elif fault == 'inline_text':
            cell[0].text = '未读取的额外文本'
        elif fault == 'cell_tail':
            cell.tail = '未读取的额外文本'
        else:
            row.text = '未读取的额外文本'

    checked = readback(changed_package(content, mutate), 'xlsx', prefs, frozen)
    assert checked['status'] == 'failed'
    assert checked['signatureReadback']['sourceStatus'] == 'unverified'
