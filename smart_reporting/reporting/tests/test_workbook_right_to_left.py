from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook

from smart_reporting.reporting.delivery.xlsx import inspect_workbook, patch_workbook


def test_right_to_left_roundtrip_preserves_cell_content_and_protected_sheet():
    book = Workbook()
    sheet = book.active
    sheet['A1'] = 'keep'
    sheet['B1'] = '=1+2'
    sheet.sheet_view.showRowColHeaders = False
    sheet.sheet_view.zoomScale = 125
    book.create_sheet('Protected').protection.sheet = True
    stream = BytesIO()
    book.save(stream)
    original = stream.getvalue()
    rtl = patch_workbook(original, [{
        'kind': 'applyPageSetups', 'setups': [{'sheetName': 'Sheet', 'rightToLeft': True}],
    }])
    assert inspect_workbook(rtl)['sheets'][0]['rightToLeft'] is True
    changed = patch_workbook(rtl, [{
        'kind': 'applyCellEdits', 'edits': [{
            'sheetName': 'Sheet', 'row': 0, 'column': 2, 'writeValue': True,
            'cell': {'value': 'new'},
        }],
    }])
    saved = load_workbook(BytesIO(changed))
    assert saved.active.sheet_view.rightToLeft is True
    assert saved.active.sheet_view.showRowColHeaders is False
    assert saved.active.sheet_view.zoomScale == 125
    assert saved.active['A1'].value == 'keep'
    assert saved.active['B1'].value == '=1+2'
    assert saved.active['C1'].value == 'new'
    assert saved['Protected'].protection.sheet is True
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(rtl)) as after:
        assert set(before.namelist()) == set(after.namelist())
        assert [name for name in before.namelist() if before.read(name) != after.read(name)] == [
            'xl/worksheets/sheet1.xml',
        ]
    ltr = patch_workbook(changed, [{
        'kind': 'applyPageSetups', 'setups': [{'sheetName': 'Sheet', 'rightToLeft': False}],
    }])
    assert inspect_workbook(ltr)['sheets'][0]['rightToLeft'] is False
    with ZipFile(BytesIO(ltr)) as package:
        assert b'rightToLeft=' not in package.read('xl/worksheets/sheet1.xml')
