"""单格边距显式覆盖与恢复继承必须在真实 DOCX 保存后保持一致。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_table_cell_margins import source


def target(content):
    return next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')


def operation(content, margins):
    block = target(content)
    return {'kind': 'setTableCellMarginOverrides', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'],
            'steps': [{'top': 0, 'left': 0, 'bottom': 1, 'right': 1, 'margins': margins}]}


def test_selected_cell_override_and_reset_preserve_other_cells_and_table_defaults():
    content = source()
    assert target(content).get('tableCellMarginOverridesEditable') is True
    before = Document(BytesIO(content)).tables[0]
    other_cells = [cell._tc.xml for cell in before._cells[1:]]
    defaults = before._tbl.tblPr.xml
    paragraphs = [p.xml for p in before.cell(0, 0)._tc.p_lst]
    margins = {'top': 0, 'right': 131, 'bottom': 97, 'left': 177}
    result = patch_docx(content, [operation(content, margins)])
    table = Document(BytesIO(result)).tables[0]
    assert table._tbl.tblPr.xml == defaults
    assert [cell._tc.xml for cell in table._cells[1:]] == other_cells
    assert [p.xml for p in table.cell(0, 0)._tc.p_lst] == paragraphs
    override = table.cell(0, 0)._tc.tcPr.find(qn('w:tcMar'))
    for side, value in margins.items():
        assert override.find(qn('w:' + side)).get(qn('w:w')) == str(value)
    reset = patch_docx(result, [operation(result, None)])
    table = Document(BytesIO(reset)).tables[0]
    assert table.cell(0, 0)._tc.tcPr.find(qn('w:tcMar')) is None
    assert [cell._tc.xml for cell in table._cells[1:]] == other_cells
    assert table._tbl.tblPr.xml == defaults
    snapshot = target(reset)['tableCellMarginOverridesSource']['cells'][0]
    assert snapshot['raw'] is None
    assert snapshot['effective'] == snapshot['resetEffective']


@pytest.mark.parametrize('change', [
    {'margins': {'top': -1, 'right': 0, 'bottom': 0, 'left': 0}},
    {'margins': {'top': 0, 'right': 0, 'bottom': 0, 'left': 28351}},
    {'margins': {'top': 0, 'right': 0, 'bottom': 0}},
    {'xml': '<w:tcMar/>'},
    {'right': 3},
])
def test_invalid_override_steps_are_rejected(change):
    content = source()
    op = operation(content, {'top': 0, 'right': 0, 'bottom': 0, 'left': 0})
    op['steps'][0].update(change)
    with pytest.raises(ValueError):
        patch_docx(content, [op])


def test_override_identity_protection_batch_conflict_and_independent_layout():
    content = source()
    op = operation(content, {'top': 0, 'right': 131, 'bottom': 97, 'left': 177})
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'expectedObjectSha256': '0' * 64}])
    with pytest.raises(ValueError):
        patch_docx(content, [op, operation(content, None)])
    section = inspect_docx(content)['sections'][0]
    layout = {'kind': 'setSectionLayout', 'sectionId': section['sectionId'],
              'expectedSectionSha256': section['expectedSectionSha256'], 'values': {'marginLeft': 2500}}
    result = patch_docx(content, [op, layout])
    assert Document(BytesIO(result)).sections[0].left_margin.twips == 2500
    assert target(result)['tableCellMarginOverridesSource']['cells'][0]['raw'] == op['steps'][0]['margins']
    doc = Document(BytesIO(content))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings._element.append(protection)
    buffer = BytesIO()
    doc.save(buffer)
    protected = buffer.getvalue()
    assert target(protected)['tableCellMarginOverridesEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(protected, [operation(protected, None)])


def test_lower_merged_slot_updates_all_physical_margins_without_losing_hidden_content():
    doc = Document(BytesIO(source()))
    table = doc.tables[0]
    table.cell(0, 0).merge(table.cell(1, 0))
    continuation = table._tbl.tr_lst[1].tc_lst[0]
    paragraph = continuation.p_lst[0]
    paragraph.set(qn('w:rsidR'), 'DEADBEEF')
    run = OxmlElement('w:r')
    text = OxmlElement('w:t')
    text.text = '合并续格隐藏内容必须保留'
    run.append(text)
    paragraph.append(run)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    before = Document(BytesIO(content)).tables[0]
    physical = [row.tc_lst[0] for row in before._tbl.tr_lst]
    paragraphs = [[p.xml for p in cell.p_lst] for cell in physical]
    op = operation(content, {'top': 0, 'right': 130, 'bottom': 96, 'left': 175})
    op['steps'][0].update(top=1, bottom=2)
    result = patch_docx(content, [op])
    reopened = Document(BytesIO(result)).tables[0]
    for index, row in enumerate(reopened._tbl.tr_lst):
        cell = row.tc_lst[0]
        assert [p.xml for p in cell.p_lst] == paragraphs[index]
        assert cell.tcPr.find(qn('w:tcMar')).find(qn('w:left')).get(qn('w:w')) == '175'
        assert row.tc_lst[1].xml == before._tbl.tr_lst[index].tc_lst[1].xml
    with ZipFile(BytesIO(content)) as original, ZipFile(BytesIO(result)) as saved:
        original_parts = {item.filename for item in original.infolist() if not item.is_dir()}
        assert original_parts == {item.filename for item in saved.infolist() if not item.is_dir()}
        for name in original_parts:
            if name != 'word/document.xml':
                assert saved.read(name) == original.read(name), name


def test_reset_reveals_row_inheritance_instead_of_clearing_padding_to_null():
    doc = Document(BytesIO(source()))
    row = doc.tables[0]._tbl.tr_lst[0]
    exception = OxmlElement('w:tblPrEx')
    margins = OxmlElement('w:tblCellMar')
    for side, value in {'top': 23, 'bottom': 17, 'left': 41}.items():
        node = OxmlElement('w:' + side)
        node.set(qn('w:w'), str(value))
        node.set(qn('w:type'), 'dxa')
        margins.append(node)
    exception.append(margins)
    row.insert(0, exception)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    signed = target(content)['tableCellMarginOverridesSource']['cells'][0]
    assert signed['raw'] == {'left': 33}
    assert signed['effective'] == {'top': 23, 'left': 33, 'bottom': 17}
    assert signed['resetEffective'] == {'top': 23, 'left': 41, 'bottom': 17}
    result = patch_docx(content, [operation(content, None)])
    reopened = target(result)['tableCellMarginOverridesSource']['cells'][0]
    assert reopened['rawPresent'] is False
    assert reopened['effective'] == signed['resetEffective']
    assert Document(BytesIO(result)).tables[0]._tbl.tr_lst[0].find(qn('w:tblPrEx')).xml == exception.xml


def test_reset_is_available_when_only_hidden_continuation_has_an_override():
    doc = Document(BytesIO(source()))
    table = doc.tables[0]
    table.cell(0, 0).merge(table.cell(1, 0))
    owner_props = table._tbl.tr_lst[0].tc_lst[0].tcPr
    owner_props.remove(owner_props.find(qn('w:tcMar')))
    hidden_props = table._tbl.tr_lst[1].tc_lst[0].tcPr
    override = OxmlElement('w:tcMar')
    left = OxmlElement('w:left')
    left.set(qn('w:w'), '71')
    left.set(qn('w:type'), 'dxa')
    override.append(left)
    hidden_props.append(override)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    signed = target(content)['tableCellMarginOverridesSource']['cells'][0]
    assert signed['rawPresent'] is False
    assert signed['hasPhysicalOverrides'] is True
    result = patch_docx(content, [operation(content, None)])
    for row in Document(BytesIO(result)).tables[0]._tbl.tr_lst:
        assert row.tc_lst[0].tcPr.find(qn('w:tcMar')) is None
    assert target(result)['tableCellMarginOverridesSource']['cells'][0]['hasPhysicalOverrides'] is False
