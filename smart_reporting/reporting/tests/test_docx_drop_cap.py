"""首字下沉沿源格式生成器写回；独立 XML/Word 回读。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    doc = Document()
    p = doc.add_paragraph('首段正文')
    p.add_run(' 保留粗体').bold = True
    p.paragraph_format.keep_with_next = True
    unknown = OxmlElement('w:autoSpaceDE'); unknown.set(qn('w:val'), '0')
    p._p.get_or_add_pPr().append(unknown)
    doc.add_paragraph('相邻正文')
    doc.sections[0].header.paragraphs[0].text = '不修改页眉'
    out = BytesIO(); doc.save(out)
    return out.getvalue()


def operation(data, value):
    anchor = inspect_docx(data)['blocks'][0]
    return {'kind': 'setParagraphDropCap', 'blockId': anchor['blockId'], 'expectedObjectSha256': anchor['expectedObjectSha256'], 'value': value}


@pytest.mark.parametrize('kind', ['drop', 'margin'])
def test_drop_cap_writes_source_frame_and_preserves_runs_unknown_properties_and_other_parts(kind):
    before = source(); after = patch_docx(before, [operation(before, {'type': kind, 'lines': 3})])
    a, b = Document(BytesIO(before)), Document(BytesIO(after))
    frame = b.paragraphs[0]._p.pPr.find(qn('w:framePr'))
    assert frame is not None
    assert {name.split('}')[1]: value for name, value in frame.attrib.items()} == {'dropCap': kind, 'lines': '3', 'wrap': 'around', 'vAnchor': 'text', 'hAnchor': 'text'}
    assert [r._r.xml for r in a.paragraphs[0].runs] == [r._r.xml for r in b.paragraphs[0].runs]
    assert b.paragraphs[0]._p.pPr.find(qn('w:autoSpaceDE')).get(qn('w:val')) == '0'
    assert a.paragraphs[1]._p.xml == b.paragraphs[1]._p.xml
    names = [n.tag.split('}')[1] for n in b.paragraphs[0]._p.pPr]
    assert names.index('keepNext') < names.index('framePr') < names.index('autoSpaceDE')
    with ZipFile(BytesIO(before)) as x, ZipFile(BytesIO(after)) as y:
        for name in x.namelist():
            if name != 'word/document.xml': assert x.read(name) == y.read(name), name
    cleared = patch_docx(after, [operation(after, None)])
    assert Document(BytesIO(cleared)).paragraphs[0]._p.pPr.find(qn('w:framePr')) is None


def test_drop_cap_composes_with_body_replacement_and_new_paragraph_in_source_order():
    before = source(); op = operation(before, {'type': 'margin', 'lines': 3})
    base = {key: op[key] for key in ['blockId', 'expectedObjectSha256']}
    after = patch_docx(before, [op, {**base, 'kind': 'replaceParagraph', 'text': '人工修改'}, {**base, 'kind': 'insertParagraph', 'position': 'after', 'text': '新增段落', 'dropCap': {'type': 'drop', 'lines': 3}}])
    assert Document(BytesIO(after)).paragraphs[0].text == '人工修改'
    assert Document(BytesIO(after)).paragraphs[1].text == '新增段落'
    assert Document(BytesIO(after)).paragraphs[1]._p.pPr.find(qn('w:framePr')).get(qn('w:dropCap')) == 'drop'


@pytest.mark.parametrize('value', [{'type': 'unknown', 'lines': 3}, {'type': 'drop', 'lines': True}, {'type': 'drop', 'lines': 0}, {'type': 'drop', 'lines': 3, 'xml': 'no'}])
def test_drop_cap_rejects_invalid_value(value):
    data = source()
    with pytest.raises(ValueError): patch_docx(data, [operation(data, value)])


def test_drop_cap_rejects_stale_identity_and_duplicate_operation():
    data = source(); op = operation(data, {'type': 'drop', 'lines': 3})
    with pytest.raises(ValueError): patch_docx(data, [{**op, 'expectedObjectSha256': '0' * 64}])
    with pytest.raises(ValueError): patch_docx(data, [op, op])


def test_drop_cap_combines_with_paragraph_properties_and_shading_without_overwriting_either():
    data = source(); op = operation(data, {'type': 'drop', 'lines': 3})
    base = {key: op[key] for key in ['blockId', 'expectedObjectSha256']}
    for other in [{'kind': 'setParagraphProperties', 'values': {'align': 'center', 'spaceBefore': 0}}, {'kind': 'setParagraphShading', 'fill': 'edf5fc', 'clear': False}]:
        after = patch_docx(data, [op, {**base, **other}])
        para = Document(BytesIO(after)).paragraphs[0]
        assert para._p.pPr.find(qn('w:framePr')).get(qn('w:dropCap')) == 'drop'
        if other['kind'] == 'setParagraphProperties':
            assert para._p.pPr.find(qn('w:jc')).get(qn('w:val')) == 'center'
        else:
            assert para._p.pPr.find(qn('w:shd')).get(qn('w:fill')).lower() == 'edf5fc'
