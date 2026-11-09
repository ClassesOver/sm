from __future__ import annotations

import json
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.filters import CustomFilter, CustomFilters, DateGroupItem, FilterColumn, Filters


def _run_cli(request: dict) -> str:
    root = Path(__file__).resolve().parents[1] / 'workbook_engine'
    cli = root / 'dist' / 'cli.mjs'
    with tempfile.TemporaryDirectory(prefix='filter-cli-') as directory:
        request_path = Path(directory) / 'request.json'
        request_path.write_text(json.dumps(request), encoding='utf-8')
        result = subprocess.run(['node', str(cli), str(request_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def _inspect(path: Path) -> dict:
    return json.loads(_run_cli({'kind': 'inspect', 'input': str(path)}))


def test_cli_reads_openpyxl_filter_criteria_and_rewrites_them_with_openpyxl_readback(tmp_path):
    source_path = tmp_path / 'openpyxl-filter.xlsx'
    output_path = tmp_path / 'edited.xlsx'
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Data'
    sheet['A1'], sheet['B1'], sheet['C1'] = 'Name', 'Qty', 'Note'
    for row in range(2, 9):
        sheet.cell(row=row, column=1, value=f'item{row - 1}')
        sheet.cell(row=row, column=2, value=row - 1)
    sheet.auto_filter.ref = 'A1:C8'
    sheet.auto_filter.add_filter_column(0, ['item1', 'item2'], blank=True)
    sheet.auto_filter.filterColumn.append(
        FilterColumn(
            colId=1, customFilters=CustomFilters(customFilter=[CustomFilter(operator='greaterThan', val='4')]),
        ),
    )
    other = workbook.create_sheet('Other')
    other['A1'] = 'untouched'
    workbook.save(source_path)
    original = source_path.read_bytes()

    model = _inspect(source_path)
    filter_model = model['sheets'][0]['filter']
    assert filter_model.get('readOnlyReason') is None
    assert filter_model['ref'] == 'A1:C8'
    assert filter_model['columns'] == [
        {'colId': 0, 'values': ['item1', 'item2'], 'blank': True},
        {'colId': 1, 'customs': {'filters': [{'val': '4', 'operator': 'greaterThan'}]}},
    ]

    operation = {
        'kind': 'applySheetFilter', 'sheetName': 'Data',
        'filter': {
            'range': {'startRow': 0, 'endRow': 7, 'startColumn': 0, 'endColumn': 2},
            'columns': [
                {'colId': 0, 'values': ['item3'], 'blank': False},
                {'colId': 2, 'values': ['keep'], 'blank': True},
            ],
        },
        'hiddenRows': [2, 3],
    }
    _run_cli({'kind': 'patch', 'input': str(source_path), 'output': str(output_path), 'operations': [operation]})

    patched = output_path.read_bytes()
    readback = load_workbook(BytesIO(patched))
    auto_filter = readback['Data'].auto_filter
    assert auto_filter.ref == 'A1:C8'
    first = auto_filter.filterColumn[0]
    assert first.colId == 0
    assert list(first.filters.filter) == ['item3']
    assert not first.filters.blank
    second = auto_filter.filterColumn[1]
    assert second.colId == 2
    assert list(second.filters.filter) == ['keep']
    assert second.filters.blank
    assert len(readback['Data'].auto_filter.filterColumn) == 2
    assert readback['Other']['A1'].value == 'untouched'
    # The engine hid rows 3/4 (0-based 2/3) as the declared filter result.
    assert readback['Data'].row_dimensions[3].hidden
    assert readback['Data'].row_dimensions[4].hidden
    assert not readback['Data'].row_dimensions[1].hidden
    assert source_path.read_bytes() == original
    # Non-target parts stay byte-identical.
    before_zip, after_zip = ZipFile(BytesIO(original)), ZipFile(BytesIO(patched))
    assert before_zip.read('xl/worksheets/sheet2.xml') == after_zip.read('xl/worksheets/sheet2.xml')

    # Clearing removes the element and unhides the span's rows.
    cleared_path = tmp_path / 'cleared.xlsx'
    _run_cli({'kind': 'patch', 'input': str(output_path), 'output': str(cleared_path), 'operations': [
        {'kind': 'applySheetFilter', 'sheetName': 'Data', 'filter': None, 'hiddenRows': [], 'visibilityRange':
            {'startRow': 0, 'endRow': 7, 'startColumn': 0, 'endColumn': 2}},
    ]})
    final = load_workbook(cleared_path)
    assert not final['Data'].auto_filter.ref
    assert not final['Data'].row_dimensions[3].hidden
    assert final['Other']['A1'].value == 'untouched'
    assert source_path.read_bytes() == original


def test_cli_reads_openpyxl_date_group_filters_and_rewrites_them_with_openpyxl_readback(tmp_path):
    source_path = tmp_path / 'openpyxl-date-group.xlsx'
    output_path = tmp_path / 'edited.xlsx'
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Data'
    sheet['A1'], sheet['B1'] = 'Name', 'Day'
    for row in range(2, 9):
        sheet.cell(row=row, column=1, value=f'item{row - 1}')
        sheet.cell(row=row, column=2, value=row - 1)
    sheet.auto_filter.ref = 'A1:B8'
    sheet.auto_filter.add_filter_column(0, ['item1', 'item2'], blank=True)
    sheet.auto_filter.filterColumn.append(
        FilterColumn(
            colId=1,
            filters=Filters(dateGroupItem=[
                DateGroupItem(year=2024, month=1, day=15, dateTimeGrouping='day'),
                DateGroupItem(year=2023, dateTimeGrouping='year'),
            ]),
        ),
    )
    workbook.save(source_path)
    original = source_path.read_bytes()

    # The date-group column is a first-class read model citizen now: no
    # readOnlyReason, buckets surfaced per OOXML dateGroupItem semantics.
    model = _inspect(source_path)
    filter_model = model['sheets'][0]['filter']
    assert filter_model.get('readOnlyReason') is None
    assert filter_model['columns'] == [
        {'colId': 0, 'values': ['item1', 'item2'], 'blank': True},
        {'colId': 1, 'dateGroups': [
            {'year': 2024, 'month': 1, 'day': 15, 'dateTimeGrouping': 'day'},
            {'year': 2023, 'dateTimeGrouping': 'year'},
        ]},
    ]

    operation = {
        'kind': 'applySheetFilter', 'sheetName': 'Data',
        'filter': {
            'range': {'startRow': 0, 'endRow': 7, 'startColumn': 0, 'endColumn': 1},
            'columns': [
                {'colId': 0, 'values': ['item3']},
                {'colId': 1, 'dateGroups': [{'year': 2024, 'month': 2, 'dateTimeGrouping': 'month'}]},
            ],
        },
    }
    _run_cli({'kind': 'patch', 'input': str(source_path), 'output': str(output_path), 'operations': [operation]})

    readback = load_workbook(BytesIO(output_path.read_bytes()))
    auto_filter = readback['Data'].auto_filter
    assert auto_filter.ref == 'A1:B8'
    first, second = auto_filter.filterColumn
    assert list(first.filters.filter) == ['item3']
    groups = second.filters.dateGroupItem
    assert len(groups) == 1
    assert groups[0].year == 2024 and groups[0].month == 2
    assert groups[0].dateTimeGrouping == 'month'
    assert source_path.read_bytes() == original

    # Illegal date-group combinations are refused whole: an incomplete
    # granularity chain (grouping "day" without month+day) never writes.
    illegal_path = tmp_path / 'illegal.xlsx'
    with pytest.raises(AssertionError):
        _run_cli({'kind': 'patch', 'input': str(source_path), 'output': str(illegal_path), 'operations': [{
            'kind': 'applySheetFilter', 'sheetName': 'Data',
            'filter': {
                'range': {'startRow': 0, 'endRow': 7, 'startColumn': 0, 'endColumn': 1},
                'columns': [{'colId': 0, 'dateGroups': [{'year': 2024, 'dateTimeGrouping': 'day'}]}],
            },
        }]})
    assert not illegal_path.exists()
    assert source_path.read_bytes() == original


def test_cli_filter_rejects_contradictions_without_output_or_source_mutation(tmp_path):
    source_path = tmp_path / 'original.xlsx'
    original_path = tmp_path / 'seed.xlsx'
    workbook = Workbook()
    workbook.active['A1'] = 'Name'
    workbook.active['B1'] = 'Qty'
    workbook.save(original_path)
    original = original_path.read_bytes()

    base = {'kind': 'applySheetFilter', 'sheetName': 'Sheet',
            'filter': {'range': {'startRow': 0, 'endRow': 4, 'startColumn': 0, 'endColumn': 1}, 'columns': []}}
    contradictions = [
        {**base, 'filter': {**base['filter'], 'columns': [{'colId': 2, 'values': ['x']}]}},
        {**base, 'filter': {**base['filter'], 'columns': [
            {'colId': 0, 'values': ['a']}, {'colId': 0, 'values': ['b']}]}},
        {**base, 'hiddenRows': [9]},
    ]
    for operation in contradictions:
        output = tmp_path / 'must-not-exist.xlsx'
        with pytest.raises(AssertionError):
            _run_cli({'kind': 'patch', 'input': str(original_path), 'output': str(output), 'operations': [operation]})
        assert not output.exists()
    assert original_path.read_bytes() == original

    # A table-overlapping filter range is refused instead of written onto the sheet.
    from openpyxl.worksheet.table import Table, TableStyleInfo
    workbook2 = Workbook()
    sheet = workbook2.active
    sheet['A1'], sheet['B1'] = 'Name', 'Qty'
    for row in range(2, 5):
        sheet.cell(row=row, column=1, value=f'item{row}')
        sheet.cell(row=row, column=2, value=row)
    table = Table(displayName='Inventory', ref='A1:B4')
    table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True)
    sheet.add_table(table)
    table_path = tmp_path / 'tabled.xlsx'
    workbook2.save(table_path)
    with pytest.raises(AssertionError, match='表格|workbook_engine_failed'):
        _run_cli({'kind': 'patch', 'input': str(table_path), 'output': str(tmp_path / 'overlapped.xlsx'), 'operations': [
            {**base, 'filter': {'range': {'startRow': 0, 'endRow': 3, 'startColumn': 0, 'endColumn': 1}, 'columns': []}},
        ]})
    assert not (tmp_path / 'overlapped.xlsx').exists()
    assert source_path.with_name('tabled.xlsx').read_bytes() == table_path.read_bytes()
