"""applyCellShift：插入/删除单元格移位经真实引擎写回，openpyxl 独立回读。"""
from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from smart_reporting.report_editor.native_office import patch_office


def _source() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = 'Sheet1'
    for row in range(1, 4):
        for column, letter in enumerate('ABC', start=1):
            sheet.cell(row=row, column=column, value=f'{letter.lower()}{row}')
    sheet['A6'] = '=B2'
    sheet['A7'] = '=SUM(B1:B3)'
    other = book.create_sheet('Data')
    other['A1'] = '=Sheet1!B2'
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def test_insert_cells_shift_right_moves_only_the_band_and_follows_references():
    patched = patch_office('xlsx', _source(), [{'kind': 'applyCellShift', 'sheetName': 'Sheet1', 'range': 'B2', 'shift': 'right'}])
    book = load_workbook(BytesIO(patched))
    sheet = book['Sheet1']
    assert [sheet[f'{c}2'].value for c in 'ABCD'] == ['a2', None, 'b2', 'c2']
    assert [sheet['B1'].value, sheet['B3'].value] == ['b1', 'b3']
    assert sheet['A6'].value == '=C2'
    assert sheet['A7'].value == '=SUM(B1:B3)'
    assert book['Data']['A1'].value == '=Sheet1!C2'


def test_delete_cells_shift_up_and_protocol_validation():
    patched = patch_office('xlsx', _source(), [{'kind': 'applyCellShift', 'sheetName': 'Sheet1', 'range': 'B1:B2', 'shift': 'up'}])
    sheet = load_workbook(BytesIO(patched))['Sheet1']
    assert [sheet[f'B{r}'].value for r in (1, 2, 3)] == ['b3', None, None]
    assert sheet['A6'].value == '=#REF!'
    for bad in ({'range': 'B2', 'shift': 'sideways'}, {'range': 'Sheet1!B2', 'shift': 'right'}, {'range': 'B2', 'shift': 'right', 'extra': 1}):
        with pytest.raises(ValueError):
            patch_office('xlsx', _source(), [{'kind': 'applyCellShift', 'sheetName': 'Sheet1', **bad}])
