"""XLSX 页面布局 ▸ 主题/颜色/字体：前端产出的 setThemePart 经真实引擎写回，ZIP/openpyxl 独立回读。"""
from __future__ import annotations

import re
from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.styles.colors import Color

from smart_reporting.report_editor.native_office import inspect_office, patch_office

EMBER = ['#FFFFFF', '#2B1B14', '#F7EBE6', '#632B1A', '#C43E1C', '#E97132', '#FFC000', '#8A3B12', '#D98F73', '#A33517', '#C43E1C', '#954F72']


def _source() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '数据'
    sheet['A1'] = '主题色单元格'
    sheet['A1'].font = Font(color=Color(theme=4), scheme='minor')
    sheet['A1'].fill = PatternFill('solid', fgColor=Color(theme=5))
    sheet['B1'] = '显式 RGB'
    sheet['B1'].font = Font(color='FF123456')
    stream = BytesIO(); workbook.save(stream)
    return stream.getvalue()


def _op(**state):
    return {'kind': 'setThemePart', 'themePath': 'xl/theme/theme1.xml', 'state': state}


def test_theme_colors_and_fonts_rewrite_only_the_theme_part():
    content = _source()
    edited = patch_office('xlsx', content, [_op(colors={'name': 'Ember', 'values': EMBER}, fonts={'name': 'Trebuchet MS', 'major': 'Trebuchet MS', 'minor': 'Calibri'})])
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(edited)) as after:
        theme = after.read('xl/theme/theme1.xml').decode()
        assert re.search(r'<a:clrScheme name="Ember">', theme)
        assert '<a:accent1><a:srgbClr val="C43E1C"/></a:accent1>' in theme and '<a:dk1><a:srgbClr val="2B1B14"/></a:dk1>' in theme
        assert re.search(r'<a:majorFont>.*?<a:latin typeface="Trebuchet MS"', theme, re.S)
        for name in before.namelist():
            if name != 'xl/theme/theme1.xml':
                assert before.read(name) == after.read(name), name
    workbook = load_workbook(BytesIO(edited))
    sheet = workbook['数据']
    # 单元格仍引用主题槽位（Excel 打开时随新主题着色），显式 RGB 保持原样
    assert sheet['A1'].font.color.theme == 4 and sheet['A1'].fill.fgColor.theme == 5
    assert sheet['B1'].font.color.rgb == 'FF123456'
    assert inspect_office('xlsx', edited)['themePalette'] == EMBER


def test_fonts_only_keeps_palette():
    content = patch_office('xlsx', _source(), [_op(colors={'name': 'Ember', 'values': EMBER})])
    edited = patch_office('xlsx', content, [_op(fonts={'name': 'Arial', 'major': 'Arial', 'minor': 'Arial'})])
    theme = ZipFile(BytesIO(edited)).read('xl/theme/theme1.xml').decode()
    assert '<a:clrScheme name="Ember">' in theme and '<a:fontScheme name="Arial">' in theme


@pytest.mark.parametrize('operation', [
    {'kind': 'setThemePart', 'themePath': 'xl/styles.xml', 'state': {'colors': {'name': 'x', 'values': EMBER}}},
    _op(),
    _op(colors={'name': 'x', 'values': EMBER[:11]}),
    _op(fonts={'name': 'x', 'major': 'A\nB', 'minor': 'C'}),
    {**_op(colors={'name': 'x', 'values': EMBER}), 'extra': 1},
])
def test_invalid_theme_operations_are_rejected(operation):
    with pytest.raises(ValueError):
        patch_office('xlsx', _source(), [operation])
