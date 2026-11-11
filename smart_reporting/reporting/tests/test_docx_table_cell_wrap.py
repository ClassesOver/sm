"""单元格换行只修改 noWrap；保留隐藏续格、tcFitText 与非目标部件。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_table_row_height import source


def anchor(content):
    return next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')


def operation(content, steps):
    block = anchor(content)
    return {'kind': 'setTableCellWrap', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'], 'steps': steps}


def step(wrap):
    return {'top': 0, 'left': 0, 'bottom': 1, 'right': 1, 'wrap': wrap}


def test_cell_wrap_changes_only_target_property_and_preserves_parts():
    content = source()
    assert anchor(content).get('tableCellWrapEditable') is True
    result = patch_docx(content, [operation(content, [step(False)])])
    before = Document(BytesIO(content)).tables[0]._tbl
    after = Document(BytesIO(result)).tables[0]._tbl
    target = after.tr_lst[0].tc_lst[0]
    assert target.tcPr.find(qn('w:noWrap')) is not None
    target.tcPr.remove(target.tcPr.find(qn('w:noWrap')))
    assert etree.tostring(after) == etree.tostring(before)
    with ZipFile(BytesIO(content)) as old, ZipFile(BytesIO(result)) as new:
        names = {i.filename for i in old.infolist() if not i.is_dir()}
        assert names == {i.filename for i in new.infolist() if not i.is_dir()}
        for name in names - {'word/document.xml'}:
            assert old.read(name) == new.read(name), name
    reset = patch_docx(result, [operation(result, [step(True)])])
    assert anchor(reset)['tableCellWrapSource']['cells'][0]['noWrap'] is False


def test_cell_wrap_preserves_hidden_continuation_text_and_fit_text():
    doc = Document(BytesIO(source()))
    table = doc.tables[0]
    table.cell(0, 0).merge(table.cell(1, 0))
    physical = [row.tc_lst[0] for row in table._tbl.tr_lst]
    for index, cell in enumerate(physical):
        cell.get_or_add_tcPr().append(OxmlElement('w:tcFitText'))
        cell.get_or_add_tcPr().append(OxmlElement('w:noWrap'))
        run = OxmlElement('w:r')
        text = OxmlElement('w:t')
        text.text = f'physical-hidden-{index}'
        run.append(text)
        cell.p_lst[0].append(run)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    result = patch_docx(content, [operation(content, [{**step(True), 'bottom': 2}])])
    with ZipFile(BytesIO(content)) as old, ZipFile(BytesIO(result)) as new:
        before, after = old.read('word/document.xml'), new.read('word/document.xml')
        assert after == before.replace(b'<w:noWrap/>', b'')
        assert b'physical-hidden-1' in after
        assert after.count(b'<w:tcFitText/>') == 2


@pytest.mark.parametrize('change', [
    {'wrap': 1}, {'left': -1}, {'right': 99}, {'xml': '<w:noWrap/>'},
])
def test_cell_wrap_rejects_invalid_steps(change):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, [{**step(False), **change}])])


def test_cell_wrap_rejects_foreign_hash_duplicate_and_protection():
    content = source()
    op = operation(content, [step(False)])
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'expectedObjectSha256': '0' * 64}])
    with pytest.raises(ValueError):
        patch_docx(content, [op, op])
    doc = Document(BytesIO(content))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings._element.append(protection)
    buffer = BytesIO()
    doc.save(buffer)
    protected = buffer.getvalue()
    assert anchor(protected)['tableCellWrapEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(protected, [operation(protected, [step(False)])])


def test_cell_wrap_reversed_tables_survive_paragraph_index_changes_and_section_edit():
    doc = Document(BytesIO(source()))
    doc.add_paragraph('delete this paragraph')
    second = doc.add_table(rows=1, cols=1)
    second.cell(0, 0).text = 'second table'
    second.cell(0, 0)._tc.get_or_add_tcPr().append(OxmlElement('w:noWrap'))
    doc.add_paragraph('insert anchor')
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    model = inspect_docx(content)
    tables = [b for b in model['blocks'] if b['type'] == 'table']
    paragraphs = [b for b in model['blocks'] if b['type'] == 'paragraph']
    def identity(block):
        return {key: block[key] for key in ('blockId', 'expectedObjectSha256')}
    section = model['sections'][0]
    ops = [
        {'kind': 'setTableCellWrap', **identity(tables[1]), 'steps': [step(True)]},
        {'kind': 'setTableCellWrap', **identity(tables[0]), 'steps': [step(False)]},
        {'kind': 'deleteParagraph', **identity(paragraphs[0])},
        {'kind': 'insertParagraph', **identity(paragraphs[-1]), 'position': 'before', 'text': 'inserted'},
        {'kind': 'setSectionLayout', 'sectionId': section['sectionId'],
         'expectedSectionSha256': section['expectedSectionSha256'], 'values': {'marginLeft': 2500}},
    ]
    result = Document(BytesIO(patch_docx(content, ops)))
    assert result.tables[0]._tbl.tr_lst[0].tc_lst[0].tcPr.find(qn('w:noWrap')) is not None
    assert result.tables[1]._tbl.tr_lst[0].tc_lst[0].tcPr.find(qn('w:noWrap')) is None
    assert result.tables[1].cell(0, 0).text == 'second table'
    assert [p.text for p in result.paragraphs] == ['inserted', 'insert anchor']
    assert result.sections[0].left_margin.twips == 2500
