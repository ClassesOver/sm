"""单元格文字方向保留原段落与非目标部件。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    for i, cell in enumerate(table._cells):
        cell.text = f'原始中文 {i}'
        cell.paragraphs[0]._p.set(qn('w:rsidR'), '12345678')
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def target(content):
    return next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')


def operation(content, steps):
    block = target(content)
    return {'kind': 'setTableCellTextDirection', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'], 'steps': steps}


def test_cell_text_directions_save_reopen_and_clear_without_rebuilding_content():
    original = source()
    assert target(original).get('cellTextDirectionEditable') is True
    paragraphs = [p._p.xml for cell in Document(BytesIO(original)).tables[0]._cells for p in cell.paragraphs]
    content = original
    for direction in ['tbRl', 'btLr', 'lrTb']:
        content = patch_docx(content, [operation(content, [{'top': 0, 'left': 0, 'bottom': 2, 'right': 1, 'direction': direction}])])
        table = Document(BytesIO(content)).tables[0]
        for row in table.rows:
            tag = row.cells[0]._tc.tcPr.find(qn('w:textDirection'))
            assert tag is None if direction == 'lrTb' else tag.get(qn('w:val')) == direction
            assert row.cells[1]._tc.tcPr.find(qn('w:textDirection')) is None
        assert [p._p.xml for cell in table._cells for p in cell.paragraphs] == paragraphs
        with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(content)) as after:
            names = {name for name in before.namelist() if not name.endswith('/')}
            assert names == {name for name in after.namelist() if not name.endswith('/')}
            for name in names - {'word/document.xml'}:
                assert before.read(name) == after.read(name)


@pytest.mark.parametrize('step', [
    {'top': 0, 'left': 0, 'bottom': 2, 'right': 1, 'direction': 'unknown'},
    {'top': 0, 'left': 0, 'bottom': 3, 'right': 1, 'direction': 'tbRl'},
    {'top': 0, 'left': 0, 'bottom': 2, 'right': 1, 'direction': 'tbRl', 'xml': '<forged/>'},
])
def test_cell_text_direction_rejects_invalid_steps(step):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, [step])])


def test_direction_preserves_merged_owner_and_continuation_content():
    doc = Document(BytesIO(source()))
    table = doc.tables[0]
    table.cell(0, 0).merge(table.cell(1, 0))
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    # 触及合并owner的下半个slot也须按源selectedCells语义覆盖整个owner。
    result = patch_docx(content, [operation(content, [
        {'top': 1, 'left': 0, 'bottom': 2, 'right': 1, 'direction': 'btLr'},
    ])])
    physical = Document(BytesIO(result)).tables[0]._tbl.findall(qn('w:tr'))
    for row in physical:
        cell = row.findall(qn('w:tc'))[0]
        assert cell.find(qn('w:tcPr')).find(qn('w:textDirection')).get(qn('w:val')) == 'btLr'
    assert target(result)['cellTextDirections'][0] == 'btLr'


def test_direction_rejects_forged_identity_and_protection_but_allows_page_layout():
    from docx.oxml import OxmlElement
    content = source()
    steps = [{'top': 0, 'left': 0, 'bottom': 1, 'right': 1, 'direction': 'tbRl'}]
    op = operation(content, steps)
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'expectedObjectSha256': '0' * 64}])
    section = inspect_docx(content)['sections'][0]
    layout = {'kind': 'setSectionLayout', 'sectionId': section['sectionId'],
              'expectedSectionSha256': section['expectedSectionSha256'], 'values': {'marginLeft': 2500}}
    result = patch_docx(content, [op, layout])
    assert target(result)['cellTextDirections'][0] == 'tbRl'
    doc = Document(BytesIO(content))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings._element.append(protection)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    assert target(content)['cellTextDirectionEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, steps)])
