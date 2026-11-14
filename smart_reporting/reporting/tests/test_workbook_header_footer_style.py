"""打印页眉页脚使用原生字体代码，保留字段、文字和业务单元格。"""
from copy import deepcopy
from io import BytesIO

import pytest
from openpyxl import load_workbook

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.preferences.workbook_adapter import prepare_workbook
from smart_reporting.reporting.delivery.xlsx import build_workbook


def _preferences(*, size=14, bold=True, enabled=True):
    return resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '打印编制', 'dateFormat': 'iso'}, 'xlsx': {'print': {'headerFooter': {
            'enabled': enabled, 'style': {'font': 'serif', 'size': size, 'bold': bold, 'color': '#345678'},
            'header': {'left': '{signer}', 'center': 'R&D {title}', 'right': '{date}'},
            'footer': {'left': '{period}', 'center': '', 'right': '{page}/{pages}'},
        }}}}), 'xlsx')


@pytest.mark.parametrize('bold,name', [(True, 'Bold'), (False, 'Regular')])
def test_workbook_adapter_encodes_font_size_color_before_escaped_content_and_fields(bold, name):
    prefs = _preferences(bold=bold)
    original = deepcopy(prefs)
    _, native = prepare_workbook(({'name': '数据', 'rows': [['指标'], ['收入']]},), prefs,
        title='预算 &P', period='2026年10月', generated_date='2026-11-13', filename='report.xlsx')
    prefix = f'&"Noto Serif CJK SC,{name}"&14&K345678'
    assert native['print']['header']['center'] == prefix + 'R&&D 预算 &&P'
    assert native['print']['footer']['right'] == prefix + '&P/&N'
    assert native['print']['footer']['center'] == ''
    assert prefs == original


def test_workbook_fractional_print_font_is_explicitly_warned_and_disabled_headers_stay_empty():
    args = dict(title='报告', period='2026', generated_date='2026-11-13', filename='report.xlsx')
    sheets = ({'name': '数据', 'rows': [['指标'], ['收入']]},)
    _, native = prepare_workbook(sheets, _preferences(size=13.5), **args)
    assert '&14&K' in native['print']['header']['left']
    assert any(issue['code'] == 'workbook_header_footer_font_rounded' for issue in native['layoutIssues'])
    _, disabled = prepare_workbook(sheets, _preferences(size=13.5, enabled=False), **args)
    assert disabled['print']['header'] is disabled['print']['footer'] is None
    assert not any(issue['code'] == 'workbook_header_footer_font_rounded' for issue in disabled['layoutIssues'])


def test_oversize_print_header_footer_warns_without_mutating_frozen_style_or_removing_output():
    sheets = ({'name': '数据', 'rows': [['指标'], ['收入']]},)
    args = dict(title='报告', period='2026', generated_date='2026-11-13', filename='report.xlsx')
    preferences = _preferences(size=72)
    before = deepcopy(preferences)
    _, native = prepare_workbook(sheets, preferences, **args)
    risks = [issue for issue in native['layoutIssues'] if issue['code'] == 'workbook_header_footer_band_overflow']
    assert len(risks) == 2 and all('可能' in issue['message'] for issue in risks)
    assert '&72&K' in native['print']['header']['left'] and '&P/&N' in native['print']['footer']['right']
    assert preferences == before
    _, ordinary = prepare_workbook(sheets, _preferences(), **args)
    assert not any(issue['code'] == 'workbook_header_footer_band_overflow' for issue in ordinary['layoutIssues'])
    _, disabled = prepare_workbook(sheets, _preferences(size=72, enabled=False), **args)
    assert not any(issue['code'] == 'workbook_header_footer_band_overflow' for issue in disabled['layoutIssues'])


