"""XLSX 插入符号与上/下标：前端产出的 applyCellEdits 经真实引擎写回，openpyxl 独立回读。"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from smart_reporting.report_editor.native_office import patch_office


def _source() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '数据'
    sheet['A1'] = '价格'
    sheet['A2'] = 12.5
    sheet['B1'] = 'H2O'
    sheet['B1'].font = Font(name='Calibri', size=11, bold=True)
    sheet['C1'] = '=A2*2'
    other = workbook.create_sheet('其它')
    other['A1'] = '不变'
    stream = BytesIO(); workbook.save(stream)
    return stream.getvalue()


def _edit(row, column, value, *, write=True, style=None):
    item = {'sheetName': '数据', 'row': row, 'column': column, 'writeValue': write, 'cell': {'value': value}}
    if style is not None:
        item['style'] = style
    return item


def test_symbol_append_writes_text_and_keeps_other_cells():
    source = _source()
    edited = patch_office('xlsx', source, [{'kind': 'applyCellEdits', 'edits': [
        _edit(0, 0, '价格€'),      # 文字后追加
        _edit(1, 0, '12.5%'),      # 数字转为文本后追加（固定源 appendSymbol）
    ]}])
    sheet = load_workbook(BytesIO(edited))['数据']
    assert sheet['A1'].value == '价格€'
    assert sheet['A2'].value == '12.5%' and sheet['A2'].data_type == 's'
    assert sheet['B1'].value == 'H2O' and sheet['B1'].font.b is True
    assert sheet['C1'].value == '=A2*2'
    assert load_workbook(BytesIO(edited))['其它']['A1'].value == '不变'


@pytest.mark.parametrize('align', ['superscript', 'subscript'])
def test_vert_align_style_delta_roundtrips_and_baseline_clears(align):
    source = _source()
    edited = patch_office('xlsx', source, [{'kind': 'applyCellEdits', 'edits': [
        _edit(0, 1, 'H2O', write=False, style={'vertAlign': align}),
    ]}])
    cell = load_workbook(BytesIO(edited))['数据']['B1']
    assert cell.font.vertAlign == align
    assert cell.font.b is True and cell.font.name == 'Calibri' and cell.value == 'H2O'
    with ZipFile(BytesIO(edited)) as archive:
        assert f'<vertAlign val="{align}"/>' in archive.read('xl/styles.xml').decode()
    cleared = patch_office('xlsx', edited, [{'kind': 'applyCellEdits', 'edits': [
        _edit(0, 1, 'H2O', write=False, style={'vertAlign': 'baseline'}),
    ]}])
    cell = load_workbook(BytesIO(cleared))['数据']['B1']
    assert cell.font.vertAlign is None and cell.font.b is True


def test_invalid_vert_align_is_rejected():
    with pytest.raises(ValueError):
        patch_office('xlsx', _source(), [{'kind': 'applyCellEdits', 'edits': [
            _edit(0, 1, 'H2O', write=False, style={'vertAlign': 'raised'}),
        ]}])
