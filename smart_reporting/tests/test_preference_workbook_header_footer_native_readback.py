"""只有完整原生包与全部打印区域见证能支撑页眉页脚字段V。"""

from copy import deepcopy
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.reporting.tests.test_workbook_header_footer_style import _preferences
from smart_reporting.reporting.tests.test_workbook_header_footer_style import (
    styled_workbook as styled_workbook,
)


def package(styled_workbook, mutate, member='xl/worksheets/sheet2.xml'):
    source, _ = styled_workbook
    result = BytesIO()
    with ZipFile(source) as original, ZipFile(result, 'w') as output:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == member:
                node = ElementTree.fromstring(data)
                mutate(node)
                data = ElementTree.tostring(node, encoding='utf-8', xml_declaration=True)
            output.writestr(item, data)
    return result.getvalue()


def test_native_header_footer_summary_witnesses_both_sheets_and_all_active_regions(styled_workbook):
    source, frozen = styled_workbook
    result = readback(source.read_bytes(), 'xlsx', _preferences(), frozen)
    summary = result['headerFooterReadback']
    assert summary['sourceStatus'] == 'verified' and summary['status'] == 'passed'
    assert summary['expectedSheets'] == summary['nativeSheets'] == summary['checkedSheets'] == 2
    assert summary['sheetNames'] == ['数据', '说明']
    assert len(summary['variants']) == 2
    for variant in summary['variants']:
        assert variant['variant'] == 'odd'
        assert len(variant['styledPositions']) == 5
    checks = [item for item in result['checks'] if item['path'] == 'xlsx.print.headerFooter.footer.right']
    assert all(item['evidenceKind'] == 'xlsx_native_header_footer_fields_v1' for item in checks)
    assert [item['evidenceObjects'] for item in checks] == [
        {'sheet': name, 'part': f'xl/worksheets/sheet{index}.xml', 'variant': 'odd', 'kind': 'footer', 'side': 'right'}
        for index, name in enumerate(('数据', '说明'), 1)]


@pytest.mark.parametrize('fault', ['duplicate_group', 'duplicate_footer', 'nested_markup', 'inline_size_reset'])
def test_ambiguous_or_incompletely_parsed_native_sections_cannot_get_complete_witness(styled_workbook, fault):
    def mutate(node):
        group = node.find('{*}headerFooter')
        footer = group.find('{*}oddFooter')
        if fault == 'duplicate_group':
            node.append(deepcopy(group))
        elif fault == 'duplicate_footer':
            group.append(deepcopy(footer))
        elif fault == 'nested_markup':
            ElementTree.SubElement(footer, '{urn:unexpected}format').text = '隐藏变化'
        else:
            # 最后字号仍为14，openpyxl会剥去前面的30并误认为全部14。
            footer.text = footer.text.replace('&P/&N', '&30&P/&14&N')

    _, frozen = styled_workbook
    result = readback(package(styled_workbook, mutate), 'xlsx', _preferences(), frozen)
    summary = result['headerFooterReadback']
    assert summary['sourceStatus'] == 'unverified'
    assert summary['status'] == 'unverified'
    assert result['status'] == 'failed'


def test_sheet_ids_are_unique_as_numbers_not_only_as_xml_strings(styled_workbook):
    def mutate(node):
        node.find('{*}sheets')[1].set('sheetId', '01')

    _, frozen = styled_workbook
    result = readback(package(styled_workbook, mutate, 'xl/workbook.xml'), 'xlsx', _preferences(), frozen)
    assert result['headerFooterReadback']['sourceStatus'] == 'unverified'


@pytest.mark.parametrize('fault', ['duplicate_relationship', 'aliased_part', 'duplicate_margins',
    'unknown_attribute', 'inline_font', 'inline_color', 'inline_bold', 'page_offset'])
