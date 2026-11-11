from io import BytesIO
import re
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.table import Table, TableStyleInfo

from smart_reporting.report_editor.native_office import patch_office


def source_book():
    book = Workbook()
    sheet = book.active
    sheet.append(['Name', 'Qty'])
    sheet.append(['Ada', 2])
    sheet.append(['Grace', 3])
    table = Table(displayName='Staff', ref='A1:B3')
    table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium4', showRowStripes=True)
    sheet.add_table(table)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def test_table_edits_write_real_file_metadata_and_preserve_other_parts():
    source = source_book()
    result = patch_office('xlsx', source, [{'kind': 'applyTableEdits', 'edits': [{
        'worksheetSheetName': 'Sheet', 'tableName': 'Staff', 'name': 'Employees',
        'columnNames': ['Employee', 'Qty'], 'style': 'TableStyleDark3', 'firstColumn': True,
    }]}])
    sheet = load_workbook(BytesIO(result)).active
    table = sheet.tables['Employees']
    assert table.id == 1
    assert [column.name for column in table.tableColumns] == ['Employee', 'Qty']
    assert table.tableStyleInfo.name == 'TableStyleDark3'
    assert table.tableStyleInfo.showFirstColumn is True
    assert list(sheet.values) == [('Name', 'Qty'), ('Ada', 2), ('Grace', 3)]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        for path in before.namelist():
            if path != 'xl/tables/table1.xml':
                assert after.read(path) == before.read(path)


def test_convert_table_to_range_keeps_values_and_removes_registration():
    result = patch_office('xlsx', source_book(), [{'kind': 'applyTableEdits', 'edits': [{
        'worksheetSheetName': 'Sheet', 'tableName': 'Staff', 'remove': True,
    }]}])
    sheet = load_workbook(BytesIO(result)).active
    assert not sheet.tables
    assert list(sheet.values) == [('Name', 'Qty'), ('Ada', 2), ('Grace', 3)]
    with ZipFile(BytesIO(result)) as archive:
        assert 'xl/tables/table1.xml' not in archive.namelist()


def test_new_headerless_table_accepts_one_data_row_and_preserves_cell_xml():
    book = load_workbook(BytesIO(source_book()))
    book.active['D1'] = 'single data row'
    output = BytesIO()
    book.save(output)
    source = output.getvalue()
    result = patch_office('xlsx', source, [{'kind': 'applyTableAdditions', 'additions': [{
        'worksheetSheetName': 'Sheet', 'name': 'OneRow',
        'area': {'startRow': 0, 'endRow': 0, 'startColumn': 3, 'endColumn': 3},
        'columnNames': ['Name'], 'style': 'TableStyleMedium2', 'bandedRows': True, 'headerRow': False,
    }]}])
    sheet = load_workbook(BytesIO(result)).active
    table = sheet.tables['OneRow']
    assert table.ref == 'D1:D1'
    assert table.headerRowCount == 0
    assert table.autoFilter is None
    assert [column.name for column in table.tableColumns] == ['Name']
    assert sheet['D1'].value == 'single data row'
    assert list(sheet.iter_rows(min_col=1, max_col=2, values_only=True)) == [('Name', 'Qty'), ('Ada', 2), ('Grace', 3)]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        assert after.read('xl/tables/table1.xml') == before.read('xl/tables/table1.xml')
        cells = rb'<c\b[^>]*(?:/>|>.*?</c>)'
        assert re.findall(cells, after.read('xl/worksheets/sheet1.xml')) == re.findall(cells, before.read('xl/worksheets/sheet1.xml'))


@pytest.mark.parametrize('edit', [
    {'worksheetSheetName': 'Sheet', 'tableName': 'Staff', 'worksheetPath': 'xl/foreign.xml'},
    {'worksheetSheetName': 'Other', 'tableName': 'Staff', 'remove': True},
    {'worksheetSheetName': 'Sheet', 'tableName': 'Staff', 'columnNames': ['Name', 'name']},
])
def test_invalid_table_edits_are_rejected(edit):
    with pytest.raises(ValueError):
        patch_office('xlsx', source_book(), [{'kind': 'applyTableEdits', 'edits': [edit]}])