@pytest.fixture(scope='module')
def styled_workbook(tmp_path_factory):
    output = tmp_path_factory.mktemp('workbook-header-style') / 'styled-header.xlsx'
    sheets = ({'name': '数据', 'rows': [['指标', '金额'], ['收入', 1234.56],
        ['合计', {'value': 1234.56, 'formula': 'B2'}]]},)
    build_workbook(output_path=output, title='季度报告', period='2026年10月',
        sheets=sheets,
        preferences=_preferences(), generated_date='2026-11-13')
    return output, {'markdown': '# 季度报告', 'sheets': sheets, 'state': {'_documentContext': {'title': '季度报告',
        'periodLabel': '2026年10月', 'generatedDate': '2026-11-13'}}}


def test_workbook_native_print_style_preserves_real_page_fields_and_formula_cache(styled_workbook):
    output, _ = styled_workbook
    book = load_workbook(output)
    for sheet in book:
        for kind, side in [('oddHeader', 'left'), ('oddHeader', 'center'), ('oddHeader', 'right'),
            ('oddFooter', 'left'), ('oddFooter', 'right')]:
            part = getattr(getattr(sheet, kind), side)
            assert part.font == 'Noto Serif CJK SC,Bold'
            assert part.size == 14 and part.color == '345678'
        assert sheet.oddFooter.center.text is None
        assert sheet.oddFooter.right.text == '&P/&N'
        assert sheet.oddHeader.right.text == '2026-11-13'
    assert book['数据']['B2'].value == 1234.56
    assert book['数据']['B3'].value == '=B2'
    assert load_workbook(output, data_only=True)['数据']['B3'].value == 1234.56


def test_preflight_reads_print_style_in_all_business_and_signature_header_footer_sections(styled_workbook):
    from smart_reporting.management.preference_preflight import _capabilities
    from smart_reporting.management.preference_preflight_readback import readback

    output, frozen = styled_workbook
    resolved = _preferences()
    result = readback(output.read_bytes(), 'xlsx', resolved, frozen)
    capabilities = {item['path']: item['status'] for item in _capabilities('xlsx', resolved, result, frozen)}
    for key in ('font', 'size', 'color', 'bold'):
        path = 'xlsx.print.headerFooter.style.' + key
        checks = [item for item in result['checks'] if item['path'] == path]
        assert len(checks) == 10  # 两个工作表，每页五个有内容的区域。
        assert all(item['passed'] and item['coverage'] == 'complete' for item in checks)
        assert capabilities[path] == 'verified'


def test_preflight_detects_print_style_corruption_in_last_signature_footer(styled_workbook):
    from smart_reporting.management.preference_preflight import _capabilities
    from smart_reporting.management.preference_preflight_readback import readback

    output, frozen = styled_workbook
    book = load_workbook(output)
    book['说明'].oddFooter.right.size = 30
    modified = BytesIO()
    book.save(modified)
    result = readback(modified.getvalue(), 'xlsx', _preferences(), frozen)
    paths = {item['path']: item['status'] for item in _capabilities('xlsx', _preferences(), result, frozen)}
    assert paths['xlsx.print.headerFooter.style.size'] == 'failed'


@pytest.mark.parametrize('bold', [True, False])
def test_preflight_does_not_approve_style_when_expected_signature_footer_is_removed(styled_workbook, bold):
    from smart_reporting.management.preference_preflight import _capabilities
    from smart_reporting.management.preference_preflight_readback import readback

    output, frozen = styled_workbook
    book = load_workbook(output)
    if not bold:
        for sheet in book:
            for kind in (sheet.oddHeader, sheet.oddFooter):
                for side in ('left', 'center', 'right'):
                    part = getattr(kind, side)
                    if part.text:
                        part.font = 'Noto Serif CJK SC,Regular'
    book['说明'].oddFooter.right.text = None
    modified = BytesIO()
    book.save(modified)
    result = readback(modified.getvalue(), 'xlsx', _preferences(bold=bold), frozen)
    paths = {item['path']: item['status'] for item in _capabilities('xlsx', _preferences(bold=bold), result, frozen)}
    for key in ('font', 'size', 'color', 'bold'):
        assert paths['xlsx.print.headerFooter.style.' + key] == 'failed'
