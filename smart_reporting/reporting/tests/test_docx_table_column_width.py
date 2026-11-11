"""Column widths use trusted section bounds and preserve original DOCX XML."""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn

from scripts.probe_native_docx_tables import fixture
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'width.docx'
    fixture(path)
    return path.read_bytes()


def anchor(content):
    return next(item for item in inspect_docx(content)['blocks'] if item['type'] == 'table')


def resize(content, steps):
    target = anchor(content)
    return patch_docx(content, [{'kind': 'resizeTableColumns', 'blockId': target['blockId'],
                                'expectedObjectSha256': target['expectedObjectSha256'], 'steps': steps}])


def test_resize_and_distribute_survive_reopen_preserving_paragraphs(source):
    before = anchor(source)
    assert before.get('columnWidthEditable') is True
    step = {'kind': 'setTableColumnWidth', 'left': 0, 'right': 1, 'widthTwips': 3000}
    result = resize(source, [step])
    after = anchor(result)
    assert after['columnWidthsTwips'][0] == 3000
    table = Document(BytesIO(result)).tables[0]
    assert int(table._tbl.tblPr.find(qn('w:tblW')).get(qn('w:w'))) == sum(after['columnWidthsTwips'])
    original = Document(BytesIO(source)).tables[0]
    assert [[p._p.xml for p in c.paragraphs] for row in table.rows for c in row.cells] == [[p._p.xml for p in c.paragraphs] for row in original.rows for c in row.cells]
    widths = after['columnWidthsTwips']
    distributed = resize(result, [{'kind': 'distributeTableColumns', 'left': 0, 'right': 1}])
    final = anchor(distributed)['columnWidthsTwips']
    assert sum(final) == sum(widths)
    assert max(final) - min(final) <= 1
    for content in [result, distributed]:
        with ZipFile(BytesIO(source)) as before_zip, ZipFile(BytesIO(content)) as after_zip:
            names = {name for name in before_zip.namelist() if not name.endswith('/')}
            assert names == {name for name in after_zip.namelist() if not name.endswith('/')}
            assert [name for name in names if before_zip.read(name) != after_zip.read(name)] == ['word/document.xml']


@pytest.mark.parametrize('step', [
    {'kind': 'setTableColumnWidth', 'left': 0, 'right': 1, 'widthTwips': True},
    {'kind': 'setTableColumnWidth', 'left': 0, 'right': 99, 'widthTwips': 3000},
    {'kind': 'setTableColumnWidth', 'left': 0, 'right': 1, 'widthTwips': 3000, 'maxWidthTwips': 999999},
    {'kind': 'distributeTableColumns', 'left': -1, 'right': 1},
])
def test_resize_rejects_invalid_or_forged_requests(source, step):
    with pytest.raises(ValueError):
        resize(source, [step])


def test_width_limit_comes_from_each_source_section_and_cannot_be_overridden(source):
    from copy import deepcopy
    from docx.enum.section import WD_SECTION
    doc = Document(BytesIO(source))
    second = doc.add_section(WD_SECTION.NEW_PAGE)
    second.left_margin = 1800 * 635
    second.right_margin = 1800 * 635
    second.page_width = 10000 * 635
    doc._body._body.insert(-1, deepcopy(doc.tables[0]._tbl))
    out = BytesIO()
    doc.save(out)
    content = out.getvalue()
    targets = [item for item in inspect_docx(content)['blocks'] if item['type'] == 'table']
    limits = [int((s.page_width - s.left_margin - s.right_margin) / 635) for s in doc.sections]
    assert [item['columnWidthMaxTwips'] for item in targets] == limits
    target = targets[1]
    op = {'kind': 'resizeTableColumns', 'blockId': target['blockId'],
          'expectedObjectSha256': target['expectedObjectSha256'],
          'steps': [{'kind': 'setTableColumnWidth', 'left': 0, 'right': 1, 'widthTwips': 30000}]}
    result = patch_docx(content, [op])
    after = [item for item in inspect_docx(result)['blocks'] if item['type'] == 'table']
    assert sum(after[1]['columnWidthsTwips']) <= limits[1]
    assert after[0]['expectedObjectSha256'] == targets[0]['expectedObjectSha256']
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'maxWidthTwips': 31680}])


def test_multicolumn_section_is_readonly_and_same_section_resize_layout_cannot_mix(source):
    doc = Document(BytesIO(source))
    columns = doc.sections[0]._sectPr.find(qn('w:cols'))
    columns.set(qn('w:num'), '2')
    out = BytesIO()
    doc.save(out)
    content = out.getvalue()
    assert anchor(content)['columnWidthEditable'] is False
    step = {'kind': 'setTableColumnWidth', 'left': 0, 'right': 1, 'widthTwips': 3000}
    with pytest.raises(ValueError):
        resize(content, [step])
    model = inspect_docx(source)
    target = anchor(source)
    section = model['sections'][0]
    op = {'kind': 'resizeTableColumns', 'blockId': target['blockId'],
          'expectedObjectSha256': target['expectedObjectSha256'], 'steps': [step]}
    layout = {'kind': 'setSectionLayout', 'sectionId': section['sectionId'],
              'expectedSectionSha256': section['expectedSectionSha256'], 'values': {'marginLeft': 2500}}
    for batch in [[op, layout], [layout, op]]:
        with pytest.raises(ValueError, match='batch_conflict'):
            patch_docx(source, batch)
