"""九宫格对齐真实保存，保留非目标内容及隐藏合并续格。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source(merged=False):
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    for i, cell in enumerate(table._cells):
        cell.text = f'中文内容 {i}'
        cell.paragraphs[0]._p.set(qn('w:rsidR'), '12345678')
    if merged:
        table.cell(0, 0).merge(table.cell(1, 0))
        hidden = table._tbl.findall(qn('w:tr'))[1].findall(qn('w:tc'))[0]
        p = hidden.find(qn('w:p'))
        ppr = OxmlElement('w:pPr')
        jc = OxmlElement('w:jc')
        jc.set(qn('w:val'), 'right')
        ppr.append(jc)
        p.insert(0, ppr)
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def target(content):
    return next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')


def operation(content, vertical='center', horizontal='center', **bounds):
    block = target(content)
    return {'kind': 'setTableCellAlignment', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'],
            'steps': [{'top': 0, 'left': 0, 'bottom': 1, 'right': 1,
                       'vertical': vertical, 'horizontal': horizontal, **bounds}]}


def test_nine_alignments_save_reopen_without_rebuilding_runs_or_other_parts():
    original = source()
    assert target(original).get('cellAlignmentEditable') is True
    before_doc = Document(BytesIO(original))
    runs = [p._p.find(qn('w:r')).xml for cell in before_doc.tables[0]._cells for p in cell.paragraphs]
    content = original
    for vertical in ['top', 'center', 'bottom']:
        for horizontal in ['left', 'center', 'right']:
            content = patch_docx(content, [operation(content, vertical, horizontal)])
            table = Document(BytesIO(content)).tables[0]
            selected = table.cell(0, 0)
            valign = selected._tc.tcPr.find(qn('w:vAlign'))
            assert valign is None if vertical == 'top' else valign.get(qn('w:val')) == vertical
            ppr = selected.paragraphs[0]._p.pPr
            jc = None if ppr is None else ppr.find(qn('w:jc'))
            assert jc is None if horizontal == 'left' else jc.get(qn('w:val')) == horizontal
            assert selected.paragraphs[0]._p.get(qn('w:rsidR')) == '12345678'
            assert [p._p.find(qn('w:r')).xml for cell in table._cells for p in cell.paragraphs] == runs
            assert table.cell(0, 1)._tc.xml == before_doc.tables[0].cell(0, 1)._tc.xml
            with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(content)) as after:
                names = {name for name in before.namelist() if not name.endswith('/')}
                assert names == {name for name in after.namelist() if not name.endswith('/')}
                for name in names - {'word/document.xml'}:
                    assert before.read(name) == after.read(name)
            assert target(content)['cellAlignmentEditable'] is True


def test_lower_merged_slot_propagates_vertical_but_preserves_hidden_paragraph():
    content = source(merged=True)
    rows = Document(BytesIO(content)).tables[0]._tbl.findall(qn('w:tr'))
    hidden_before = rows[1].findall(qn('w:tc'))[0].find(qn('w:p')).xml
    result = patch_docx(content, [operation(content, 'bottom', 'center', top=1, bottom=2)])
    rows = Document(BytesIO(result)).tables[0]._tbl.findall(qn('w:tr'))
    for row in rows:
        cell = row.findall(qn('w:tc'))[0]
        assert cell.find(qn('w:tcPr')).find(qn('w:vAlign')).get(qn('w:val')) == 'bottom'
    assert rows[1].findall(qn('w:tc'))[0].find(qn('w:p')).xml == hidden_before


def test_visual_alignment_distinguishes_explicit_and_inferred_rtl():
    doc = Document(BytesIO(source()))
    cell = doc.tables[0].cell(0, 0)
    cell.text = 'LTR source'
    explicit = cell.add_paragraph('שלום עולם')
    explicit._p.get_or_add_pPr().append(OxmlElement('w:bidi'))
    cell.add_paragraph('שלום עולם')
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    for horizontal, expected in [('left', [None, 'right', 'left']),
                                 ('right', ['right', None, None]),
                                 ('center', ['center', 'center', 'center'])]:
        content = patch_docx(content, [operation(content, 'center', horizontal)])
        paragraphs = Document(BytesIO(content)).tables[0].cell(0, 0).paragraphs
        actual = []
        for paragraph in paragraphs:
            ppr = paragraph._p.pPr
            jc = None if ppr is None else ppr.find(qn('w:jc'))
            actual.append(None if jc is None else jc.get(qn('w:val')))
        assert actual == expected
        assert paragraphs[1]._p.pPr.find(qn('w:bidi')) is not None
        assert paragraphs[2]._p.pPr.find(qn('w:bidi')) is None


@pytest.mark.parametrize('patch', [{'vertical': 'baseline'}, {'horizontal': 'justify'},
                                  {'bottom': 3}, {'bidi': True}])
def test_invalid_alignment_steps_are_rejected(patch):
    content = source()
    op = operation(content)
    op['steps'][0].update(patch)
    with pytest.raises(ValueError):
        patch_docx(content, [op])


def test_alignment_identity_protection_and_independent_page_layout():
    content = source()
    op = operation(content)
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'expectedObjectSha256': '0' * 64}])
    section = inspect_docx(content)['sections'][0]
    layout = {'kind': 'setSectionLayout', 'sectionId': section['sectionId'],
              'expectedSectionSha256': section['expectedSectionSha256'], 'values': {'marginLeft': 2500}}
    result = patch_docx(content, [op, layout])
    assert target(result)['cellAlignments'][0] == 'center'
    doc = Document(BytesIO(content))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings._element.append(protection)
    buffer = BytesIO()
    doc.save(buffer)
    protected = buffer.getvalue()
    assert target(protected)['cellAlignmentEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(protected, [operation(protected)])


def test_same_table_alignment_and_direction_are_atomic_conflicts():
    content = source()
    op = operation(content)
    direction = {**op, 'kind': 'setTableCellTextDirection', 'steps': [
        {'top': 0, 'left': 0, 'bottom': 1, 'right': 1, 'direction': 'tbRl'},
    ]}
    for operations in [[op, direction], [direction, op], [op, op]]:
        with pytest.raises(ValueError, match='batch_conflict'):
            patch_docx(content, operations)


def test_self_closing_empty_paragraph_saves_alignment_inside_paragraph():
    original = source()
    with ZipFile(BytesIO(original)) as package:
        parts = {name: package.read(name) for name in package.namelist()}
    from lxml import etree
    root = etree.fromstring(parts['word/document.xml'])
    paragraph = root.find('.//' + qn('w:tc') + '/' + qn('w:p'))
    for child in list(paragraph):
        paragraph.remove(child)
    parts['word/document.xml'] = etree.tostring(root)
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as package:
        for name, data in parts.items():
            package.writestr(name, data)
    content = buffer.getvalue()
    result = patch_docx(content, [operation(content)])
    cell = Document(BytesIO(result)).tables[0].cell(0, 0)
    assert cell._tc.find(qn('w:pPr')) is None
    assert cell.paragraphs[0]._p.pPr.find(qn('w:jc')).get(qn('w:val')) == 'center'
    assert target(result)['cellAlignmentEditable'] is True
