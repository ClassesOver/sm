"""完整数字原生组：全部来源对象、原值和有效格式。"""

import json
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.xlsx import build_workbook
from smart_reporting.tests.test_preference_workbook_number_readback import _mutate
from smart_reporting.tests.test_preference_workbook_signature_native import changed_package

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
MARKER = 'xlsx_native_number_fields_v1'
OUTPUT = Path('output/system-config-preferences/xlsx-number-native-evidence')


@pytest.fixture(scope='module')
def native_numbers(tmp_path_factory):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '数字原生验收', 'dateFormat': 'iso'},
        'xlsx': {'numbers': {'decimalPlaces': 3, 'percentPlaces': 1,
            'thousandsSeparator': True, 'negativeStyle': 'parentheses', 'dateFormat': 'slash'}}}), 'xlsx')
    sheets = ({'name': '数据', 'rows': [['项目', 2026],
        ['局部加粗', {'value': 1234.56, 'style': {'bold': True}}], ['支出', -234.56],
        ['合计', {'value': 1000, 'formula': 'SUM(B2:B3)'}],
        ['百分点', {'value': 12.5, 'valueType': 'percentPoints', 'style': {'fontColor': '#334455'}}],
        ['显式百分数', {'value': .125, 'valueType': 'percentPoints', 'style': {'numberFormat': '0.0%'}}],
        ['布尔值', True]]},
        {'name': '日期明细', 'rows': [['项目', '数值'],
            ['日期', {'value': '2026-10-31', 'valueType': 'date'}], ['登记百分点', 7.5],
            ['显式日期', {'value': '2026-10-30', 'valueType': 'date', 'style': {'numberFormat': 'm/d/yyyy'}}]],
            'cellTypes': {'B3': 'percentPoints'}})
    frozen = {'sheets': sheets, 'state': {'_documentContext': {
        'title': '数字原生报告', 'periodLabel': '2026年10月', 'generatedDate': '2026-11-13'}}}
    output = tmp_path_factory.mktemp('number-native') / 'original.xlsx'
    build_workbook(output_path=output, title='数字原生报告', period='2026年10月',
        sheets=sheets, preferences=prefs, generated_date='2026-11-13')
    content = output.read_bytes()
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / 'original.xlsx').write_bytes(content)
    (OUTPUT / 'inputs.json').write_text(json.dumps({'preferences': prefs, 'frozen': frozen}, ensure_ascii=False, indent=2))
    return content, prefs, frozen


def group(content, prefs, frozen):
    checked = readback(content, 'xlsx', prefs, frozen)
    assert 'numbersReadback' in checked
    return checked, checked['numbersReadback']


def test_all_numeric_sources_and_field_locations_have_native_witness(native_numbers):
    checked, summary = group(*native_numbers)
    assert checked['status'] == 'passed'
    assert summary['sourceStatus'] == 'verified' and summary['status'] == 'passed'
    assert summary['sourceSheets'] == summary['checkedSheets'] == 2
    assert summary['expectedCells'] == summary['checkedCells'] == len(summary['cells']) == 9
    assert [(c['sheet'], c['cell'], c['kind'], c['override']) for c in summary['cells']] == [
        ('数据', 'B1', 'number', False), ('数据', 'B2', 'number', False),
        ('数据', 'B3', 'number', False), ('数据', 'B4', 'number', False),
        ('数据', 'B5', 'percent', False), ('数据', 'B6', 'percent', True),
        ('日期明细', 'B2', 'date', False), ('日期明细', 'B3', 'percent', False),
        ('日期明细', 'B4', 'date', True)]
    assert {k: len(v) for k, v in summary['fields'].items()} == {
        'decimalPlaces': 4, 'thousandsSeparator': 4, 'negativeStyle': 6, 'percentPlaces': 2, 'dateFormat': 1}
    marked = [c for c in checked['checks'] if c.get('evidenceKind') == MARKER]
    assert len(marked) == 18 and all(c['passed'] and c['coverage'] == 'complete' for c in marked)
    assert marked[0]['evidenceObjects'] == summary


@pytest.mark.parametrize('address,failed', [('B2', {'decimalPlaces', 'thousandsSeparator', 'negativeStyle'}),
    ('B5', {'percentPlaces', 'negativeStyle'})])
def test_wrong_format_keeps_group_but_fails_each_affected_field(native_numbers, address, failed):
    content, prefs, frozen = native_numbers
    checked, summary = group(_mutate(content, address, number_format=True), prefs, frozen)
    assert summary['status'] == 'passed'
    assert {c['path'].removeprefix('xlsx.numbers.') for c in checked['checks']
        if c.get('evidenceKind') == MARKER and not c['passed']} == failed


@pytest.mark.parametrize('fault', ['value', 'cache', 'duplicate_cell', 'missing_cell', 'foreign_value',
    'hidden_row', 'hidden_column', 'conditional_format', 'merge', 'extra_cell'])
