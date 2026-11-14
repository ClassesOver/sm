"""真实电子表格的数字格式优先级与来源精度验收。"""

import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.xlsx import build_workbook

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
EVIDENCE = Path('output/system-config-preferences/xlsx-number-readback')


@pytest.fixture(scope='module')
def numeric_workbook(tmp_path_factory):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '数字格式验收', 'dateFormat': 'iso'},
        'xlsx': {'numbers': {'decimalPlaces': 3, 'percentPlaces': 1,
            'thousandsSeparator': True, 'negativeStyle': 'parentheses', 'dateFormat': 'slash'}}}), 'xlsx')
    sheets = ({'name': '数据', 'rows': [
        ['项目', 2026],
        ['局部加粗', {'value': 1234.56, 'style': {'bold': True}}],
        ['支出', -234.56],
        ['合计', {'value': 1000, 'formula': 'SUM(B2:B3)'}],
        ['局部颜色百分点', {'value': 12.5, 'valueType': 'percentPoints', 'style': {'fontColor': '#334455'}}],
        ['日期显式覆盖', {'value': '2026-10-31', 'valueType': 'date', 'style': {'numberFormat': 'm/d/yyyy'}}],
        ['数字显式覆盖', {'value': .125, 'valueType': 'percentPoints', 'style': {'numberFormat': '0.0%'}}],
        ['偏好日期', {'value': '2026-10-31', 'valueType': 'date'}],
        ['布尔值', True],
    ]},)
    frozen = {'sheets': sheets, 'state': {'_documentContext': {
        'title': '数字格式报告', 'periodLabel': '2026年10月', 'generatedDate': '2026-11-13'}}}
    output = tmp_path_factory.mktemp('number-readback') / 'original.xlsx'
    build_workbook(output_path=output, title='数字格式报告', period='2026年10月',
        sheets=sheets, preferences=prefs, generated_date='2026-11-13')
    content = output.read_bytes()
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / 'original.xlsx').write_bytes(content)
    (EVIDENCE / 'inputs.json').write_text(json.dumps({'preferences': prefs, 'frozen': frozen},
        ensure_ascii=False, indent=2))
    return content, prefs, frozen


def _mutate(content, address, *, number_format=False, raw_value=None):
    """只改目标格样式索引或原始v；不经过会丢失公式缓存的保存器。"""
    output = BytesIO()
    with ZipFile(BytesIO(content)) as archive, ZipFile(output, 'w') as target:
        sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        cell = sheet.find(f'.//{NS}c[@r="{address}"]')
        changed = {}
        if number_format:
            styles = ET.fromstring(archive.read('xl/styles.xml'))
            formats = styles.find(NS + 'cellXfs')
            style = deepcopy(formats[int(cell.get('s', '0'))])
            style.set('numFmtId', '0')
            style.set('applyNumberFormat', '1')
            cell.set('s', str(len(formats)))
            formats.append(style)
            formats.set('count', str(len(formats)))
            changed['xl/styles.xml'] = ET.tostring(styles, encoding='utf-8', xml_declaration=True)
        if raw_value is not None:
            cell.find(NS + 'v').text = raw_value
        changed['xl/worksheets/sheet1.xml'] = ET.tostring(sheet, encoding='utf-8', xml_declaration=True)
        for item in archive.infolist():
            target.writestr(item, changed.get(item.filename, archive.read(item.filename)))
    return output.getvalue()


def test_actual_numeric_formats_and_explicit_overrides_pass(numeric_workbook):
    content, prefs, frozen = numeric_workbook
    result = readback(content, 'xlsx', prefs, frozen)
    assert result['status'] == 'passed', [c for c in result['checks'] if not c['passed']]


@pytest.mark.parametrize('address,path', [
    ('B1', 'xlsx.numbers.decimalPlaces'),
    ('B2', 'xlsx.numbers.decimalPlaces'),
    ('B5', 'xlsx.numbers.percentPlaces'),
    ('B6', None),
    ('B7', None),
    ('B8', 'xlsx.numbers.dateFormat'),
])
def test_changed_native_format_never_passes(numeric_workbook, address, path):
    content, prefs, frozen = numeric_workbook
    changed = _mutate(content, address, number_format=True)
    (EVIDENCE / f'format-{address}.xlsx').write_bytes(changed)
    result = readback(changed, 'xlsx', prefs, frozen)
    failures = [c for c in result['checks'] if not c['passed']]
    assert result['status'] == 'failed', address
    assert any(c['path'] == path for c in failures), failures


@pytest.mark.parametrize('address,value', [('B2', '1234.57'), ('B4', '1000.01')])
def test_small_source_or_formula_cache_drift_fails(numeric_workbook, address, value):
    content, prefs, frozen = numeric_workbook
    changed = _mutate(content, address, raw_value=value)
    (EVIDENCE / f'value-{address}.xlsx').write_bytes(changed)
    result = readback(changed, 'xlsx', prefs, frozen)
    assert result['status'] == 'failed'
    assert any(c['path'] is None and not c['passed'] and c['actual'] == float(value)
        for c in result['checks'])


def test_explicit_non_date_display_preserves_date_source(tmp_path, numeric_workbook):
    _, prefs, frozen = numeric_workbook
    frozen = deepcopy(frozen)
    frozen['sheets'][0]['rows'][5][1]['style']['numberFormat'] = '0.00'
    output = tmp_path / 'date-override.xlsx'
    build_workbook(output_path=output, title='数字格式报告', period='2026年10月',
        sheets=frozen['sheets'], preferences=prefs, generated_date='2026-11-13')
    content = output.read_bytes()
    (EVIDENCE / 'date-override.xlsx').write_bytes(content)
    result = readback(content, 'xlsx', prefs, frozen)
    assert result['status'] == 'passed', [c for c in result['checks'] if not c['passed']]


