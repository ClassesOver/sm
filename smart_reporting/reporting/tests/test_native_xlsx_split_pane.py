"""XLSX 视图 ▸ 拆分窗口：文件中的拆分窗格不得被当作冻结读取；取消拆分经真实引擎写回，openpyxl / ZIP 独立回读。"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.views import Pane, Selection

from smart_reporting.report_editor.native_office import inspect_office, patch_office

EXPECTED = {'xSplitTwips': 2400, 'ySplitTwips': 1200, 'topLeftCell': 'C5'}


def _source(state: str = 'split') -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '数据'
    sheet['A1'] = '标题'
    sheet['B2'] = 42
    sheet.sheet_view.zoomScale = 120
    if state == 'split':
        sheet.sheet_view.pane = Pane(xSplit=2400, ySplit=1200, topLeftCell='C5', activePane='bottomRight', state='split')
        sheet.sheet_view.selection = [Selection(pane='bottomRight', activeCell='C5', sqref='C5')]
    else:
        sheet.freeze_panes = 'B3'
    other = workbook.create_sheet('其他')
    other['A1'] = '保持不变'
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _sheet(content: bytes, name: str = '数据') -> dict:
    return next(sheet for sheet in inspect_office('xlsx', content)['sheets'] if sheet['name'] == name)


def test_split_pane_is_read_as_split_not_freeze_and_removed_with_readback():
    content = _source()
    before = _sheet(content)
    assert before['freeze'] is None
    assert before['splitPane'] == EXPECTED
    edited = patch_office('xlsx', content, [{'kind': 'removeSheetSplitPane', 'sheetName': '数据', 'expected': EXPECTED}])
    after = _sheet(edited)
    assert after['freeze'] is None and 'splitPane' not in after
    workbook = load_workbook(BytesIO(edited))
    view = workbook['数据'].sheet_view
    assert view.pane is None and view.zoomScale == 120
    assert [workbook['数据'][ref].value for ref in ('A1', 'B2')] == ['标题', 42]
    assert workbook['其他']['A1'].value == '保持不变'
    with ZipFile(BytesIO(content)) as old, ZipFile(BytesIO(edited)) as new:
        changed = {name for name in new.namelist() if old.read(name) != new.read(name)}
        assert changed == {'xl/worksheets/sheet1.xml'}
        assert set(old.namelist()) == set(new.namelist())
        assert 'pane' not in new.read('xl/worksheets/sheet1.xml').decode()


def test_frozen_panes_keep_their_row_and_column_counts():
    sheet = _sheet(_source('frozen'))
    assert sheet['freeze'] == {'frozenRows': 2, 'frozenColumns': 1}
    assert 'splitPane' not in sheet


@pytest.mark.parametrize('operation', [
    {'kind': 'removeSheetSplitPane', 'sheetName': '数据', 'expected': {**EXPECTED, 'xSplitTwips': 2401}},
    {'kind': 'removeSheetSplitPane', 'sheetName': '缺失', 'expected': EXPECTED},
    {'kind': 'removeSheetSplitPane', 'sheetName': '数据', 'expected': {**EXPECTED, 'extra': 1}},
    {'kind': 'removeSheetSplitPane', 'sheetName': '数据'},
])
def test_invalid_or_stale_removals_are_rejected(operation):
    with pytest.raises(ValueError):
        patch_office('xlsx', _source(), [operation])


def test_removal_without_split_pane_is_rejected():
    with pytest.raises(ValueError):
        patch_office('xlsx', _source('frozen'), [{'kind': 'removeSheetSplitPane', 'sheetName': '数据', 'expected': EXPECTED}])
