"""原生表格单元格边框：富文本与真实 ZIP 保留契约。"""
from io import BytesIO
from zipfile import ZipFile
import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from smart_reporting.reporting.tests.test_docx_cell_shading import source as rich_source
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

@pytest.mark.parametrize('mode', ['outer', 'none'])
def test_native_selected_cell_border_preserves_zip(mode):
    doc = Document(BytesIO(rich_source.__wrapped__()))
    table = doc.tables[0]
    borders = OxmlElement('w:tblBorders')
    for name in ['insideH', 'insideV']:
        side = OxmlElement(f'w:{name}')
        side.set(qn('w:val'), 'single')
        side.set(qn('w:sz'), '4')
        side.set(qn('w:color'), '000000')
        borders.append(side)
    table._tbl.tblPr.append(borders)
    output = BytesIO()
    doc.save(output)
    content = output.getvalue()
    anchor = next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')
    # 候选命令：可信源table hash + 身份化端点；null与裸caret一样为整表。
    selected = None if mode == 'outer' else {
        'fromCellId': anchor['cells'][0][0]['cellId'],
        'toCellId': anchor['cells'][0][1]['cellId'],
    }
    operation = {'kind': 'setTableCellBorders', 'blockId': anchor['blockId'],
                 'expectedObjectSha256': anchor['expectedObjectSha256'],
                 'steps': [{'range': selected, 'mode': mode,
                 'pen': {'style': 'single', 'szEighths': 12, 'color': 'FF0000'}}]}
    patched = patch_docx(content, [operation])
    before, after = ZipFile(BytesIO(content)), ZipFile(BytesIO(patched))
    names = {name for name in before.namelist() if not name.endswith('/')}
    assert names == {name for name in after.namelist() if not name.endswith('/')}
    for name in names - {'word/document.xml'}:
        assert before.read(name) == after.read(name), name
    result = Document(BytesIO(patched)).tables[0]
    for r, row in enumerate(table.rows):
        for c, cell in enumerate(row.cells):
            assert [etree.tostring(p._p) for p in cell.paragraphs] == [etree.tostring(p._p) for p in result.cell(r,c).paragraphs]
    if mode == 'none':
        for c in range(2):
            border = result.cell(0,c)._tc.tcPr.find(qn('w:tcBorders'))
            for name in ['top','left','bottom','right','tl2br','tr2bl']:
                assert border.find(qn(f'w:{name}')).get(qn('w:val')) == 'none'
        # 固定源 No Border 会清整张表的inside，不能遗漏该跨cell副作用。
        table_borders = result._tbl.tblPr.find(qn('w:tblBorders'))
        assert table_borders is None or all(table_borders.find(qn(f'w:{name}')) is None for name in ['insideH','insideV'])
    else:
        for r,c,name in [(0,0,'top'),(0,0,'left'),(0,1,'top'),(0,1,'right'),(1,0,'bottom'),(1,0,'left'),(1,1,'bottom'),(1,1,'right')]:
            line = result.cell(r,c)._tc.tcPr.find(qn('w:tcBorders')).find(qn(f'w:{name}'))
            assert (line.get(qn('w:val')),line.get(qn('w:sz')),line.get(qn('w:color'))) == ('single','12','FF0000')


def anchored(content):
    anchor = next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')
    return anchor, {'kind': 'setTableCellBorders', 'blockId': anchor['blockId'],
                    'expectedObjectSha256': anchor['expectedObjectSha256'],
                    'steps': [{'range': None, 'mode': 'all',
                               'pen': {'style': 'single', 'szEighths': 4, 'color': '000000'}}]}


@pytest.mark.parametrize('fault', ['hash', 'range', 'style', 'width', 'color', 'extra', 'empty', 'duplicate', 'mixed'])
def test_cell_borders_reject_untrusted_or_conflicting_operations(fault):
    content = rich_source.__wrapped__()
    anchor, operation = anchored(content)
    operations = [operation]
    if fault == 'hash':
        operation['expectedObjectSha256'] = 'foreign'
    elif fault == 'range':
        operation['steps'][0]['range'] = {'fromCellId': 'foreign', 'toCellId': anchor['cells'][1][1]['cellId']}
    elif fault in {'style', 'width', 'color'}:
        key, value = {'style': ('style', 'art'), 'width': ('szEighths', 6), 'color': ('color', '#FF0000')}[fault]
        operation['steps'][0]['pen'][key] = value
    elif fault == 'extra':
        operation['steps'][0]['xml'] = '<w:tbl/>'
    elif fault == 'empty':
        operation['steps'] = []
    elif fault == 'duplicate':
        operations.append(operation)
    else:
        cell = anchor['cells'][1][1]
        operations.append({'kind': 'replaceCellText', 'blockId': anchor['blockId'], 'cellId': cell['cellId'],
                           'expectedObjectSha256': cell['expectedObjectSha256'], 'text': 'conflict'})
    with pytest.raises(ValueError):
        patch_docx(content, operations)


@pytest.mark.parametrize('fault', ['merged', 'nested', 'revision'])
def test_cell_borders_report_readonly_for_ambiguous_source(fault):
    doc = Document(BytesIO(rich_source.__wrapped__()))
    table = doc.tables[0]
    if fault == 'merged':
        table.cell(0, 0).merge(table.cell(0, 1))
    elif fault == 'nested':
        table.cell(0, 0).add_table(rows=1, cols=1)
    else:
        table.cell(0, 0)._tc.get_or_add_tcPr().append(OxmlElement('w:tcPrChange'))
    output = BytesIO()
    doc.save(output)
    content = output.getvalue()
    anchor, operation = anchored(content)
    assert anchor['bordersEditable'] is False
    assert anchor['bordersReadOnlyReason']
    with pytest.raises(ValueError, match='cell_borders'):
        patch_docx(content, [operation])
