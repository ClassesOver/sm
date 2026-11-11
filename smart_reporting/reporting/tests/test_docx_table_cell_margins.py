"""整表默认边距不得覆盖已有单元格局部边距与内容。"""
from io import BytesIO

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    for i, cell in enumerate(table._cells):
        cell.text = f'边距中文 {i}'
        cell.paragraphs[0]._p.set(qn('w:rsidR'), '12345678')
    override = OxmlElement('w:tcMar')
    left = OxmlElement('w:left')
    left.set(qn('w:w'), '33')
    left.set(qn('w:type'), 'dxa')
    override.append(left)
    table.cell(0, 0)._tc.tcPr.append(override)
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def target(content):
    return next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')


def operation(content, margins):
    block = target(content)
    return {'kind': 'setTableCellMargins', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'], 'margins': margins}


def test_table_defaults_preserve_all_physical_cells_and_reopen_exact_twips():
    content = source()
    assert target(content).get('tableCellMarginsEditable') is True
    before = Document(BytesIO(content)).tables[0]
    original_cells = [cell._tc.xml for cell in before._cells]
    margins = {'top': 0, 'right': 131, 'bottom': 97, 'left': 177}
    result = patch_docx(content, [operation(content, margins)])
    table = Document(BytesIO(result)).tables[0]
    assert [cell._tc.xml for cell in table._cells] == original_cells
    defaults = table._tbl.tblPr.find(qn('w:tblCellMar'))
    assert defaults is not None
    for side, value in margins.items():
        node = defaults.find(qn('w:' + side))
        assert node.get(qn('w:w')) == str(value)
        assert node.get(qn('w:type')) == 'dxa'
    cleared = patch_docx(result, [operation(result, dict.fromkeys(margins, 0))])
    table = Document(BytesIO(cleared)).tables[0]
    assert [cell._tc.xml for cell in table._cells] == original_cells
    for node in table._tbl.tblPr.find(qn('w:tblCellMar')):
        assert node.get(qn('w:w')) == '0'


@pytest.mark.parametrize('margins', [
    {'top': -1, 'right': 0, 'bottom': 0, 'left': 0},
    {'top': 0, 'right': 0, 'bottom': 0, 'left': 28351},
    {'top': 0, 'right': 0, 'bottom': 0, 'left': 1.5},
    {'top': 0, 'right': 0, 'bottom': 0, 'left': 0, 'xml': 'fake'},
])
def test_table_margins_reject_invalid_values_atomically(margins):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, margins)])


def test_margins_reject_forged_identity_and_protection_but_allow_independent_page_layout():
    content = source()
    margins = {'top': 0, 'right': 131, 'bottom': 97, 'left': 177}
    op = operation(content, margins)
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'expectedObjectSha256': '0' * 64}])
    section = inspect_docx(content)['sections'][0]
    layout = {'kind': 'setSectionLayout', 'sectionId': section['sectionId'],
              'expectedSectionSha256': section['expectedSectionSha256'], 'values': {'marginLeft': 2500}}
    result = patch_docx(content, [op, layout])
    assert Document(BytesIO(result)).tables[0]._tbl.tblPr.find(qn('w:tblCellMar')) is not None
    doc = Document(BytesIO(content))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings._element.append(protection)
    buffer = BytesIO()
    doc.save(buffer)
    protected = buffer.getvalue()
    assert target(protected)['tableCellMarginsEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(protected, [operation(protected, margins)])
