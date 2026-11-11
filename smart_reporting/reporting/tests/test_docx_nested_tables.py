"""一层嵌套表：直接运行源码 bridge，避免依赖旧 bundle。"""
import json
import subprocess
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document

ENGINE = Path(__file__).resolve().parents[1] / 'doc_engine'


def bridge(tmp_path, source, operations=None):
    source_path = tmp_path / 'source.docx'
    source_path.write_bytes(source)
    output = tmp_path / 'output.docx'
    output.unlink(missing_ok=True)
    request = {'kind': 'inspect' if operations is None else 'patch', 'input': str(source_path)}
    if operations is not None:
        request.update(output=str(output), operations=operations)
    request_path = tmp_path / 'request.json'
    request_path.write_text(json.dumps(request, ensure_ascii=False))
    result = subprocess.run([str(ENGINE / 'node_modules/.bin/tsx'), str(ENGINE / 'bridge/edit-docx.ts'), str(request_path)], capture_output=True, text=True)
    if result.returncode:
        assert not output.exists()
        raise ValueError(result.stderr)
    return json.loads(result.stdout) if operations is None else output.read_bytes()


def fixture():
    doc = Document()
    cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = 'before'
    nested = cell.add_table(rows=1, cols=2)
    nested.cell(0, 0).text = 'same'
    nested.cell(0, 1).text = 'other'
    # 两张同胞完全相同，且处于同一个段落锚点。
    cell._tc.insert(list(cell._tc).index(nested._tbl) + 1, deepcopy(nested._tbl))
    cell.paragraphs[-1].text = 'after'
    cell.add_paragraph('')
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def operation(root, table, row=0, column=0, paragraphs=None):
    cell = table['cells'][row][column]
    return {'kind': 'replaceNestedCellText', 'blockId': root['blockId'], 'tableId': table['tableId'], 'cellId': cell['cellId'],
            'expectedObjectSha256': cell['expectedObjectSha256'], 'paragraphs': paragraphs or ['changed第二张']}


def root_of(model):
    return next(block for block in model['blocks'] if block['type'] == 'table')


def test_identical_siblings_edit_second_only_and_keep_other_xml(tmp_path):
    source = fixture()
    root = root_of(bridge(tmp_path, source))
    first, second = root['nestedTables']
    assert first['tableId'] != second['tableId']
    assert first['cells'][0][0]['cellId'] != second['cells'][0][0]['cellId']
    assert first['expectedObjectSha256'] == second['expectedObjectSha256']
    assert second['cells'][0][0]['editable'] is True
    assert [first['nestedOrdinal'], second['nestedOrdinal']] == [0, 1]
    result = bridge(tmp_path, source, [operation(root, second)])
    reread = root_of(bridge(tmp_path, result))
    assert reread['nestedTables'][0]['cells'][0][0]['paragraphs'] == ['same']
    assert reread['nestedTables'][1]['cells'][0][0]['paragraphs'] == ['changed第二张']
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        original, actual = before.read('word/document.xml'), after.read('word/document.xml')
        first_at = original.index(b'<w:t>same</w:t>')
        second_at = original.index(b'<w:t>same</w:t>', first_at + 1)
        expected = original[:second_at] + original[second_at:].replace(b'<w:t>same</w:t>', '<w:t xml:space="preserve">changed第二张</w:t>'.encode(), 1)
        assert actual == expected


def test_multiple_targets_and_full_paragraph_arrays(tmp_path):
    source = fixture()
    root = root_of(bridge(tmp_path, source))
    first, second = root['nestedTables']
    paragraphs = ['中文😀 $&', '', 'tail', '']
    result = bridge(tmp_path, source, [operation(root, second, paragraphs=paragraphs), operation(root, first, column=1, paragraphs=['longer text'])])
    reread = root_of(bridge(tmp_path, result))
    assert reread['nestedTables'][1]['cells'][0][0]['paragraphs'] == paragraphs
    assert reread['nestedTables'][0]['cells'][0][1]['paragraphs'] == ['longer text']


