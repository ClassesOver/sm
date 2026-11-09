"""Real native bridge contracts for bounded, source-preserving table structure."""
from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from scripts.probe_native_docx_tables import fixture
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

KINDS = ['insertTableRow', 'deleteTableRow', 'insertTableColumn', 'deleteTableColumn']


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.docx'
    fixture(path)
    return path.read_bytes()


def table_anchor(content):
    return next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')


def operation(anchor, kind='insertTableRow', index=1, **extra):
    return {'kind': kind, 'blockId': anchor['blockId'],
            'expectedObjectSha256': anchor['expectedObjectSha256'], 'index': index, **extra}


def xml(node):
    return etree.tostring(node, method='c14n')


def modified(source, edit):
    doc = Document(BytesIO(source))
    edit(doc.tables[0])
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(('kind', 'index'), [(kind, index) for kind in KINDS for index in ([0, 1, 3] if kind.startswith('insert') else [0, 1, 2])])
def test_structure_preserves_original_paragraphs_and_renews_anchors(source, kind, index):
    anchor = table_anchor(source)
    assert anchor['structureEditable'] is True
    assert (anchor['rowCount'], anchor['columnCount']) == (3, 3)
    edited = patch_docx(source, [operation(anchor, kind, index)])
    before, after = Document(BytesIO(source)).tables[0], Document(BytesIO(edited)).tables[0]
    expected = [[cell.text for cell in row.cells] for row in before.rows]
    if kind == 'insertTableRow':
        expected.insert(index, ['', '', ''])
    elif kind == 'deleteTableRow':
        expected.pop(index)
    elif kind == 'insertTableColumn':
        for row in expected:
            row.insert(index, '')
    else:
        for row in expected:
            row.pop(index)
    assert [[cell.text for cell in row.cells] for row in after.rows] == expected
    paragraphs = {cell.text: [xml(p._p) for p in cell.paragraphs] for row in before.rows for cell in row.cells}
    for row in after.rows:
        for cell in row.cells:
            if cell.text:
                assert [xml(p._p) for p in cell.paragraphs] == paragraphs[cell.text]
    assert xml(before._tbl.tblPr) == xml(after._tbl.tblPr)
    fresh = table_anchor(edited)
    assert fresh['structureEditable'] is True
    assert fresh['blockId'] != anchor['blockId']
    assert fresh['cells'][-1][-1]['cellId'] != anchor['cells'][-1][-1]['cellId']
    with pytest.raises(ValueError, match='anchor_invalid'):
        patch_docx(edited, [operation(anchor)])
    old_cell = anchor['cells'][1][1]
    with pytest.raises(ValueError, match='anchor_invalid'):
        patch_docx(edited, [{'kind': 'replaceCellText', 'blockId': fresh['blockId'],
                             'cellId': old_cell['cellId'], 'expectedObjectSha256': old_cell['expectedObjectSha256'], 'text': 'wrong target'}])
    # New revision anchors remain usable; source coordinate IDs are never migrated.
    current = fresh['cells'][-1][-1]
    patched = patch_docx(edited, [{'kind': 'replaceCellText', 'blockId': fresh['blockId'],
                                 'cellId': current['cellId'], 'expectedObjectSha256': current['expectedObjectSha256'], 'text': 'fresh edit'}])
    assert Document(BytesIO(patched)).tables[0].rows[-1].cells[-1].text == 'fresh edit'


@pytest.mark.parametrize('extra', [{'index': -1}, {'index': 4}, {'index': True}, {'index': 1.5}, {'index': '1'}, {'xml': '<w:tbl/>'}, {'model': {}}, {'expectedObjectSha256': 'wrong'}])
def test_structure_rejects_invalid_or_untrusted_fields(source, extra):
    op = operation(table_anchor(source)) | extra
    with pytest.raises(ValueError):
        patch_docx(source, [op])


