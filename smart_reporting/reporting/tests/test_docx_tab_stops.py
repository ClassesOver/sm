"""标尺制表位的真实DOCX写回、继承清除和来源保全。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Twips

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source_docx(inherited=False, unsupported=None):
    doc = Document()
    style = doc.styles.add_style('RulerTabs', WD_STYLE_TYPE.PARAGRAPH)
    style.paragraph_format.tab_stops.add_tab_stop(Twips(2160))
    p = doc.add_paragraph(style=style if inherited else None)
    p.add_run('A\t').bold = True
    p.add_run('B 漢字 😀').italic = True
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.left_indent = Twips(125)
    if not inherited:
        p.paragraph_format.tab_stops.add_tab_stop(Twips(2160))
    if unsupported == 'unknown':
        p._p.pPr.find(qn('w:tabs')).set('{urn:tab-test}keep', 'opaque')
    if unsupported == 'unknown_stop':
        p._p.pPr.find(qn('w:tabs')).find(qn('w:tab')).set('{urn:tab-test}keep', 'opaque')
    if unsupported == 'rtl':
        p._p.pPr.append(OxmlElement('w:bidi'))
    if unsupported == 'columns':
        doc.sections[0]._sectPr.find(qn('w:cols')).set(qn('w:num'), '2')
    if unsupported == 'mirror':
        doc.settings.element.append(OxmlElement('w:mirrorMargins'))
    if unsupported == 'protected':
        protection = OxmlElement('w:documentProtection')
        protection.set(qn('w:edit'), 'readOnly')
        protection.set(qn('w:enforcement'), '1')
        doc.settings.element.append(protection)
    if unsupported == 'relative':
        ptab = OxmlElement('w:ptab')
        ptab.set(qn('w:alignment'), 'right'); ptab.set(qn('w:relativeTo'), 'margin')
        p.runs[0]._r.append(ptab)
    doc.add_paragraph('邻段不变')
    doc.add_table(rows=1, cols=1).cell(0, 0).text = '表格不变'
    doc.sections[0].header.paragraphs[0].text = '页眉不变'
    stream = BytesIO(); doc.save(stream)
    return stream.getvalue()


def operation(source, stops):
    target = inspect_docx(source)['blocks'][0]
    return {'kind': 'setParagraphTabStops', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'], 'stops': stops}


@pytest.mark.parametrize('inherited', [False, True])
@pytest.mark.parametrize('stops', [
    [{'pos': 2160, 'val': 'clear'}],
    [{'pos': 2160, 'val': 'clear'}, {'pos': 4320, 'val': 'decimal', 'leader': 'dot'}],
    [{'pos': 720, 'val': 'left'}, {'pos': 1440, 'val': 'center'},
     {'pos': 2160, 'val': 'right', 'leader': 'hyphen'}, {'pos': 2880, 'val': 'bar'}],
])
def test_tab_stops_roundtrip_preserves_other_xml(inherited, stops):
    source = source_docx(inherited)
    assert inspect_docx(source)['blocks'][0]['tabStopsEditable'] is True
    result = patch_docx(source, [operation(source, stops)])
    original, reopened = Document(BytesIO(source)), Document(BytesIO(result))
    tabs = reopened.paragraphs[0]._p.pPr.find(qn('w:tabs'))
    assert [dict(node.attrib) for node in tabs] == [
        {qn('w:pos'): str(t['pos']), qn('w:val'): t['val'], **({qn('w:leader'): t['leader']} if 'leader' in t else {})}
        for t in stops]
    model = inspect_docx(result)['blocks'][0]
    assert model['tabStopsEditable'] is True
    normalized = []
    for doc in (original, reopened):
        p = doc.paragraphs[0]._p
        tabs = p.pPr.find(qn('w:tabs'))
        if tabs is not None: p.pPr.remove(tabs)
        normalized.append(p.xml.replace(' xml:space="preserve"', ''))
    assert normalized[0] == normalized[1]
    assert [n.xml for n in list(original._element.body)[1:]] == [n.xml for n in list(reopened._element.body)[1:]]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        assert {n for n in before.namelist() if not n.endswith('/')} == {n for n in after.namelist() if not n.endswith('/')}
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}: assert before.read(name) == after.read(name), name


def test_tab_stops_can_remove_last_direct_stop():
    source = source_docx()
    result = patch_docx(source, [operation(source, [])])
    assert Document(BytesIO(result)).paragraphs[0]._p.pPr.find(qn('w:tabs')) is None


@pytest.mark.parametrize('unsupported', ['unknown', 'unknown_stop', 'rtl', 'columns', 'mirror', 'protected', 'relative'])
def test_tab_stops_reject_unsupported_source(unsupported):
    source = source_docx(unsupported=unsupported)
    assert inspect_docx(source)['blocks'][0]['tabStopsEditable'] is False
    with pytest.raises(ValueError): patch_docx(source, [operation(source, [])])


@pytest.mark.parametrize('stops', [None, {}, [{'pos': True, 'val': 'left'}], [{'pos': 1.5, 'val': 'left'}],
                                  [{'pos': 720, 'val': 'num'}], [{'pos': 720, 'val': 'left', 'inherited': True}],
                                  [{'pos': 720, 'val': 'left', 'leader': 'invalid'}],
                                  [{'pos': 720, 'val': 'left'}, {'pos': 720, 'val': 'right'}]])
def test_tab_stops_reject_invalid_protocol(stops):
    source = source_docx()
    with pytest.raises(ValueError): patch_docx(source, [operation(source, stops)])


def test_tab_stops_reject_stale_identity_and_mixed_or_duplicate_batch():
    source = source_docx()
    op = operation(source, [{'pos': 4320, 'val': 'right'}])
    for ops in [[{**op, 'expectedObjectSha256': 'f' * 64}], [op, op],
                [op, {'kind': 'setParagraphRulerIndent', 'blockId': op['blockId'], 'expectedObjectSha256': op['expectedObjectSha256'], 'leftTwips': 810}]]:
        with pytest.raises(ValueError): patch_docx(source, ops)
