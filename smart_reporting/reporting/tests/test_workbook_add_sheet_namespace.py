"""新增工作表在 openpyxl 产出的工作簿上必须保持 workbook.xml 可解析。

openpyxl 把 xmlns:r 声明在每个 <sheet> 上而不是 <workbook> 根上；引擎新增的 <sheet>
若不自带声明，r:id 前缀未绑定，整本工作簿无法读取（真实浏览器验收发现）。
"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook

from smart_reporting.report_editor.native_office import patch_office


def test_added_sheet_declares_relationship_prefix_on_openpyxl_sources():
    book = Workbook()
    book.active.title = 'Summary'
    book.active['A1'] = 'alpha'
    stream = BytesIO()
    book.save(stream)
    source = stream.getvalue()
    assert b'<sheet xmlns:r=' in ZipFile(BytesIO(source)).read('xl/workbook.xml')
    patched = patch_office('xlsx', source, [
        {'kind': 'applySheetEdits', 'plan': {'renames': [], 'additions': [{'name': '新表'}], 'removals': [], 'order': ['Summary', '新表']}},
        {'kind': 'applyCellEdits', 'edits': [{'sheetName': '新表', 'row': 0, 'column': 0, 'writeValue': True, 'cell': {'value': 'copied'}}]},
    ])
    etree.fromstring(ZipFile(BytesIO(patched)).read('xl/workbook.xml'))
    reopened = load_workbook(BytesIO(patched))
    assert reopened.sheetnames == ['Summary', '新表']
    assert reopened['新表']['A1'].value == 'copied'
    assert reopened['Summary']['A1'].value == 'alpha'