@pytest.mark.parametrize('cell_first', [False, True])
def test_same_table_structure_and_text_or_second_structure_conflict(source, cell_first):
    anchor = table_anchor(source)
    cell = anchor['cells'][0][0]
    text = {'kind': 'replaceCellText', 'blockId': anchor['blockId'], 'cellId': cell['cellId'],
            'expectedObjectSha256': cell['expectedObjectSha256'], 'text': 'ambiguous'}
    structure = operation(anchor)
    with pytest.raises(ValueError, match='batch_conflict'):
        patch_docx(source, [text, structure] if cell_first else [structure, text])
    with pytest.raises(ValueError, match='batch_conflict'):
        patch_docx(source, [structure, operation(anchor, 'deleteTableColumn')])


@pytest.mark.parametrize('fault', ['merge', 'nested', 'revision', 'hyperlink', 'auto', 'bad_width', 'row_attribute', 'unknown_property', 'disjoint_header', 'bookmark'])
def test_structure_gate_reports_reason_and_refuses_complex_source(source, fault):
    def edit(table):
        if fault == 'merge':
            table.cell(0, 0).merge(table.cell(0, 1))
        elif fault == 'nested':
            table.cell(0, 0).add_table(rows=1, cols=1)
        elif fault == 'revision':
            table.rows[0]._tr.get_or_add_trPr().append(OxmlElement('w:ins'))
        elif fault == 'hyperlink':
            table.cell(0, 0).paragraphs[0]._p.append(OxmlElement('w:hyperlink'))
        elif fault == 'auto':
            table.autofit = True
        elif fault == 'bad_width':
            table.cell(0, 0)._tc.get_or_add_tcPr().find(qn('w:tcW')).set(qn('w:w'), '100')
        elif fault == 'row_attribute':
            table.rows[0]._tr.set(qn('w:rsidR'), '12345678')
        elif fault == 'unknown_property':
            table._tbl.tblPr.append(OxmlElement('w:tblOverlap'))
        elif fault == 'disjoint_header':
            table.rows[2]._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
        else:
            table.cell(0, 0).paragraphs[0]._p.append(OxmlElement('w:bookmarkStart'))
    content = modified(source, edit)
    anchor = table_anchor(content)
    assert anchor['structureEditable'] is False
    assert anchor['structureReadOnlyReason'].startswith('docx_table_structure_')
    with pytest.raises(ValueError, match='docx_table_structure_'):
        patch_docx(content, [operation(anchor)])


@pytest.mark.parametrize('kind', ['deleteTableRow', 'deleteTableColumn'])
def test_last_dimension_cannot_be_deleted(source, kind):
    current = source
    for _ in range(2):
        current = patch_docx(current, [operation(table_anchor(current), kind, 0)])
    with pytest.raises(ValueError, match='last_dimension'):
        patch_docx(current, [operation(table_anchor(current), kind, 0)])


def test_insert_inside_header_prefix_keeps_it_contiguous_and_new_row_empty(source):
    result = patch_docx(source, [operation(table_anchor(source), 'insertTableRow', 0)])
    table = Document(BytesIO(result)).tables[0]
    assert [bool(row._tr.xpath('./w:trPr/w:tblHeader')) for row in table.rows] == [True, True, False, False]
    assert [cell.text for cell in table.rows[0].cells] == ['', '', '']
    assert not table.rows[0]._tr.xpath('./w:trPr/w:trHeight|./w:trPr/w:cantSplit')


def test_structure_on_different_tables_and_body_text_can_share_batch(source):
    doc = Document(BytesIO(source))
    second = doc.add_table(rows=1, cols=1)
    second.autofit = False
    second._tbl.tblPr.find(qn('w:tblW')).set(qn('w:type'), 'dxa')
    second._tbl.tblPr.find(qn('w:tblW')).set(qn('w:w'), str(second._tbl.tblGrid[0].get(qn('w:w'))))
    second.cell(0, 0).text = 'independent'
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    model = inspect_docx(content)
    tables = [block for block in model['blocks'] if block['type'] == 'table']
    paragraph = next(block for block in model['blocks'] if block['editable'])
    result = patch_docx(content, [operation(tables[0]), operation(tables[1], 'insertTableColumn', 1),
                                 {'kind': 'replaceParagraph', 'blockId': paragraph['blockId'],
                                  'expectedObjectSha256': paragraph['expectedObjectSha256'], 'text': 'body changed'}])
    after = Document(BytesIO(result))
    assert len(after.tables[0].rows) == 4
    assert [cell.text for cell in after.tables[1].rows[0].cells] == ['independent', '']
    assert after.paragraphs[0].text == 'body changed'


