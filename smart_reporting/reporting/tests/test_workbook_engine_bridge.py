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
