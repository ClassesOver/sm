"""行跨页仅修改直属 cantSplit，不重建行或丢失表格内容。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_table_row_height import source


def anchor(content):
    return next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')


def operation(content, steps):
    block = anchor(content)
    return {'kind': 'setTableRowBreaks', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'], 'steps': steps}


def test_row_break_toggle_preserves_cells_height_and_other_parts():
    content = source()
    assert anchor(content).get('rowBreakEditable') is True
    original = Document(BytesIO(content)).tables[0]
    cells = [[cell.xml for cell in row.tc_lst] for row in original._tbl.tr_lst]
    op = operation(content, [{'top': 0, 'bottom': 1, 'allowBreak': False}])
    result = patch_docx(content, [op])
    table = Document(BytesIO(result)).tables[0]
    assert table._tbl.tr_lst[0].trPr.find(qn('w:cantSplit')) is not None
    assert table._tbl.tr_lst[0].trPr.find(qn('w:trHeight')).xml == original._tbl.tr_lst[0].trPr.find(qn('w:trHeight')).xml
    assert [[cell.xml for cell in row.tc_lst] for row in table._tbl.tr_lst] == cells
    reset = patch_docx(result, [operation(result, [{'top': 0, 'bottom': 1, 'allowBreak': True}])])
    assert Document(BytesIO(reset)).tables[0]._tbl.tr_lst[0].trPr.find(qn('w:cantSplit')) is None
    assert anchor(reset)['rowBreakSource']['rows'][0]['cantSplit'] is False
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(result)) as after:
        parts = {item.filename for item in before.infolist() if not item.is_dir()}
        assert parts == {item.filename for item in after.infolist() if not item.is_dir()}
        for name in parts - {'word/document.xml'}:
            assert before.read(name) == after.read(name), name


def test_paired_cant_split_is_removed_instead_of_surviving_or_becoming_duplicate():
    doc = Document(BytesIO(source()))
    row = doc.tables[0]._tbl.tr_lst[0]
    row.trPr.insert(0, OxmlElement('w:cantSplit'))
    buffer = BytesIO()
    doc.save(buffer)
    output = BytesIO()
    with ZipFile(BytesIO(buffer.getvalue())) as original, ZipFile(output, 'w') as modified:
        for entry in original.infolist():
            value = original.read(entry.filename)
            if entry.filename == 'word/document.xml':
                value = value.replace(b'<w:cantSplit/>', b'<w:cantSplit></w:cantSplit>')
            modified.writestr(entry, value)
    content = output.getvalue()
    assert anchor(content)['rowBreakSource']['rows'][0]['cantSplit'] is True
    result = patch_docx(content, [operation(content, [{'top': 0, 'bottom': 1, 'allowBreak': True}])])
    assert Document(BytesIO(result)).tables[0]._tbl.tr_lst[0].trPr.find(qn('w:cantSplit')) is None


@pytest.mark.parametrize('step', [
    {'top': 0, 'bottom': 1, 'allowBreak': 1},
    {'top': -1, 'bottom': 1, 'allowBreak': True},
    {'top': 0, 'bottom': 3, 'allowBreak': True},
    {'top': 0, 'bottom': 1, 'allowBreak': True, 'xml': '<w:cantSplit/>'},
])
def test_invalid_row_break_steps_reject_atomically(step):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, [step])])


def test_row_breaks_identity_protection_batch_and_independent_section_layout():
    content = source()
    op = operation(content, [{'top': 0, 'bottom': 2, 'allowBreak': False}])
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'expectedObjectSha256': '0' * 64}])
    with pytest.raises(ValueError):
        patch_docx(content, [op, op])
    section = inspect_docx(content)['sections'][0]
    layout = {'kind': 'setSectionLayout', 'sectionId': section['sectionId'],
              'expectedSectionSha256': section['expectedSectionSha256'], 'values': {'marginLeft': 2500}}
    result = patch_docx(content, [op, layout])
    assert Document(BytesIO(result)).sections[0].left_margin.twips == 2500
    assert all(row['cantSplit'] for row in anchor(result)['rowBreakSource']['rows'])
    doc = Document(BytesIO(content))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings._element.append(protection)
    buffer = BytesIO()
    doc.save(buffer)
    protected = buffer.getvalue()
    assert anchor(protected)['rowBreakEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(protected, [operation(protected, op['steps'])])