def test_raw_package_ambiguities_never_grant_complete_group(styled_workbook, fault):
    member = 'xl/_rels/workbook.xml.rels' if fault in ('duplicate_relationship', 'aliased_part') else 'xl/worksheets/sheet2.xml'

    def mutate(node):
        if fault == 'duplicate_relationship':
            node.append(deepcopy(node[0]))
        elif fault == 'aliased_part':
            sheets = [item for item in node if item.get('Type', '').endswith('/worksheet')]
            sheets[1].set('Target', sheets[0].get('Target'))
        elif fault == 'duplicate_margins':
            node.append(deepcopy(node.find('{*}pageMargins')))
        elif fault == 'unknown_attribute':
            node.find('{*}headerFooter').set('unknown', '1')
        else:
            footer = node.find('{*}headerFooter/{*}oddFooter')
            code = {'inline_font': '&"Arial,Regular"', 'inline_color': '&KFF0000',
                'inline_bold': '&B', 'page_offset': '&P+1'}[fault]
            footer.text = footer.text.replace('&P/&N', code + '&P/&N')

    _, frozen = styled_workbook
    content = package(styled_workbook, mutate, member)
    if fault == 'unknown_attribute':
        # openpyxl先拒绝未知属性；直接核验原生包读器的拒证边界。
        from openpyxl import load_workbook

        from smart_reporting.management.preference_workbook_header_footer_readback import (
            read_header_footer_group,
        )

        checks = []
        summary = read_header_footer_group(content, load_workbook(styled_workbook[0]), _preferences(), frozen,
            lambda *args, **kwargs: checks.append((args, kwargs)))
        assert summary['sourceStatus'] == 'unverified' and checks[0][0][1] is False
        return
    result = readback(content, 'xlsx', _preferences(), frozen)
    assert result['headerFooterReadback']['sourceStatus'] == 'unverified'
    assert result['status'] == 'failed'


def test_each_field_owns_its_evidence_location(styled_workbook):
    source, frozen = styled_workbook
    result = readback(source.read_bytes(), 'xlsx', _preferences(), frozen)
    checks = result['checks']
    content = next(item for item in checks if item['path'] == 'xlsx.print.headerFooter.footer.right')
    style = next(item for item in checks if item['path'] == 'xlsx.print.headerFooter.style.font'
        and item['evidenceObjects'] == content['evidenceObjects'])
    content['evidenceObjects']['sheet'] = '损坏的证据'
    assert style['evidenceObjects']['sheet'] == '数据'


def test_section_parser_distinguishes_literal_fields_and_decodes_escapes_once():
    from smart_reporting.management.preference_workbook_header_footer_readback import _section

    prefix = '&L&"Noto Serif CJK SC,Bold"&14&K345678'
    assert _section(prefix + '&&P / &P / &N')['left']['text'] == '&&P / &P / &N'
    assert _section(prefix + '_x005F_x0041_')['left']['text'] == '_x0041_'


@pytest.mark.parametrize('fault', ['wrong_worksheet_type', 'duplicate_override', 'duplicate_default'])
def test_native_part_content_types_must_be_unique_and_match_used_parts(styled_workbook, fault):
    def mutate(node):
        if fault == 'duplicate_default':
            node.append(deepcopy(node.find('{*}Default')))
            return
        worksheet = next(item for item in node if item.get('PartName') == '/xl/worksheets/sheet2.xml')
        if fault == 'duplicate_override':
            node.append(deepcopy(worksheet))
        else:
            worksheet.set('ContentType', 'application/xml')

    _, frozen = styled_workbook
    result = readback(package(styled_workbook, mutate, '[Content_Types].xml'), 'xlsx', _preferences(), frozen)
    assert result['headerFooterReadback']['sourceStatus'] == 'unverified'


@pytest.mark.parametrize('identity', ['２', '4294967296'])
def test_sheet_ids_require_ascii_unsigned_int_identity(styled_workbook, identity):
    def mutate(node):
        node.find('{*}sheets')[1].set('sheetId', identity)

    _, frozen = styled_workbook
    result = readback(package(styled_workbook, mutate, 'xl/workbook.xml'), 'xlsx', _preferences(), frozen)
    assert result['headerFooterReadback']['sourceStatus'] == 'unverified'


@pytest.mark.parametrize('fault', ['unqualified_override', 'nested_declaration'])
def test_content_type_declarations_require_native_direct_elements(styled_workbook, fault):
    def mutate(node):
        part = next(item for item in node if item.get('PartName') == '/xl/worksheets/sheet2.xml')
        if fault == 'unqualified_override':
            part.tag = 'Override'
        else:
            ElementTree.SubElement(part, '{urn:unexpected}hidden')

    _, frozen = styled_workbook
    result = readback(package(styled_workbook, mutate, '[Content_Types].xml'), 'xlsx', _preferences(), frozen)
    assert result['headerFooterReadback']['sourceStatus'] == 'unverified'
