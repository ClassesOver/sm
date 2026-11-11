from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook

from smart_reporting.reporting.delivery.xlsx import inspect_workbook, patch_workbook


def test_headings_view_roundtrip_preserves_cells_and_other_package_parts():
    book = Workbook()
    book.active['A1'] = 'keep'
    book.create_sheet('Protected').protection.sheet = True
    stream = BytesIO()
    book.save(stream)
    original = stream.getvalue()
    hidden = patch_workbook(original, [{
        'kind': 'applyPageSetups',
        'setups': [{'sheetName': 'Sheet', 'showHeadings': False}],
    }])
    assert load_workbook(BytesIO(hidden)).active.sheet_view.showRowColHeaders is False
    assert inspect_workbook(hidden)['sheets'][0]['showHeadings'] is False
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(hidden)) as after:
        assert set(before.namelist()) == set(after.namelist())
        assert [name for name in before.namelist() if before.read(name) != after.read(name)] == [
            'xl/worksheets/sheet1.xml',
        ]
    shown = patch_workbook(hidden, [{
        'kind': 'applyPageSetups',
        'setups': [{'sheetName': 'Sheet', 'showHeadings': True}],
    }])
    assert inspect_workbook(shown)['sheets'][0]['showHeadings'] is True
    saved = load_workbook(BytesIO(shown))
    assert saved.active['A1'].value == 'keep'
    assert saved['Protected'].protection.sheet is True
