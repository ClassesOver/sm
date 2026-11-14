"""完整表格属性族一次原生操作保存，保留正文及非目标部件。"""
import subprocess
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
import pytest
from docx import Document
from docx.oxml.ns import qn
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_table_row_height import source


@pytest.fixture(autouse=True)
def source_bridge(monkeypatch):
    from smart_reporting.reporting.delivery import docx_native
    root = Path(__file__).parents[1] / "doc_engine"
    def invoke(engine, script, request):
        return subprocess.run([str(root / "node_modules/.bin/tsx"), str(root / "bridge" / f"{script}.ts"), str(request)], cwd=root, capture_output=True, text=True, timeout=120)
    monkeypatch.setattr(docx_native, "run_bridge", invoke)


def anchor(content):
    return next(b for b in inspect_docx(content)['blocks'] if b['type'] == 'table')


def operation(content, patch=None):
    block = anchor(content)
    return {'kind': 'formatTableProperties', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'], 'patch': patch or {
                'table': {'autoFit': 'fixed', 'align': 'right', 'wrap': 'right',
                          'xTwips': -120, 'yTwips': 300, 'distanceTwips': 180,
                          'margins': {'top': 45, 'bottom': 65, 'left': 85, 'right': 105}},
                'rows': [{'index': 0, 'heightTwips': 540, 'heightRule': 'exact',
                          'cantSplit': True, 'repeatHeader': True}],
                'widthsTwips': [2100, 2400],
                'cells': [{'row': 1, 'column': 0, 'vAlign': 'bottom', 'noWrap': True,
                           'margins': {'top': 21, 'bottom': 31, 'left': 41, 'right': 51}}],
                'alt': {'title': '完整属性', 'description': '五个页签\n统一保存'},
            }}


def test_full_table_properties_single_operation_preserves_body_and_package():
    content = source()
    assert anchor(content).get('tablePropertiesEditable') is True
    result = patch_docx(content, [operation(content)])
    before = Document(BytesIO(content)).tables[0]._tbl
    table = Document(BytesIO(result)).tables[0]._tbl
    pr = table.tblPr
    assert pr.find(qn('w:jc')).get(qn('w:val')) == 'right'
    assert pr.find(qn('w:tblLayout')).get(qn('w:type')) == 'fixed'
    floating = pr.find(qn('w:tblpPr'))
    assert floating.get(qn('w:tblpX')) == '-120'
    assert floating.get(qn('w:tblpY')) == '300'
    assert floating.get(qn('w:leftFromText')) == '180'
    assert pr.find(qn('w:tblCaption')).get(qn('w:val')) == '完整属性'
    assert pr.find(qn('w:tblDescription')).get(qn('w:val')) == '五个页签\n统一保存'
    assert pr.find(qn('w:tblCellMar')).find(qn('w:left')).get(qn('w:w')) == '85'
    height = table.tr_lst[0].trPr.find(qn('w:trHeight'))
    assert (height.get(qn('w:val')), height.get(qn('w:hRule'))) == ('540', 'exact')
    assert table.tr_lst[0].trPr.find(qn('w:cantSplit')) is not None
    assert table.tr_lst[0].trPr.find(qn('w:tblHeader')) is not None
    cell = table.tr_lst[1].tc_lst[0]
    assert cell.tcPr.find(qn('w:vAlign')).get(qn('w:val')) == 'bottom'
    assert cell.tcPr.find(qn('w:noWrap')) is not None
    assert cell.tcPr.find(qn('w:tcMar')).find(qn('w:top')).get(qn('w:w')) == '21'
    assert [int(c.get(qn('w:w'))) for c in table.tblGrid] == [2100, 2400]
    assert [p.xml for tr in table.tr_lst for tc in tr.tc_lst for p in tc.p_lst] == [p.xml for tr in before.tr_lst for tc in tr.tc_lst for p in tc.p_lst]
    assert anchor(result)['tablePropertiesEditable'] is True
    with ZipFile(BytesIO(content)) as old, ZipFile(BytesIO(result)) as new:
        names = {n for n in old.namelist() if not n.endswith('/')}
        assert names == {n for n in new.namelist() if not n.endswith('/')}
        for name in names - {'word/document.xml'}:
            assert old.read(name) == new.read(name), name


@pytest.mark.parametrize('patch', [
    {'xml': '<w:tbl/>'}, {'table': {'wrap': 'bad'}},
    {'rows': [{'index': 0, 'heightTwips': -1, 'heightRule': 'exact'}]},
    {'rows': [{'index': 1, 'repeatHeader': True}]},
    {'cells': [{'row': 9, 'column': 0, 'noWrap': True}]},
    {'widthsTwips': [1, 2]}, {'alt': {'title': 'bad\nline', 'description': ''}},
])
def test_table_properties_rejects_invalid_controlled_patch(patch):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, patch)])
