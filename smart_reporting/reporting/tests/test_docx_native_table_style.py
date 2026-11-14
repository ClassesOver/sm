"""表格样式库/表格样式选项/内置预设经真实 Python/Node 保存后，以独立 python-docx / ZIP+lxml 回读确认。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from lxml import etree

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_text_host import (
    NS,
    W,
    isolated_bundled_engine,
)


def _source() -> bytes:
    doc = Document()
    doc.add_paragraph('表格样式正文')
    table = doc.add_table(rows=3, cols=2)
    table.style = 'Table Grid'
    for r, values in enumerate([('项目', '金额'), ('收入', '100'), ('成本', '60')]):
        for c, value in enumerate(values):
            table.cell(r, c).text = value
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _tbl(content: bytes):
    with ZipFile(BytesIO(content)) as archive:
        root = etree.fromstring(archive.read('word/document.xml'))
    return root.xpath('//w:tbl', namespaces=NS)[0]


def _table_block(model):
    return next(block for block in model['blocks'] if block['type'] == 'table')


def _op(block, **fields):
    return {'kind': 'setTableStyle', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], **fields}


LOOK = {'firstRow': True, 'lastRow': True, 'firstColumn': False, 'lastColumn': False, 'bandedRows': False, 'bandedColumns': True}


def test_table_style_gallery_and_look_options_with_independent_readback(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source()
    model = docx_native.inspect_docx(source)
    ids = [style['styleId'] for style in model['tableStyles']]
    assert 'TableGrid' in ids and 'TableNormal' not in ids
    target = next(style_id for style_id in ids if style_id != 'TableGrid')
    block = _table_block(model)
    assert block['tableStyleEditable'] is True and block['tableStyleState']['styleId'] == 'TableGrid'

    saved = docx_native.patch_docx(source, [_op(block, styleId=target, look=LOOK)])
    tbl = _tbl(saved)
    assert tbl.xpath('./w:tblPr/w:tblStyle/@w:val', namespaces=NS) == [target]
    look = tbl.xpath('./w:tblPr/w:tblLook', namespaces=NS)[0]
    assert {key: look.get(f'{{{W}}}{key}') for key in ('firstRow', 'lastRow', 'firstColumn', 'lastColumn', 'noHBand', 'noVBand')} == \
        {'firstRow': '1', 'lastRow': '1', 'firstColumn': '0', 'lastColumn': '0', 'noHBand': '1', 'noVBand': '0'}
    reopened = Document(BytesIO(saved))
    assert reopened.tables[0].style.style_id == target
    assert [[cell.text for cell in row.cells] for row in reopened.tables[0].rows] == [['项目', '金额'], ['收入', '100'], ['成本', '60']]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(saved)) as after:
        changed = {name for name in before.namelist() if before.read(name) != after.read(name)}
        assert changed <= {'word/document.xml', 'docProps/core.xml'} and 'word/document.xml' in changed
    state = _table_block(docx_native.inspect_docx(saved))['tableStyleState']
    assert state['styleId'] == target and state['look'] == LOOK

    cleared = docx_native.patch_docx(saved, [_op(_table_block(docx_native.inspect_docx(saved)), styleId=None)])
    assert _tbl(cleared).xpath('./w:tblPr/w:tblStyle', namespaces=NS) == []


def test_builtin_preset_writes_direct_fills_and_borders(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source()
    block = _table_block(docx_native.inspect_docx(source))
    saved = docx_native.patch_docx(source, [_op(block, preset='blueBanded')])
    tbl = _tbl(saved)
    assert tbl.xpath('./w:tblPr/w:tblStyle', namespaces=NS) == []
    fills = [[(cell.xpath('./w:tcPr/w:shd/@w:fill', namespaces=NS) or [None])[0] for cell in row.xpath('./w:tc', namespaces=NS)] for row in tbl.xpath('./w:tr', namespaces=NS)]
    assert [[value.upper() for value in row] for row in fills] == [['BDD7EE'] * 2, ['DDEBF7'] * 2, ['FFFFFF'] * 2]
    for edge in tbl.xpath('./w:tr/w:tc/w:tcPr/w:tcBorders/*', namespaces=NS):
        assert (edge.get(f'{{{W}}}val'), edge.get(f'{{{W}}}sz'), edge.get(f'{{{W}}}color')) == ('single', '4', '9DC3E6')
    assert len(tbl.xpath('./w:tr/w:tc/w:tcPr/w:tcBorders/*', namespaces=NS)) >= 24


@pytest.mark.parametrize('fields', [{'styleId': 'NoSuchStyle'}, {'preset': 'rainbow'}, {'preset': 'grid', 'styleId': None}, {}, {'look': {'firstRow': True}}, {'expectedObjectSha256': 'f' * 64}, {'styleId': None, 'extra': 1}])
def test_invalid_or_stale_table_style_is_rejected(tmp_path, monkeypatch, fields):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source()
    block = _table_block(docx_native.inspect_docx(source))
    with pytest.raises(ValueError):
        docx_native.patch_docx(source, [_op(block, **fields)])
