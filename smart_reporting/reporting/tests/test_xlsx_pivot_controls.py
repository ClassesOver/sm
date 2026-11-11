"""通过真实 Node 保存桥验证原生控件关系。"""
from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook

from smart_reporting.report_editor.native_office import patch_office


def test_native_save_creates_slicer_with_cache_and_drawing():
    book = Workbook()
    for row in [['Region', 'Amount'], ['East', 10], ['West', 20]]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    saved = patch_office('xlsx', stream.getvalue(), [
        {'kind': 'addPivot', 'addition': {
            'worksheetSheetName': 'Sheet', 'sourceSheetName': 'Sheet',
            'sourceArea': {'startRow': 0, 'endRow': 2, 'startColumn': 0, 'endColumn': 1},
            'location': {'startRow': 0, 'endRow': 3, 'startColumn': 5, 'endColumn': 6},
            'name': 'Sales', 'fieldNames': ['Region', 'Amount'],
            'rowFieldIndices': [0], 'rowLevelItems': [['East', 'West']],
            'rowLines': [{'t': 'data', 'members': [0]}, {'t': 'data', 'members': [1]}], 'values': [{'fieldIndex': 1, 'agg': 'sum'}],
        }},
        {'kind': 'upsertPivotControl', 'request': {
            'kind': 'slicer', 'tablePath': 'xl/pivotTables/pivotTable1.xml',
            'field': 'Region', 'name': 'RegionSelector',
        }},
    ])
    reopened = load_workbook(BytesIO(saved))
    assert reopened.active._pivots[0].name == 'Sales'
    assert reopened.active['B2'].value == 10
    with ZipFile(BytesIO(saved)) as package:
        assert b'RegionSelector' in package.read('xl/slicers/slicer1.xml')
        assert b'pivotCacheId="' in package.read('xl/slicerCaches/slicerCache1.xml')
        assert b'slicerCaches' in package.read('xl/workbook.xml')
        assert b'graphicFrame' in package.read('xl/drawings/drawing1.xml')

    removed = patch_office('xlsx', saved, [{'kind': 'removePivotControl', 'request': {
        'tablePath': 'xl/pivotTables/pivotTable1.xml', 'name': 'RegionSelector',
    }}])
    with ZipFile(BytesIO(removed)) as package:
        assert 'xl/slicers/slicer1.xml' not in package.namelist()
        assert 'xl/slicerCaches/slicerCache1.xml' not in package.namelist()
        assert b'RegionSelector_Cache' not in package.read('xl/workbook.xml')
        assert b'slicerList' not in package.read('xl/worksheets/sheet1.xml')
    assert load_workbook(BytesIO(removed)).active._pivots[0].name == 'Sales'