@pytest.mark.parametrize('kind', KINDS)
def test_duplicate_text_uses_source_coordinates_and_preserves_multiple_paragraphs(source, kind):
    def edit(table):
        for row in table.rows:
            for cell in row.cells:
                cell.paragraphs[0].runs[0].text = 'same text'
                cell.paragraphs[0].add_run(' mixed').italic = True
                cell.add_paragraph('second paragraph')
    content = modified(source, edit)
    before = Document(BytesIO(content)).tables[0]
    original = [[[xml(p._p) for p in cell.paragraphs] for cell in row.cells] for row in before.rows]
    rows, columns = [0, 1, 2], [0, 1, 2]
    ids = rows if kind.endswith('Row') else columns
    if kind.startswith('insert'):
        ids.insert(1, None)
    else:
        ids.pop(1)
    result = patch_docx(content, [operation(table_anchor(content), kind, 1)])
    after = Document(BytesIO(result)).tables[0]
    for ri, row in enumerate(after.rows):
        for ci, cell in enumerate(row.cells):
            if rows[ri] is None or columns[ci] is None:
                assert cell.text == ''
            else:
                assert [xml(p._p) for p in cell.paragraphs] == original[rows[ri]][columns[ci]]


def test_unsplittable_width_is_rejected_but_odd_width_keeps_total(source):
    def widths(table, values):
        for node, width in zip(table._tbl.tblGrid, values, strict=True):
            node.set(qn('w:w'), str(width))
        for row in table.rows:
            for cell, width in zip(row.cells, values, strict=True):
                cell._tc.get_or_add_tcPr().find(qn('w:tcW')).set(qn('w:w'), str(width))
    content = modified(source, lambda table: widths(table, [1, 3000, 5999]))
    with pytest.raises(ValueError, match='width_too_small'):
        patch_docx(content, [operation(table_anchor(content), 'insertTableColumn', 0)])
    content = modified(source, lambda table: widths(table, [2401, 3000, 3599]))
    result = patch_docx(content, [operation(table_anchor(content), 'insertTableColumn', 0)])
    after = Document(BytesIO(result)).tables[0]
    assert [node.get(qn('w:w')) for node in after._tbl.tblGrid] == ['1200', '1201', '3000', '3599']


def test_insert_respects_result_row_budget(source):
    from copy import deepcopy

    def edit(table):
        for _ in range(97):
            table._tbl.append(deepcopy(table.rows[-1]._tr))
    content = modified(source, edit)
    anchor = table_anchor(content)
    assert anchor['structureEditable'] is True
    with pytest.raises(ValueError, match='size_unsupported'):
        patch_docx(content, [operation(anchor, 'insertTableRow', 100)])


