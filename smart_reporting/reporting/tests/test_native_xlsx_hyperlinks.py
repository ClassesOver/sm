"""XLSX 插入 ▸ 链接：前端产出的 applySheetHyperlinks 经真实引擎写回（固定源 xlsx-hyperlinks.ts），openpyxl / ZIP 独立回读。"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook

from smart_reporting.report_editor.native_office import patch_office


def _source() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '数据'
    sheet['A1'] = '官网'
    sheet['B1'] = '目录'
    sheet['C1'] = '已有链接'
    sheet['C1'].hyperlink = 'https://old.example/'
    other = workbook.create_sheet('汇总 表')
    other['A1'] = '保持不变'
    stream = BytesIO(); workbook.save(stream)
    return stream.getvalue()


def _op(*edits, sheet='数据'):
    return {'kind': 'applySheetHyperlinks', 'sheetName': sheet, 'edits': list(edits)}


def test_links_roundtrip_with_openpyxl_and_only_touch_the_sheet_and_its_rels():
    content = _source()
    edited = patch_office('xlsx', content, [_op(
        {'ref': 'A1', 'expectedTarget': None, 'target': 'https://example.com/?a=1&b=2'},
        {'ref': 'B1', 'expectedTarget': None, 'target': "#'汇总 表'!A1"},
        {'ref': 'C1', 'expectedTarget': 'https://old.example/', 'target': 'mailto:team@example.com'},
    )])
    sheet = load_workbook(BytesIO(edited))['数据']
    assert sheet['A1'].hyperlink.target == 'https://example.com/?a=1&b=2'
    assert sheet['B1'].hyperlink.location == "'汇总 表'!A1" and sheet['B1'].hyperlink.target is None
    assert sheet['C1'].hyperlink.target == 'mailto:team@example.com'
    assert [sheet[ref].value for ref in ('A1', 'B1', 'C1')] == ['官网', '目录', '已有链接']
    assert load_workbook(BytesIO(edited))['汇总 表']['A1'].value == '保持不变'
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(edited)) as after:
        changed = {name for name in after.namelist() if name not in before.namelist() or before.read(name) != after.read(name)}
        assert changed <= {'xl/worksheets/sheet1.xml', 'xl/worksheets/_rels/sheet1.xml.rels'}
        rels = after.read('xl/worksheets/_rels/sheet1.xml.rels').decode()
        assert 'https://old.example/' not in rels and rels.count('TargetMode="External"') == 2
    removed = patch_office('xlsx', edited, [_op({'ref': 'A1', 'expectedTarget': 'https://example.com/?a=1&b=2', 'target': None})])
    assert load_workbook(BytesIO(removed))['数据']['A1'].hyperlink is None


@pytest.mark.parametrize('edit', [
    {'ref': 'A1', 'expectedTarget': None, 'target': 'javascript:alert(1)'},
    {'ref': 'A1', 'expectedTarget': None, 'target': '#不存在!A1'},
    {'ref': 'C1', 'expectedTarget': None, 'target': 'https://new.example/'},
    {'ref': 'C1', 'expectedTarget': 'https://old.example/', 'target': 'https://old.example/'},
    {'ref': 'a1', 'expectedTarget': None, 'target': 'https://new.example/'},
    {'ref': 'A1', 'expectedTarget': None, 'target': 'https://new.example/', 'extra': 1},
])
def test_invalid_or_stale_link_edits_are_rejected(edit):
    with pytest.raises(ValueError):
        patch_office('xlsx', _source(), [_op(edit)])


def test_operation_shape_is_whitelisted():
    with pytest.raises(ValueError):
        patch_office('xlsx', _source(), [{**_op({'ref': 'A1', 'expectedTarget': None, 'target': 'https://a.example/'}), 'extra': 1}])
