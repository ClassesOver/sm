"""正式XLSX样例回读；说明页和实际激活变体不能遗漏。"""

from copy import deepcopy
from io import BytesIO

import pytest
from openpyxl import load_workbook

from smart_reporting.management.preference_preflight import _capabilities
from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.reporting.tests.test_workbook_header_footer_style import _preferences
from smart_reporting.reporting.tests.test_workbook_header_footer_style import (
    styled_workbook as styled_workbook,
)


def _check(styled_workbook, mutate, *, enabled=True):
    source, frozen = styled_workbook
    book = load_workbook(source)
    mutate(book['说明'])
    stream = BytesIO()
    book.save(stream)
    prefs = _preferences(enabled=enabled)
    result = readback(stream.getvalue(), 'xlsx', prefs, frozen)
    return result, {item['path']: item['status'] for item in _capabilities('xlsx', prefs, result, frozen)}


@pytest.mark.parametrize('kind,side', [('header', 'left'), ('header', 'center'), ('header', 'right'),
    ('footer', 'left'), ('footer', 'center'), ('footer', 'right')])
def test_last_signature_sheet_header_footer_text_cannot_hide_behind_business_sheet_checks(styled_workbook, kind, side):
    def mutate(sheet):
        part = getattr(getattr(sheet, 'odd' + kind.title()), side)
        part.text = '错误的说明页文字'

    _, capabilities = _check(styled_workbook, mutate)
    assert capabilities['xlsx.print.headerFooter.' + kind + '.' + side] == 'failed'


@pytest.mark.parametrize('side', ['header', 'footer'])
def test_signature_sheet_header_footer_distance_is_checked(styled_workbook, side):
    def mutate(sheet):
        setattr(sheet.page_margins, side, .01)

    _, capabilities = _check(styled_workbook, mutate)
    assert capabilities['xlsx.print.headerFooter.' + side + 'Distance'] == 'failed'


@pytest.mark.parametrize('flag', ['differentFirst', 'differentOddEven'])
def test_activated_first_or_even_variant_does_not_approve_unused_odd_text_and_style(styled_workbook, flag):
    def mutate(sheet):
        setattr(sheet.HeaderFooter, flag, True)
        # 变体为空仍会使实际首页/偶数页丢掉要求的文字，不能只找odd节点。

    _, capabilities = _check(styled_workbook, mutate)
    assert capabilities['xlsx.print.headerFooter.header.left'] == 'failed'
    assert capabilities['xlsx.print.headerFooter.enabled'] == 'failed'
    for key in ('font', 'size', 'color', 'bold'):
        assert capabilities['xlsx.print.headerFooter.style.' + key] == 'failed'


def test_header_footer_content_and_distance_checks_cover_business_and_signature_sheets(styled_workbook):
    source, frozen = styled_workbook
    result = readback(source.read_bytes(), 'xlsx', _preferences(), frozen)
    for suffix in ('enabled', 'header.left', 'header.center', 'header.right',
        'footer.left', 'footer.center', 'footer.right', 'headerDistance', 'footerDistance'):
        checks = [item for item in result['checks'] if item['path'] == 'xlsx.print.headerFooter.' + suffix]
        assert len(checks) == 2
        assert all(item['passed'] and item['coverage'] == 'complete' for item in checks)


@pytest.mark.parametrize('flag,variant', [('differentFirst', 'first'), ('differentOddEven', 'even')])
@pytest.mark.parametrize('sheet_name', ['数据', '说明'])
def test_active_variant_with_matching_text_and_style_is_verified(styled_workbook, flag, variant, sheet_name):
    source, frozen = styled_workbook
    book = load_workbook(source)
    sheet = book[sheet_name]
    setattr(sheet.HeaderFooter, flag, True)
    for kind in ('Header', 'Footer'):
        setattr(sheet, variant + kind, deepcopy(getattr(sheet, 'odd' + kind)))
    stream = BytesIO()
    book.save(stream)
    result = readback(stream.getvalue(), 'xlsx', _preferences(), frozen)
    checks = [item for item in result['checks'] if (item['path'] or '').startswith('xlsx.print.headerFooter.')]
    assert checks and all(item['passed'] for item in checks)
    assert len([item for item in checks if item['path'].endswith('.footer.right')]) == 3