def test_structure_silent_write_failure_cannot_emit_output(source, tmp_path):
    import json
    import subprocess
    from pathlib import Path

    engine = Path(__file__).parents[1] / 'slides_engine'
    isolated = tmp_path / 'isolated'
    (isolated / 'bridge').mkdir(parents=True)
    for name in ('node_modules', 'packages', 'package.json'):
        (isolated / name).symlink_to(engine / name, target_is_directory=(engine / name).is_dir())
    (isolated / 'bridge/edit-docx.ts').write_text((engine / 'bridge/edit-docx.ts').read_text())
    helper = (engine / 'bridge/docx-table-structure.ts').read_text()
    assert 'return { xml, matrix, widths }' in helper
    (isolated / 'bridge/docx-table-structure.ts').write_text(helper.replace('return { xml, matrix, widths }', 'return { xml: source.originalXml, matrix, widths }'))
    input_file, output, request = tmp_path / 'source.docx', tmp_path / 'output.docx', tmp_path / 'request.json'
    input_file.write_bytes(source)
    request.write_text(json.dumps({'kind': 'patch', 'input': str(input_file), 'output': str(output),
                                   'operations': [operation(table_anchor(source))]}))
    result = subprocess.run([str(engine / 'node_modules/.bin/tsx'), str(isolated / 'bridge/edit-docx.ts'), str(request)],
                            cwd=isolated, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'docx_table_structure_write_not_applied' in result.stderr
    assert not output.exists()
    assert input_file.read_bytes() == source


def test_source_property_dollars_are_literal_data_during_xml_splice(source):
    extension = '{urn:native-table-probe}label'
    literal = "literal $& $` $'"

    def edit(table):
        table.cell(0, 0)._tc.get_or_add_tcPr().find(qn('w:shd')).set(extension, literal)
    content = modified(source, edit)
    result = patch_docx(content, [operation(table_anchor(content))])
    props = Document(BytesIO(result)).tables[0].cell(0, 0)._tc.get_or_add_tcPr()
    assert props.find(qn('w:shd')).get(extension) == literal


def restructure(anchor, steps, texts=None):
    op = {'kind': 'restructureTable', 'blockId': anchor['blockId'], 'expectedObjectSha256': anchor['expectedObjectSha256'], 'steps': steps}
    return {**op, 'texts': texts} if texts is not None else op


def test_restructure_composes_steps_and_final_cell_texts(source):
    anchor = table_anchor(source)
    before = [[cell.text for cell in row.cells] for row in Document(BytesIO(source)).tables[0].rows]
    steps = [{'kind': 'insertTableRow', 'index': 1}, {'kind': 'deleteTableColumn', 'index': 0},
             {'kind': 'insertTableColumn', 'index': 2}, {'kind': 'insertTableRow', 'index': 4}]
    texts = [{'row': 1, 'column': 0, 'text': '新行'}, {'row': 0, 'column': 1, 'text': '改写'}, {'row': 4, 'column': 2, 'text': '末格'}]
    edited = patch_docx(source, [restructure(anchor, steps, texts)])
    expected = [row[:] for row in before]
    expected.insert(1, ['', '', ''])
    expected = [row[1:] for row in expected]
    for row in expected:
        row.insert(2, '')
    expected.insert(4, ['', '', ''])
    expected[1][0], expected[0][1], expected[4][2] = '新行', '改写', '末格'
    table = Document(BytesIO(edited)).tables[0]
    assert [[cell.text for cell in row.cells] for row in table.rows] == expected
    # untouched source paragraphs keep their original XML
    original = Document(BytesIO(source)).tables[0]
    assert xml(table.rows[2].cells[1]._tc.p_lst[0]) == xml(original.rows[1].cells[2]._tc.p_lst[0])


@pytest.mark.parametrize('bad', [
    {'steps': []},
    {'steps': [{'kind': 'insertTableRow', 'index': 99}]},
    {'steps': [{'kind': 'mergeCells', 'index': 0}]},
    {'steps': [{'kind': 'insertTableRow', 'index': 0, 'extra': 1}]},
    {'steps': [{'kind': 'insertTableRow', 'index': 0}], 'texts': [{'row': 9, 'column': 0, 'text': 'x'}]},
    {'steps': [{'kind': 'insertTableRow', 'index': 0}], 'texts': [{'row': 0, 'column': 0, 'text': 'a'}, {'row': 0, 'column': 0, 'text': 'b'}]},
    {'steps': [{'kind': 'deleteTableRow', 'index': 0}] * 3},
])
def test_restructure_rejects_invalid_steps_and_texts(source, bad):
    anchor = table_anchor(source)
    with pytest.raises(ValueError):
        patch_docx(source, [{'kind': 'restructureTable', 'blockId': anchor['blockId'], 'expectedObjectSha256': anchor['expectedObjectSha256'], **bad}])
