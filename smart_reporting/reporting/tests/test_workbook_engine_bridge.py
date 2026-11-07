from __future__ import annotations

import hashlib
from io import BytesIO
from zipfile import ZipFile

from openpyxl import load_workbook


def test_workbook_roundtrip_preserves_types_formulas_styles_and_sources(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import (
        build_workbook,
        inspect_workbook,
        patch_workbook,
    )

    output = tmp_path / 'report.xlsx'
    built = build_workbook(
        output_path=output,
        title='部门经营汇总',
        period='2026-10',
        sheets=(
            {'name': '汇总', 'rows': [['部门经营汇总'], ['收入', {'value': 120.5, 'formula': "='经营报表'!B2"}]]},
            {'name': '经营报表', 'rows': [['项目', '金额', '缺失', '是否核实'], ['收入', 120.5, None, True]], 'headerRow': 0},
        ),
        source_mapping={'经营报表!B2': {'datasetId': 'sales', 'sha256': 'a' * 64, 'unit': '元'}},
    )
    original = output.read_bytes()
    assert built.sha256 == hashlib.sha256(original).hexdigest()
    assert built.size == len(original)
    book = load_workbook(BytesIO(original), data_only=False)
    assert book.sheetnames == ['汇总', '经营报表']
    assert book['汇总']['B2'].value == "='经营报表'!B2"
    assert load_workbook(BytesIO(original), data_only=True)['汇总']['B2'].value == 120.5
    assert book['经营报表']['B2'].value == 120.5
    assert book['经营报表']['C2'].value is None
    assert book['经营报表']['D2'].value is True
    assert book['经营报表']['A1'].font.bold
    assert book['经营报表'].freeze_panes == 'A2'
    assert book['经营报表'].page_setup.orientation == 'landscape'
    assert book['经营报表'].sheet_properties.pageSetUpPr.fitToPage
    assert book['经营报表'].page_setup.fitToHeight == 0
    assert 'smart-reporting/source-mapping.json' in ZipFile(BytesIO(original)).namelist()
    model = inspect_workbook(original)
    assert model['sheets'][1]['cells']['B2']['value'] == 120.5
    edited = patch_workbook(original, [
        {'kind': 'applyCellEdits', 'edits': [{'sheetName': '经营报表', 'row': 1, 'column': 1, 'writeValue': True, 'cell': {'value': 0}}]},
        {'kind': 'applySheetEdits', 'plan': {'renames': [{'sheetName': '经营报表', 'newName': '经营明细'}], 'additions': [], 'removals': [], 'order': ['汇总', '经营明细']}},
    ])
    changed = load_workbook(BytesIO(edited), data_only=False)
    assert changed['经营明细']['B2'].value == 0
    assert changed['汇总']['B2'].value == "='经营明细'!B2"
    assert changed['经营明细']['A1'].font.bold
    assert load_workbook(BytesIO(original))['经营报表']['B2'].value == 120.5


def test_workbook_patch_rejects_unknown_operation(tmp_path):
    import pytest

    from smart_reporting.reporting.delivery.xlsx import build_workbook, patch_workbook

    output = tmp_path / 'report.xlsx'
    build_workbook(output_path=output, title='汇总', period='', sheets=({'name': '汇总', 'rows': [['金额'], [0]]},))
    with pytest.raises(ValueError, match='workbook_operation_invalid'):
        patch_workbook(output.read_bytes(), [{'kind': 'unknown'}])


def test_workbook_merge_unmerge_can_be_saved_and_reopened(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import (
        build_workbook,
        inspect_workbook,
        patch_workbook,
    )

    output = tmp_path / 'report.xlsx'
    build_workbook(output_path=output, title='汇总', period='', sheets=(
        {'name': '汇总', 'rows': [['标题'], ['指标', 12.5]]},
    ))
    original = output.read_bytes()
    merged = patch_workbook(original, [{'kind': 'applySheetMerges', 'sheetName': '汇总', 'ranges': ['A1:C1']}])
    assert inspect_workbook(merged)['sheets'][0]['merges'] == ['A1:C1']
    sheet = load_workbook(BytesIO(merged))['汇总']
    assert str(sheet.merged_cells) == 'A1:C1'
    assert sheet['A1'].value == '标题'
    assert sheet['A1'].font.bold
    assert sheet['B2'].value == 12.5
    unmerged = patch_workbook(merged, [{'kind': 'applySheetMerges', 'sheetName': '汇总', 'ranges': []}])
    sheet = load_workbook(BytesIO(unmerged))['汇总']
    assert not sheet.merged_cells
    assert sheet['A1'].value == '标题'
    assert output.read_bytes() == original


def test_workbook_bridge_reuses_sort_structure_rules_table_pivot_and_page_setup(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import (
        build_workbook,
        inspect_workbook,
        patch_workbook,
    )

    output = tmp_path / 'report.xlsx'
    build_workbook(output_path=output, title='收入汇总', period='2026-10', sheets=(
        {'name': '明细', 'rows': [['部门', '收入'], ['乙', 20], ['甲', 10], ['乙', 5]]},
        {'name': '透视', 'rows': [['汇总']]},
    ))
    content = patch_workbook(output.read_bytes(), [
        {'kind': 'sortRange', 'sheetName': '明细', 'spec': {'range': 'A1:B4', 'byColumn': 'B', 'ascending': True, 'hasHeader': True}},
        {'kind': 'applyRowColumnOps', 'sheetName': '明细', 'ops': [{'kind': 'insert-rows', 'index': 4, 'count': 1}]},
        {'kind': 'applyTableAdditions', 'additions': [{'worksheetSheetName': '明细', 'area': {'startRow': 0, 'startColumn': 0, 'endRow': 3, 'endColumn': 1}, 'name': 'Revenue', 'columnNames': ['部门', '收入'], 'bandedRows': True}]},
        {'kind': 'applyDvRules', 'rules': [{'sheet': '明细', 'sqref': 'B2:B4', 'type': 'decimal', 'operator': 'greaterThanOrEqual', 'formula1': '0'}]},
        {'kind': 'applyCfRules', 'rules': [{'kind': 'dataBar', 'sheet': '明细', 'sqref': 'B2:B4', 'min': {'type': 'min'}, 'max': {'type': 'max'}, 'color': '#4472C4'}]},
        {'kind': 'applyPageSetups', 'setups': [{'sheetName': '明细', 'orientation': 'landscape', 'frozenRows': 1, 'printArea': 'A1:B4', 'fitToWidth': 1}]},
        {'kind': 'addPivot', 'addition': {
            'worksheetSheetName': '透视', 'sourceSheetName': '明细',
            'sourceArea': {'startRow': 0, 'startColumn': 0, 'endRow': 3, 'endColumn': 1},
            'location': {'startRow': 2, 'startColumn': 0, 'endRow': 5, 'endColumn': 1},
            'name': 'ByDepartment', 'fieldNames': ['部门', '收入'], 'rowFieldIndices': [0],
            'rowLevelItems': [['乙', '甲']], 'rowLines': [{'t': 'data', 'members': [0]}, {'t': 'data', 'members': [1]}],
            'values': [{'fieldIndex': 1, 'agg': 'sum'}],
        }},
        {'kind': 'refreshPivotCaches'},
    ])
    model = inspect_workbook(content)
    assert model['sheets'][0]['cells']['B2']['value'] == 5
    book = load_workbook(BytesIO(content))
    assert book['明细']['B3'].value == 10
    assert 'Revenue' in book['明细'].tables
    assert book['明细'].tables['Revenue'].autoFilter.ref == 'A1:B4'
    assert book['明细'].data_validations.count == 1
    assert len(book['明细'].conditional_formatting) == 1
    assert book['明细'].freeze_panes == 'A2'
    assert book['明细'].page_setup.orientation == 'landscape'
    assert book['透视']._pivots[0].name == 'ByDepartment'
    assert book['透视']['B4'].value == 25
    assert book['透视']['B5'].value == 10


def test_workbook_replacement_cell_edits_preserve_legacy_notes_and_untargeted_parts(tmp_path):
    """Official Univer replacements save as strict applyCellEdits, not a new writer."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment

    from smart_reporting.reporting.delivery.xlsx import patch_workbook

    output = tmp_path / 'replacement-source.xlsx'
    book = Workbook()
    sheet = book.active
    sheet.title = 'First'
    sheet['A1'] = 'before'
    sheet['B1'] = 42
    sheet['C1'] = True
    sheet['D1'] = '=B1+1'
    sheet['A1'].comment = Comment('existing note\n第二行', 'Original author')
    other = book.create_sheet('Other')
    other['A1'] = '=1+1'
    other['C3'] = 'untouched'
    other['C3'].comment = Comment('other note', 'Another author')
    book.save(output)
    original = output.read_bytes()
    changed = patch_workbook(original, [
        {'kind': 'applyCellEdits', 'edits': [
            {'sheetName': 'First', 'row': 0, 'column': 0, 'writeValue': True, 'cell': {'value': 'after'}},
            {'sheetName': 'Other', 'row': 0, 'column': 0, 'writeValue': True, 'cell': {'value': None, 'formula': '=2+2'}},
        ]},
    ])
    reread = load_workbook(BytesIO(changed), data_only=False)
    assert reread['First']['A1'].value == 'after'
    assert reread['Other']['A1'].value == '=2+2'
    assert reread['First']['B1'].value == 42
    assert reread['First']['B1'].data_type == 'n'
    assert reread['First']['C1'].value is True
    assert reread['First']['D1'].value == '=B1+1'
    assert reread['Other']['C3'].value == 'untouched'
    assert reread['First']['A1'].comment.text == 'existing note\n第二行'
    assert reread['First']['A1'].comment.author == 'Original author'
    assert reread['Other']['C3'].comment.author == 'Another author'
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(changed)) as after:
        touched = {'xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml', 'xl/workbook.xml'}
        assert set(before.namelist()) == set(after.namelist())
        for name in before.namelist():
            if name not in touched:
                assert after.read(name) == before.read(name), name
    assert output.read_bytes() == original


def test_workbook_custom_number_formats_preserve_untargeted_cells_and_general_reset(tmp_path):
    from copy import copy

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    from smart_reporting.reporting.delivery.xlsx import patch_workbook

    output = tmp_path / 'custom-number-format-source.xlsx'
    book = Workbook()
    sheet = book.active
    sheet.title = '明细'
    sheet['A1'] = 1234.567
    sheet['A1'].number_format = '#,##0.00'
    sheet['A1'].font = Font(name='Calibri', size=14, bold=True, color='123456')
    sheet['A1'].fill = PatternFill('solid', fgColor='DDEEFF')
    sheet['B1'] = '=A1*2'
    sheet['B1'].number_format = '0.00%'
    sheet['C7'] = '不变'
    sheet['C7'].font = Font(name='Arial', size=12, italic=True, color='654321')
    sheet['C7'].alignment = Alignment(horizontal='right', text_rotation=45)
    sheet['C7'].number_format = '@'
    book.create_sheet('其他')['D3'] = '=1+1'
    book.save(output)
    original = output.read_bytes()

    def apply_format(content, code):
        return patch_workbook(content, [{'kind': 'applyCellEdits', 'edits': [
            {'sheetName': '明细', 'row': 0, 'column': 0, 'writeValue': False, 'cell': {'value': None}, 'style': {'numberFormat': code}},
            {'sheetName': '明细', 'row': 0, 'column': 1, 'writeValue': False, 'cell': {'value': None}, 'style': {'numberFormat': code}},
        ]}])

    custom = '#,##0.000;[Red]-#,##0.000'
    changed = apply_format(original, custom)
    assert load_workbook(BytesIO(changed))['明细']['A1'].number_format == custom
    assert load_workbook(BytesIO(changed))['明细']['B1'].value == '=A1*2'
    reset = apply_format(changed, 'General')
    for content, expected_format in [(changed, custom), (reset, 'General')]:
        reread = load_workbook(BytesIO(content), data_only=False)
        for name in book.sheetnames:
            for row in book[name].iter_rows():
                for before in row:
                    after = reread[name][before.coordinate]
                    assert after.value == before.value
                    assert after.data_type == before.data_type
                    if name == '明细' and before.coordinate in {'A1', 'B1'}:
                        assert after.number_format == expected_format
                        assert copy(after.font) == copy(before.font)
                        assert copy(after.fill) == copy(before.fill)
                        assert copy(after.alignment) == copy(before.alignment)
                        assert copy(after.border) == copy(before.border)
                    else:
                        assert after._style == before._style or (after.has_style == before.has_style and after.number_format == before.number_format)
    assert output.read_bytes() == original


def test_workbook_page_setups_read_back_in_openpyxl_with_defaults_and_breaks(tmp_path):
    """Page Layout 族落盘后由 openpyxl 独立回读：方向/纸张/边距/打印区域/分页符。"""
    from smart_reporting.reporting.delivery.xlsx import (
        build_workbook,
        patch_workbook,
    )

    output = tmp_path / 'layout.xlsx'
    build_workbook(output_path=output, title='排版', period='2026-10', sheets=(
        {'name': '明细', 'rows': [['部门', '收入'], ['甲', 10], ['乙', 5]]},
    ))
    content = patch_workbook(output.read_bytes(), [
        {'kind': 'applyPageSetups', 'setups': [{
            'sheetName': '明细', 'orientation': 'landscape', 'paperSize': 9, 'scale': 85,
            'fitToWidth': 2, 'fitToHeight': 1, 'fitToPage': True, 'margins': 'narrow',
            'printGridlines': True, 'printHeadings': True,
            'printArea': 'A1:C10', 'printTitles': '1:1', 'rowBreaks': [3], 'colBreaks': [2],
        }]},
    ])
    book = load_workbook(BytesIO(content))
    sheet = book['明细']
    assert sheet.page_setup.orientation == 'landscape'
    assert sheet.page_setup.paperSize == 9
    assert sheet.page_setup.scale == 85
    assert sheet.page_setup.fitToWidth == 2
    # 引擎把 fitToHeight=1（OOXML 默认）收敛为缺省属性，openpyxl 读回 None。
    assert sheet.page_setup.fitToHeight is None
    assert sheet.sheet_properties.pageSetUpPr.fitToPage is True
    assert sheet.page_margins.left == 0.25 and sheet.page_margins.right == 0.25
    assert sheet.page_margins.top == 0.75 and sheet.page_margins.bottom == 0.75
    assert sheet.page_margins.header == 0.3 and sheet.page_margins.footer == 0.3
    assert sheet.print_options.gridLines is True
    assert sheet.print_options.headings is True
    assert '$A$1:$C$10' in str(sheet.print_area)
    assert sheet.print_title_rows == '$1:$1'
    assert [brk.id for brk in sheet.row_breaks.brk] == [3]
    assert [brk.id for brk in sheet.col_breaks.brk] == [2]
