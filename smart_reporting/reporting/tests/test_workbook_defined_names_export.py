"""XLSX Formulas 名称管理器族（applyDefinedNames）openpyxl 独立回读。

与 test_workbook_engine_bridge.py 同款桥：build_workbook 造底稿，
patch_workbook 走真实引擎 applyWorkbookOperations，openpyxl 独立读回
xl/workbook.xml 的 definedNames 落盘与删除结果。
"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook


def _build(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import build_workbook

    output = tmp_path / 'report.xlsx'
    build_workbook(
        output_path=output,
        title='定义名称回读',
        period='2026',
        sheets=(
            {'name': '汇总', 'rows': [['标题'], ['收入', 120.5]]},
            {'name': '明细', 'rows': [['项目', '金额'], ['样例', 7]]},
        ),
    )
    return output.read_bytes()


def test_defined_names_persist_and_delete_survive_openpyxl_roundtrip(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import patch_workbook

    original = _build(tmp_path)
    assert load_workbook(BytesIO(original)).defined_names == {}

    added = patch_workbook(original, [
        {'kind': 'applyDefinedNames', 'plan': {'sets': [
            {'name': '收入额', 'refersTo': '明细!$B$2'},
            {'name': 'Rate2026', 'refersTo': "汇总!$A$1:$B$2"},
        ]}},
    ])
    book = load_workbook(BytesIO(added), data_only=False)
    assert book['明细'].cell(row=2, column=2).value == 7
    assert book.defined_names['收入额'].attr_text == '明细!$B$2'
    assert book.defined_names['Rate2026'].attr_text == '汇总!$A$1:$B$2'
    # 与 Excel 一致：名称判重大小写不敏感，XML 落盘原文保留。
    with ZipFile(BytesIO(added)) as archive:
        xml = archive.read('xl/workbook.xml').decode()
        assert '<definedName name="收入额">明细!$B$2</definedName>' in xml
        assert '<definedName name="Rate2026">汇总!$A$1:$B$2</definedName>' in xml

    # 同名换引用 = 原地替换；删除只移除对应条目，其余保留。
    replaced = patch_workbook(added, [
        {'kind': 'applyDefinedNames', 'plan': {'sets': [{'name': '收入额', 'refersTo': '明细!$B$2:$B$9'}]}},
    ])
    book = load_workbook(BytesIO(replaced))
    assert book.defined_names['收入额'].attr_text == '明细!$B$2:$B$9'
    assert 'Rate2026' in book.defined_names
    with ZipFile(BytesIO(replaced)) as archive:
        xml = archive.read('xl/workbook.xml').decode()
        assert xml.count('>明细!$B$2<') == 0

    removed = patch_workbook(replaced, [
        {'kind': 'applyDefinedNames', 'plan': {'removes': ['收入额']}},
    ])
    book = load_workbook(BytesIO(removed))
    assert '收入额' not in book.defined_names
    assert book.defined_names['Rate2026'].attr_text == '汇总!$A$1:$B$2'
    with ZipFile(BytesIO(removed)) as archive:
        xml = archive.read('xl/workbook.xml').decode()
        assert '收入额' not in xml
        assert '<definedNames>' in xml
    # 全局名删除后段内只剩工作表级 _xlnm.Print_Titles（引擎只管全局名，
    # sheet 级条目由 page-setup 维护）。
    cleared = patch_workbook(removed, [
        {'kind': 'applyDefinedNames', 'plan': {'removes': ['Rate2026']}},
    ])
    assert load_workbook(BytesIO(cleared)).defined_names == {}
    with ZipFile(BytesIO(cleared)) as archive:
        xml = archive.read('xl/workbook.xml').decode()
        assert 'Rate2026' not in xml
        assert '_xlnm.Print_Titles' in xml


def test_defined_names_reject_invalid_names_and_collisions(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import patch_workbook

    original = _build(tmp_path)
    for name in ('A1', '_xlnm.Print_Area', '1季度', 'R1C1'):
        with pytest.raises(Exception, match='不合法'):
            patch_workbook(original, [
                {'kind': 'applyDefinedNames', 'plan': {'sets': [{'name': name, 'refersTo': '明细!$B$2'}]}},
            ])
    seeded = patch_workbook(original, [
        {'kind': 'applyDefinedNames', 'plan': {'sets': [{'name': 'Rate', 'refersTo': '明细!$B$2'}]}},
    ])
    # 同一次操作中重复定义（大小写不敏感）被拒绝。
    with pytest.raises(Exception, match='重复定义'):
        patch_workbook(seeded, [
            {'kind': 'applyDefinedNames', 'plan': {'sets': [
                {'name': 'Rate', 'refersTo': '明细!$B$2'},
                {'name': 'rate', 'refersTo': '明细!$B$3'},
            ]}},
        ])
    # 同一次操作中同名既增又删被拒绝。
    with pytest.raises(Exception, match='同时出现在新增与删除'):
        patch_workbook(seeded, [
            {'kind': 'applyDefinedNames', 'plan': {
                'sets': [{'name': 'Rate', 'refersTo': '明细!$B$4'}], 'removes': ['rate'],
            }},
        ])
    # 原文件身份不被失败操作破坏。
    book = load_workbook(BytesIO(seeded))
    assert book.defined_names['Rate'].attr_text == '明细!$B$2'


def test_defined_names_coexist_with_print_area_and_survive_cell_patch(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import patch_workbook

    original = _build(tmp_path)
    seeded = patch_workbook(original, [
        {'kind': 'applyDefinedNames', 'plan': {'sets': [{'name': '明细区', 'refersTo': '明细!$A$1:$B$2'}]}},
        {'kind': 'applyPageSetups', 'setups': [{'sheetName': '明细', 'printArea': 'A1:B2'}]},
    ])
    book = load_workbook(BytesIO(seeded))
    # 工作表级 _xlnm.Print_Area 与全局名互不干扰。
    assert book.defined_names['明细区'].attr_text == '明细!$A$1:$B$2'
    with ZipFile(BytesIO(seeded)) as archive:
        xml = archive.read('xl/workbook.xml').decode()
        assert '_xlnm.Print_Area' in xml
        assert '<definedName name="明细区">明细!$A$1:$B$2</definedName>' in xml
    # 后续单元格修改不破坏 definedNames。
    patched = patch_workbook(seeded, [
        {'kind': 'applyCellEdits', 'edits': [
            {'sheetName': '明细', 'row': 2, 'column': 1, 'writeValue': True, 'cell': {'value': 9}},
        ]},
    ])
    book = load_workbook(BytesIO(patched), data_only=False)
    assert book['明细'].cell(row=3, column=2).value == 9
    assert book.defined_names['明细区'].attr_text == '明细!$A$1:$B$2'
