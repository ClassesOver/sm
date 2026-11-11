"""允许编辑区域从原生保存协议进入真实 Node 引擎后仍可由独立读者读取。"""
from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook

from smart_reporting.report_editor.native_office import patch_office


def test_native_save_roundtrips_editable_ranges_and_sheet_protection():
    workbook = Workbook()
    workbook.active['A1'] = '保留'
    stream = BytesIO()
    workbook.save(stream)
    saved = patch_office('xlsx', stream.getvalue(), [
        {'kind': 'setSheetEditableRanges', 'sheetName': 'Sheet', 'ranges': [{'name': '录入', 'sqref': 'B2:C4'}]},
        {'kind': 'protectSheet', 'sheetName': 'Sheet', 'protect': True},
    ])
    reopened = load_workbook(BytesIO(saved))
    assert reopened.active['A1'].value == '保留'
    assert reopened.active.protection.sheet is True
    with ZipFile(BytesIO(saved)) as package:
        xml = package.read('xl/worksheets/sheet1.xml').decode()
    assert '<protectedRange sqref="B2:C4" name="录入"/>' in xml
