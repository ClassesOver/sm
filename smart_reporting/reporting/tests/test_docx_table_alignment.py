"""整表对齐仅修改直属 tblPr/jc，不重建表格及其他部件。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_table_cell_margins import source


def target(content):
    return next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')


def operation(content, alignment):
    block = target(content)
    return {'kind': 'setTableAlignment', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'], 'alignment': alignment}


def test_table_alignment_round_trip_preserves_cells_and_other_parts():
    content = source()
    assert target(content).get('tableAlignmentEditable') is True
    original_cells = [cell._tc.xml for cell in Document(BytesIO(content)).tables[0]._cells]
    for alignment, expected in [('center', WD_TABLE_ALIGNMENT.CENTER),
                                ('right', WD_TABLE_ALIGNMENT.RIGHT), ('left', None)]:
        result = patch_docx(content, [operation(content, alignment)])
        table = Document(BytesIO(result)).tables[0]
        assert table.alignment == expected
        assert [cell._tc.xml for cell in table._cells] == original_cells
        with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(result)) as after:
            parts = {item.filename for item in before.infolist() if not item.is_dir()}
            assert parts == {item.filename for item in after.infolist() if not item.is_dir()}
            for name in parts - {'word/document.xml'}:
                assert before.read(name) == after.read(name), name
        content = result


def test_rtl_alignment_preserves_indent_width_and_source_alias_is_removed():
    doc = Document(BytesIO(source()))
    props = doc.tables[0]._tbl.tblPr
    props.append(OxmlElement('w:bidiVisual'))
    jc = OxmlElement('w:jc')
    jc.set(qn('w:val'), 'end')
    props.append(jc)
    indent = OxmlElement('w:tblInd')
    indent.set(qn('w:w'), '-109')
    indent.set(qn('w:type'), 'dxa')
    props.append(indent)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    width = etree.tostring(props.find(qn('w:tblW')))
    result = patch_docx(content, [operation(content, 'left')])
    changed = Document(BytesIO(result)).tables[0]._tbl.tblPr
    assert changed.find(qn('w:jc')) is None
    assert etree.tostring(changed.find(qn('w:tblInd'))) == etree.tostring(indent)
    assert etree.tostring(changed.find(qn('w:tblW'))) == width
    assert changed.find(qn('w:bidiVisual')) is not None


@pytest.mark.parametrize('alignment', ['start', 'end', None, 1, 'CENTER'])
def test_invalid_alignment_is_rejected(alignment):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, alignment)])


def test_alignment_rejects_identity_protection_and_same_table_batch():
    content = source()
    op = operation(content, 'center')
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'expectedObjectSha256': '0' * 64}])
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'xml': '<w:jc/>'}])
    with pytest.raises(ValueError):
        patch_docx(content, [op, operation(content, 'right')])
    doc = Document(BytesIO(content))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings._element.append(protection)
    buffer = BytesIO()
    doc.save(buffer)
    protected = buffer.getvalue()
    assert target(protected)['tableAlignmentEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(protected, [operation(protected, 'center')])


def test_alignment_coexists_with_independent_section_layout_and_preserves_float_position():
    doc = Document(BytesIO(source()))
    positioning = OxmlElement('w:tblpPr')
    for key, value in {'tblpX': '777', 'tblpY': '111', 'horzAnchor': 'margin', 'vertAnchor': 'text'}.items():
        positioning.set(qn('w:' + key), value)
    doc.tables[0]._tbl.tblPr.insert(0, positioning)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    signed = target(content)
    assert signed['tableAlignmentEditable'] is True
    assert signed['tableAlignmentSource']['positioning'] == 'floating'
    section = inspect_docx(content)['sections'][0]
    layout = {'kind': 'setSectionLayout', 'sectionId': section['sectionId'],
              'expectedSectionSha256': section['expectedSectionSha256'], 'values': {'marginLeft': 2500}}
    result = patch_docx(content, [operation(content, 'right'), layout])
    table = Document(BytesIO(result)).tables[0]
    assert table.alignment == WD_TABLE_ALIGNMENT.RIGHT
    assert etree.tostring(table._tbl.tblPr.find(qn('w:tblpPr'))) == etree.tostring(positioning)
    assert Document(BytesIO(result)).sections[0].left_margin.twips == 2500