@pytest.mark.parametrize('fault', ['table', 'cell', 'hash', 'extra', 'duplicate', 'mixed', 'paragraphs', 'tab', 'newline'])
def test_rejects_invalid_nested_requests_without_output(tmp_path, fault):
    source = fixture()
    root = root_of(bridge(tmp_path, source))
    op = operation(root, root['nestedTables'][1])
    operations = [op]
    if fault == 'table': op['tableId'] = root['nestedTables'][0]['tableId']
    if fault == 'cell': op['cellId'] = 'foreign'
    if fault == 'hash': op['expectedObjectSha256'] = 'wrong'
    if fault == 'extra': op['row'] = 0
    if fault == 'paragraphs': op['paragraphs'] = []
    if fault == 'tab': op['paragraphs'] = ['A\tB']
    if fault == 'newline': op['paragraphs'] = ['A\nB']
    if fault == 'duplicate': operations.append(dict(op))
    if fault == 'mixed': operations.append({'kind': 'setTableRepeatHeaders', 'blockId': root['blockId'], 'expectedObjectSha256': root['expectedObjectSha256'], 'expectedRowCount': 1, 'prefixRowCount': 1, 'headers': [True]})
    with pytest.raises(ValueError): bridge(tmp_path, source, operations)


@pytest.mark.parametrize('placement', ['root', 'parent', 'nested', 'merge', 'deeper'])
def test_unverified_wrappers_and_complex_cells_are_read_only(tmp_path, placement):
    source = fixture()
    doc = Document(BytesIO(source))
    root = doc.tables[0]
    if placement == 'root':
        row = root._tbl.tr_lst[0]
        parent = root._tbl
        target = row
    elif placement == 'parent':
        parent = root.cell(0, 0)._tc
        target = root.cell(0, 0).tables[0]._tbl
    elif placement == 'nested':
        parent = root.cell(0, 0).tables[0]._tbl
        target = parent.tr_lst[0]
    elif placement == 'merge':
        root.cell(0, 0).tables[0].cell(0, 0).merge(root.cell(0, 0).tables[0].cell(0, 1))
    else:
        root.cell(0, 0).tables[0].cell(0, 0).add_table(rows=1, cols=1)
    if placement in ('root', 'parent', 'nested'):
        from docx.oxml import OxmlElement
        wrapper, content = OxmlElement('w:sdt'), OxmlElement('w:sdtContent')
        parent.replace(target, wrapper)
        wrapper.append(content)
        content.append(target)
    out = BytesIO()
    doc.save(out)
    anchors = root_of(bridge(tmp_path, out.getvalue())).get('nestedTables', [])
    assert not anchors or not anchors[0]['cells'][0][0]['editable']


def test_same_nested_table_multiple_cells_and_stale_source_identity(tmp_path):
    source = fixture()
    root = root_of(bridge(tmp_path, source))
    table = root['nestedTables'][1]
    operations = [operation(root, table, paragraphs=['first grows substantially']), operation(root, table, column=1, paragraphs=['second'])]
    result = bridge(tmp_path, source, operations)
    actual = root_of(bridge(tmp_path, result))['nestedTables'][1]
    assert [cell['paragraphs'] for cell in actual['cells'][0]] == [['first grows substantially'], ['second']]
    with pytest.raises(ValueError): bridge(tmp_path, result, operations)


@pytest.mark.parametrize('paragraphs', [['x' * 20001], ['x' * 10001, 'y' * 10000], [''] * 1001])
def test_oversized_source_cell_stays_visible_but_read_only(tmp_path, paragraphs):
    doc = Document(BytesIO(fixture()))
    cell = doc.tables[0].cell(0, 0).tables[0].cell(0, 0)
    cell.text = paragraphs[0]
    for text in paragraphs[1:]:
        cell.add_paragraph(text)
    out = BytesIO()
    doc.save(out)
    root = root_of(bridge(tmp_path, out.getvalue()))
    actual = root['nestedTables'][0]['cells'][0][0]
    assert actual['paragraphs'] == paragraphs
    assert actual['editable'] is False
    assert actual['readOnlyReason']
    assert root['nestedTables'][1]['cells'][0][0]['editable'] is True
