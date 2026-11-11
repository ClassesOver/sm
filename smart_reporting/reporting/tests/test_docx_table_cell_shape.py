"""Cell merge/split must survive the real native bridge and preserve source XML."""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn

from scripts.probe_native_docx_tables import fixture
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'shape.docx'
    fixture(path)
    doc = Document(path)
    for r, row in enumerate(doc.tables[0].rows):
        for c, cell in enumerate(row.cells):
            cell.paragraphs[0]._p.set(qn('w:rsidR'), '00ABCDEF')
            cell.paragraphs[0].runs[0].text = f'{r}:{c} 中文😀$&'
            cell.add_paragraph('尾段')
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def anchor(content):
    return next(item for item in inspect_docx(content)['blocks'] if item['type'] == 'table')


def shape(content, steps):
    target = anchor(content)
    return patch_docx(content, [{'kind': 'reshapeTableCells', 'blockId': target['blockId'],
                                'expectedObjectSha256': target['expectedObjectSha256'], 'steps': steps}])


def merge(bottom=2, right=2):
    return {'kind': 'mergeTableCells', 'rect': {'top': 0, 'left': 0, 'bottom': bottom, 'right': right}}


def split(rows=2, columns=2):
    return {'kind': 'splitTableCells', 'rect': {'top': 0, 'left': 0, 'bottom': 2, 'right': 2},
            'rows': rows, 'columns': columns, 'mergeFirst': True}


def paragraphs(content):
    table = Document(BytesIO(content)).tables[0]
    return [p.xml for row in table._tbl.tr_lst for cell in row.tc_lst for p in cell.p_lst]


def test_merge_then_reopen_split_preserves_paragraph_xml_and_other_parts(source):
    assert anchor(source).get('cellShapeEditable') is True
    original_paragraphs = paragraphs(source)
    merged = shape(source, [merge()])
    model = Document(BytesIO(merged)).tables[0]
    assert model.cell(0, 0).text.split('\n') == ['0:0 中文😀$&', '尾段', '0:1 中文😀$&', '尾段',
                                                  '1:0 中文😀$&', '尾段', '1:1 中文😀$&', '尾段']
    assert all(p in paragraphs(merged) for p in original_paragraphs)
    assert anchor(merged)['cellShapeEditable'] is True
    restored = shape(merged, [split()])
    assert len(Document(BytesIO(restored)).tables[0].rows[0].cells) == 3
    assert Document(BytesIO(restored)).tables[0].cell(0, 1).text == ''
    assert all(p in paragraphs(restored) for p in original_paragraphs)
    for result in [merged, restored]:
        with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
            names = {n for n in before.namelist() if not n.endswith('/')}
            assert names == {n for n in after.namelist() if not n.endswith('/')}
            assert [n for n in names if before.read(n) != after.read(n)] == ['word/document.xml']


@pytest.mark.parametrize('steps', [[merge(99)], [{**merge(), 'xml': 'forged'}], [split(1, 1)],
                                 [{'kind': 'splitTableCells', 'rect': merge()['rect'], 'rows': True, 'columns': 2, 'mergeFirst': True}]])
def test_invalid_shape_requests_refused(source, steps):
    with pytest.raises(ValueError):
        shape(source, steps)


def test_same_table_shape_and_text_are_rejected_atomically(source):
    target = anchor(source)
    cell = target['cells'][0][0]
    op = {'kind': 'reshapeTableCells', 'blockId': target['blockId'],
          'expectedObjectSha256': target['expectedObjectSha256'], 'steps': [merge()]}
    text = {'kind': 'replaceCellText', 'blockId': target['blockId'], 'cellId': cell['cellId'],
            'expectedObjectSha256': cell['expectedObjectSha256'], 'text': 'ambiguous'}
    for batch in [[op, text], [text, op], [op, op]]:
        with pytest.raises(ValueError, match='batch_conflict'):
            patch_docx(source, batch)


@pytest.mark.parametrize(('bottom', 'right'), [(1, 2), (2, 1)])
def test_horizontal_and_vertical_merge_preserve_reading_order(source, bottom, right):
    result = shape(source, [merge(bottom, right)])
    expected = [value for r in range(bottom) for c in range(right) for value in [f'{r}:{c} 中文😀$&', '尾段']]
    assert Document(BytesIO(result)).tables[0].cell(0, 0).text.split('\n') == expected
    assert anchor(result)['cellShapeEditable'] is True


def test_split_plain_cell_expands_grid_and_preserves_neighbour_content(source):
    before = Document(BytesIO(source)).tables[0]
    step = {'kind': 'splitTableCells', 'rect': {'top': 0, 'left': 0, 'bottom': 1, 'right': 1},
            'rows': 3, 'columns': 2, 'mergeFirst': True}
    result = shape(source, [step])
    table = Document(BytesIO(result)).tables[0]
    assert len(table.rows) == 5
    assert len(table.columns) == 4
    assert table.cell(0, 0).text == before.cell(0, 0).text
    assert table.cell(0, 1).text == ''
    assert table.cell(2, 2).text == before.cell(0, 1).text
    assert table.cell(3, 0).text == before.cell(1, 0).text
    assert sum(anchor(result)['cellShapeWidthsTwips']) == sum(anchor(source)['cellShapeWidthsTwips'])


def test_same_save_merge_then_split_matches_source_semantics(source):
    result = shape(source, [merge(), split(1, 2)])
    cells = anchor(result)['cellShapeCells']
    assert cells[0] == {'top': 0, 'left': 0, 'bottom': 2, 'right': 1, 'physicalRow': 0, 'physicalColumn': 0}
    assert cells[1]['bottom'] == 2
    assert Document(BytesIO(result)).tables[0].cell(0, 1).text == ''


def test_stale_identity_and_protected_source_refuse_shape(source):
    target = anchor(source)
    op = {'kind': 'reshapeTableCells', 'blockId': target['blockId'],
          'expectedObjectSha256': 'wrong', 'steps': [merge()]}
    with pytest.raises(ValueError, match='anchor_invalid'):
        patch_docx(source, [op])
    from docx.oxml import OxmlElement
    doc = Document(BytesIO(source))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings.element.append(protection)
    out = BytesIO()
    doc.save(out)
    content = out.getvalue()
    assert anchor(content)['cellShapeEditable'] is False
    with pytest.raises(ValueError, match='protected'):
        shape(content, [merge()])
