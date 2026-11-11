"""原生单元格底纹：真实 ZIP 身份、富文本及表样式继承保留。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def serialized(doc):
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


@pytest.fixture
def source():
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    table.style = 'Light Shading Accent 1'
    for ri, row in enumerate(table.rows):
        for ci, cell in enumerate(row.cells):
            cell.text = f'cell {ri},{ci}'
    cell = table.cell(0, 0)
    cell.paragraphs[0].add_run(' bold').bold = True
    link = OxmlElement('w:hyperlink')
    link.set(qn('r:id'), cell.part.relate_to('https://example.org', RT.HYPERLINK, is_external=True))
    run, text = OxmlElement('w:r'), OxmlElement('w:t')
    text.text = ' link'
    run.append(text)
    link.append(run)
    cell.paragraphs[0]._p.append(link)
    tcpr = cell._tc.get_or_add_tcPr()
    borders, top = OxmlElement('w:tcBorders'), OxmlElement('w:top')
    top.set(qn('w:val'), 'single')
    top.set(qn('w:sz'), '12')
    borders.append(top)
    tcpr.append(borders)
    shading = OxmlElement('w:shd')
    shading.set(qn('w:val'), 'clear')
    shading.set(qn('w:fill'), 'FFC000')
    tcpr.append(shading)
    return serialized(doc)


def table_anchor(source):
    return next(block for block in inspect_docx(source)['blocks'] if block['type'] == 'table')


def operation(anchor, fill=None, row=0, column=0):
    cell = anchor['cells'][row][column]
    return {'kind': 'setCellShading', 'blockId': anchor['blockId'], 'cellId': cell['cellId'],
            'expectedObjectSha256': cell['expectedObjectSha256'], 'fill': fill}


@pytest.mark.parametrize('fill', ['00B050', None])
def test_selected_rich_cell_shading_preserves_zip(source, fill):
    anchor = table_anchor(source)
    cell = anchor['cells'][0][0]
    assert cell['editable'] is False
    assert cell['shadingEditable'] is True
    patched = patch_docx(source, [operation(anchor, fill)])
    before, after = ZipFile(BytesIO(source)), ZipFile(BytesIO(patched))
    names = {name for name in before.namelist() if not name.endswith('/')}
    assert names == {name for name in after.namelist() if not name.endswith('/')}
    for name in names:
        if name != 'word/document.xml':
            assert before.read(name) == after.read(name)
    original = before.read('word/document.xml').decode()
    replacement = '' if fill is None else f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>'
    expected = original.replace('<w:shd w:val="clear" w:fill="FFC000"/>', replacement, 1)
    assert after.read('word/document.xml').decode() == expected
    fresh = table_anchor(patched)
    assert fresh['cells'][0][0]['cellId'] != cell['cellId']
    with pytest.raises(ValueError, match='anchor_invalid'):
        patch_docx(patched, [operation(anchor, 'ABCDEF')])
    # 删除直接 shd 后仍保留原表样式及其 styles.xml，不能写 fill=auto 覆盖继承。
    assert Document(BytesIO(patched)).tables[0].style.style_id == 'LightShading-Accent1'


@pytest.mark.parametrize('extra', [
    {'fill': '#FF0000'}, {'fill': 'red'}, {'fill': False}, {'fill': {}},
    {'cellId': 'foreign'}, {'expectedObjectSha256': 'wrong'}, {'xml': '<w:tc/>'},
])
def test_cell_shading_rejects_invalid_or_forged_input(source, extra):
    with pytest.raises(ValueError):
        patch_docx(source, [operation(table_anchor(source)) | extra])


@pytest.mark.parametrize('fault', ['merged', 'nested', 'revision'])
def test_cell_shading_reports_unsupported_source_separately(source, fault):
    doc = Document(BytesIO(source))
    table = doc.tables[0]
    if fault == 'merged':
        table.cell(0, 0).merge(table.cell(0, 1))
    elif fault == 'nested':
        table.cell(0, 0).add_table(rows=1, cols=1)
    else:
        table.cell(0, 0)._tc.get_or_add_tcPr().append(OxmlElement('w:tcPrChange'))
    content = serialized(doc)
    anchor = table_anchor(content)
    assert anchor['cells'][0][0]['shadingEditable'] is False
    assert anchor['cells'][0][0]['shadingReadOnlyReason']
    with pytest.raises(ValueError, match='cell_shading'):
        patch_docx(content, [operation(anchor, 'ABCDEF')])


def test_cell_shading_multiple_targets_and_conflicts(source):
    anchor = table_anchor(source)
    operations = [operation(anchor, '123456'), operation(anchor, 'ABCDEF', row=1, column=1)]
    patched = patch_docx(source, operations)
    table = Document(BytesIO(patched)).tables[0]
    assert table.cell(0, 0)._tc.tcPr.find(qn('w:shd')).get(qn('w:fill')) == '123456'
    assert table.cell(1, 1)._tc.tcPr.find(qn('w:shd')).get(qn('w:fill')) == 'ABCDEF'
    assert table.cell(0, 1)._tc.tcPr.find(qn('w:shd')) is None
    for conflict in [operations[1], {**operations[1], 'kind': 'replaceCellText', 'text': 'no', 'fill': None}]:
        if conflict['kind'] == 'replaceCellText':
            del conflict['fill']
        with pytest.raises(ValueError, match='batch_conflict'):
            patch_docx(source, [operations[1], conflict])