@pytest.mark.parametrize('variant', ['first', 'even'])
def test_last_active_variant_font_corruption_is_not_hidden_by_matching_odd_font(styled_workbook, variant):
    def mutate(sheet):
        setattr(sheet.HeaderFooter, 'differentFirst' if variant == 'first' else 'differentOddEven', True)
        for kind in ('Header', 'Footer'):
            setattr(sheet, variant + kind, deepcopy(getattr(sheet, 'odd' + kind)))
        getattr(sheet, variant + 'Footer').right.size = 30

    _, capabilities = _check(styled_workbook, mutate)
    assert capabilities['xlsx.print.headerFooter.style.size'] == 'failed'
    for key in ('font', 'color', 'bold'):
        assert capabilities['xlsx.print.headerFooter.style.' + key] == 'verified'


def test_inactive_variant_content_does_not_fail_active_print_settings(styled_workbook):
    def mutate(sheet):
        sheet.HeaderFooter.differentFirst = False
        sheet.HeaderFooter.differentOddEven = False
        sheet.firstHeader.left.text = '未激活的首页'
        sheet.evenFooter.right.text = '未激活的偶数页'

    result, _ = _check(styled_workbook, mutate)
    checks = [item for item in result['checks'] if (item['path'] or '').startswith('xlsx.print.headerFooter.')]
    assert checks and all(item['passed'] for item in checks)


def test_disabled_header_footer_cannot_leave_residual_text_on_signature_sheet(styled_workbook):
    from openpyxl.worksheet.header_footer import HeaderFooterItem

    source, frozen = styled_workbook
    book = load_workbook(source)
    for sheet in book:
        sheet.oddHeader, sheet.oddFooter = HeaderFooterItem(), HeaderFooterItem()
    book['说明'].oddFooter.right.text = '应当关闭的说明页页脚'
    stream = BytesIO()
    book.save(stream)
    prefs = _preferences(enabled=False)
    result = readback(stream.getvalue(), 'xlsx', prefs, frozen)
    capabilities = {item['path']: item['status'] for item in _capabilities('xlsx', prefs, result, frozen)}
    assert capabilities['xlsx.print.headerFooter.enabled'] == 'failed'
    assert capabilities['xlsx.print.headerFooter.footer.right'] == 'failed'


def test_disabled_clean_header_footer_is_verified_without_fabricating_style_checks(styled_workbook):
    from openpyxl.worksheet.header_footer import HeaderFooterItem

    source, frozen = styled_workbook
    book = load_workbook(source)
    for sheet in book:
        sheet.oddHeader, sheet.oddFooter = HeaderFooterItem(), HeaderFooterItem()
    stream = BytesIO()
    book.save(stream)
    prefs = _preferences(enabled=False)
    result = readback(stream.getvalue(), 'xlsx', prefs, frozen)
    checks = [item for item in result['checks'] if (item['path'] or '').startswith('xlsx.print.headerFooter.')]
    assert checks and all(item['passed'] for item in checks)
    assert not any('.style.' in item['path'] for item in checks)


@pytest.mark.parametrize('side', ['header', 'footer'])
def test_one_millimeter_distance_drift_is_not_hidden_by_inch_tolerance(styled_workbook, side):
    def mutate(sheet):
        setattr(sheet.page_margins, side, getattr(sheet.page_margins, side) + 1 / 25.4)

    _, capabilities = _check(styled_workbook, mutate)
    assert capabilities['xlsx.print.headerFooter.' + side + 'Distance'] == 'failed'