def test_numeric_one_cannot_replace_boolean_source(numeric_workbook):
    content, prefs, frozen = numeric_workbook
    result = BytesIO()
    with ZipFile(BytesIO(content)) as original, ZipFile(result, 'w') as output:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == 'xl/worksheets/sheet1.xml':
                node = ET.fromstring(data)
                node.find(f'.//{NS}c[@r="B9"]').set('t', 'n')
                data = ET.tostring(node, encoding='utf-8', xml_declaration=True)
            output.writestr(item, data)
    result = readback(result.getvalue(), 'xlsx', prefs, frozen)
    assert result['status'] == 'failed'
    assert any(c['path'] is None and not c['passed'] and c['actual'] == 1
        and c['expected'] is True for c in result['checks'])


@pytest.mark.parametrize('pattern', ['m/d/yyyy h:mm', 'm/d/yyyy hh:mm'])
def test_existing_regional_datetime_builtin_keeps_explicit_semantics(tmp_path, numeric_workbook, pattern):
    _, prefs, frozen = numeric_workbook
    frozen = deepcopy(frozen)
    frozen['sheets'][0]['rows'][5][1]['style']['numberFormat'] = pattern
    output = tmp_path / 'regional-date.xlsx'
    build_workbook(output_path=output, title='数字格式报告', period='2026年10月',
        sheets=frozen['sheets'], preferences=prefs, generated_date='2026-11-13')
    result = readback(output.read_bytes(), 'xlsx', prefs, frozen)
    assert result['status'] == 'passed', [c for c in result['checks'] if not c['passed']]


@pytest.mark.parametrize('drift', ['60', '59.000000000001'])
def test_date_raw_serial_drift_cannot_hide_in_lossy_date_decoder(tmp_path, numeric_workbook, drift):
    _, prefs, frozen = numeric_workbook
    frozen = deepcopy(frozen)
    frozen['sheets'][0]['rows'][7][1]['value'] = '1900-02-28'
    output = tmp_path / 'date-serial.xlsx'
    build_workbook(output_path=output, title='数字格式报告', period='2026年10月',
        sheets=frozen['sheets'], preferences=prefs, generated_date='2026-11-13')
    content = output.read_bytes()
    assert readback(content, 'xlsx', prefs, frozen)['status'] == 'passed'
    changed = _mutate(content, 'B8', raw_value=drift)
    result = readback(changed, 'xlsx', prefs, frozen)
    assert result['status'] == 'failed'
    assert any(c['path'] is None and not c['passed'] for c in result['checks'])


@pytest.mark.parametrize('tag', ['v', 'c'])
def test_foreign_namespace_cannot_supply_date_identity(numeric_workbook, tag):
    content, prefs, frozen = numeric_workbook
    result = BytesIO()
    with ZipFile(BytesIO(content)) as original, ZipFile(result, 'w') as output:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == 'xl/worksheets/sheet1.xml':
                node = ET.fromstring(data)
                cell = node.find(f'.//{NS}c[@r="B8"]')
                (cell if tag == 'c' else cell.find(NS + 'v')).tag = '{urn:foreign}' + tag
                data = ET.tostring(node, encoding='utf-8', xml_declaration=True)
            output.writestr(item, data)
    changed = result.getvalue()
    (EVIDENCE / f'foreign-date-{tag}.xlsx').write_bytes(changed)
    checked = readback(changed, 'xlsx', prefs, frozen)
    assert checked['status'] == 'failed'
    assert any(c['path'] is None and not c['passed'] for c in checked['checks'])


@pytest.mark.parametrize('numbers,ordinary,percent,date_pattern', [
    ({'decimalPlaces': 0, 'percentPlaces': 0, 'thousandsSeparator': False,
        'negativeStyle': 'minus', 'dateFormat': 'iso'}, '0;-0', '0"%";-0"%"', 'yyyy-mm-dd'),
    ({'decimalPlaces': 2, 'percentPlaces': 3, 'thousandsSeparator': True,
        'negativeStyle': 'red', 'dateFormat': 'chinese'},
        '#,##0.00;[Red]-#,##0.00', '0.000"%";[Red]-0.000"%"', 'yyyy"年"m"月"d"日"'),
])
def test_other_numeric_preferences_keep_values_and_validate_each_format(
    tmp_path, numeric_workbook, numbers, ordinary, percent, date_pattern,
):
    from openpyxl import load_workbook

    _, prefs, frozen = numeric_workbook
    prefs = deepcopy(prefs)
    prefs['numbers'].update(numbers)
    output = tmp_path / 'numeric-variant.xlsx'
    build_workbook(output_path=output, title='数字格式报告', period='2026年10月',
        sheets=frozen['sheets'], preferences=prefs, generated_date='2026-11-13')
    content = output.read_bytes()
    book = load_workbook(BytesIO(content))
    assert book['数据']['B2'].value == 1234.56
    assert book['数据']['B2'].number_format == ordinary
    assert book['数据']['B5'].value == 12.5
    assert book['数据']['B5'].number_format == percent
    assert book['数据']['B8'].number_format == date_pattern
    assert readback(content, 'xlsx', prefs, frozen)['status'] == 'passed'
    for address, path in [('B2', 'decimalPlaces'), ('B5', 'percentPlaces'), ('B8', 'dateFormat')]:
        checked = readback(_mutate(content, address, number_format=True), 'xlsx', prefs, frozen)
        assert any(c['path'] == 'xlsx.numbers.' + path and not c['passed'] for c in checked['checks'])