def test_source_or_display_ambiguity_never_grants_complete_group(native_numbers, fault):
    content, prefs, frozen = native_numbers
    if fault in ('value', 'cache'):
        content = _mutate(content, 'B4' if fault == 'cache' else 'B2',
            raw_value='1000.00000000000000001' if fault == 'cache' else '1234.56000000000000001')
    else:
        def mutate(node):
            rows = node.find(NS + 'sheetData')
            row, cell = rows[1], rows[1][1]
            if fault == 'duplicate_cell':
                row.append(deepcopy(cell))
            elif fault == 'missing_cell':
                row.remove(cell)
            elif fault == 'foreign_value':
                cell.find(NS + 'v').tag = '{urn:foreign}v'
            elif fault == 'hidden_row':
                row.set('hidden', '1')
            elif fault == 'hidden_column':
                node.find(NS + 'cols')[1].set('hidden', '1')
            elif fault == 'conditional_format':
                ET.SubElement(node, NS + 'conditionalFormatting', sqref='B2')
            elif fault == 'merge':
                ET.SubElement(ET.SubElement(node, NS + 'mergeCells', count='1'), NS + 'mergeCell', ref='A2:B2')
            else:
                extra = deepcopy(cell)
                extra.set('r', 'C2')
                row.append(extra)
        content = changed_package(content, mutate, part='xl/worksheets/sheet1.xml')
    checked, summary = group(content, prefs, frozen)
    assert summary['sourceStatus'] == 'unverified' and summary['status'] != 'passed'
    assert checked['status'] == 'failed'
    assert not any(c.get('evidenceKind') == MARKER and c.get('path') != 'xlsx.numbers.nativeStructure'
        for c in checked['checks'])


def test_only_explicit_overrides_or_non_numbers_do_not_verify_defaults(tmp_path, native_numbers):
    _, prefs, _ = native_numbers
    sheets = ({'name': '数据', 'rows': [['项目', '值'], ['显式', {'value': 12.5, 'style': {'numberFormat': '0.0'}}],
        ['布尔', True], ['精确文本', '1234.560000000000001'],
        ['过早日期', {'value': '1899-12-31', 'valueType': 'date'}]]},)
    frozen = {'sheets': sheets, 'state': {'_documentContext': {
        'title': '数字原生报告', 'periodLabel': '2026年10月', 'generatedDate': '2026-11-13'}}}
    output = tmp_path / 'overrides.xlsx'
    build_workbook(output_path=output, title='数字原生报告', period='2026年10月', sheets=sheets,
        preferences=prefs, generated_date='2026-11-13')
    checked, summary = group(output.read_bytes(), prefs, frozen)
    assert summary['status'] == 'passed' and summary['expectedCells'] == 1
    assert all(v == [] for v in summary['fields'].values())
    assert [c['path'] for c in checked['checks'] if c.get('evidenceKind') == MARKER] == ['xlsx.numbers.nativeStructure']


def test_negative_style_index_cannot_alias_a_valid_python_style(native_numbers):
    from io import BytesIO
    from zipfile import ZipFile

    content, prefs, frozen = native_numbers
    with ZipFile(BytesIO(content)) as package:
        count = len(ET.fromstring(package.read('xl/styles.xml')).find(NS + 'cellXfs'))

    def mutate(node):
        cell = node.find('.//' + NS + 'c[@r="B2"]')
        cell.set('s', str(int(cell.get('s')) - count))

    changed = changed_package(content, mutate, part='xl/worksheets/sheet1.xml')
    checked, summary = group(changed, prefs, frozen)
    assert summary['sourceStatus'] == 'unverified' and summary['status'] != 'passed'
    assert checked['status'] == 'failed'


def test_changed_explicit_numeric_override_invalidates_its_source_group(native_numbers):
    content, prefs, frozen = native_numbers
    # 覆盖格不发默认偏好证据，其原始声明也不能被静默改写。
    checked, summary = group(_mutate(content, 'B6', number_format=True), prefs, frozen)
    assert checked['status'] == 'failed'
    assert summary['sourceStatus'] == 'unverified'


def test_ragged_rows_null_values_and_text_do_not_expand_numeric_scope(tmp_path, native_numbers):
    _, prefs, _ = native_numbers
    sheets = ({'name': '数据', 'rows': [['项目', '值', '备注'], ['收入', 1000],
        ['空值', None, ''], ['文本', '1234.500000000000001']]},)
    frozen = {'sheets': sheets, 'state': {'_documentContext': {
        'title': '数字原生报告', 'periodLabel': '2026年10月', 'generatedDate': '2026-11-13'}}}
    output = tmp_path / 'ragged.xlsx'
    build_workbook(output_path=output, title='数字原生报告', period='2026年10月', sheets=sheets,
        preferences=prefs, generated_date='2026-11-13')
    checked, summary = group(output.read_bytes(), prefs, frozen)
    assert checked['status'] == 'passed'
    assert summary['status'] == 'passed' and summary['expectedCells'] == 1
    assert {k: len(v) for k, v in summary['fields'].items()} == {
        'decimalPlaces': 1, 'thousandsSeparator': 1, 'negativeStyle': 1, 'percentPlaces': 0, 'dateFormat': 0}


@pytest.mark.parametrize('fault', ['inactive_format', 'duplicate_format', 'duplicate_xfs'])
def test_ambiguous_native_style_definitions_do_not_grant_number_evidence(native_numbers, fault):
    from io import BytesIO
    from zipfile import ZipFile

    content, prefs, frozen = native_numbers
    with ZipFile(BytesIO(content)) as package:
        cell = ET.fromstring(package.read('xl/worksheets/sheet1.xml')).find('.//' + NS + 'c[@r="B2"]')
        index = int(cell.get('s'))

    def mutate(styles):
        if fault == 'inactive_format':
            styles.find(NS + 'cellXfs')[index].set('applyNumberFormat', '0')
        elif fault == 'duplicate_format':
            formats = styles.find(NS + 'numFmts')
            formats.append(deepcopy(formats[0]))
            formats.set('count', str(len(formats)))
        else:
            styles.append(deepcopy(styles.find(NS + 'cellXfs')))

    changed = changed_package(content, mutate, part='xl/styles.xml')
    (OUTPUT / (fault + '.xlsx')).write_bytes(changed)
    checked, summary = group(changed, prefs, frozen)
    assert summary['sourceStatus'] == 'unverified'
    assert checked['status'] == 'failed'
