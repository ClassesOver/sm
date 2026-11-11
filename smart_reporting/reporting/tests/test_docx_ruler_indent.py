"""标尺缩进：实际DOCX最小属性写回、来源能力及原子操作。"""
from copy import deepcopy
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
    style = doc.styles.add_style('RulerSource', WD_STYLE_TYPE.PARAGRAPH)
    style.paragraph_format.left_indent = Twips(540)
    style.paragraph_format.first_line_indent = Twips(-180)
    target = doc.add_paragraph(style=style if inherited else None)
    target.add_run('标尺正文').bold = True
    target.add_run(' mixed 😀').italic = True
    target.paragraph_format.space_after = Twips(120)
    target.paragraph_format.keep_with_next = True
    target.paragraph_format.right_indent = Twips(125)
    if not inherited:
        target.paragraph_format.left_indent = Twips(720)
        target.paragraph_format.first_line_indent = Twips(180)
    ind = target._p.pPr.find(qn('w:ind'))
    ind.set('{urn:ruler-test}keep', 'opaque')
    if unsupported == 'characters':
        ind.set(qn('w:leftChars'), '200')
    if unsupported == 'inherited_characters':
        style.element.get_or_add_pPr().find(qn('w:ind')).set(qn('w:firstLineChars'), '200')
        target.style = style
    if unsupported == 'rtl':
        target._p.pPr.append(OxmlElement('w:bidi'))
    if unsupported == 'inferred_rtl':
        target.runs[0].text = 'مرحبا'
    if unsupported == 'columns':
        doc.sections[0]._sectPr.find(qn('w:cols')).set(qn('w:num'), '2')
    if unsupported == 'list':
        target.style = doc.styles['List Bullet']
    if unsupported == 'protected':
        protection = OxmlElement('w:documentProtection')
        protection.set(qn('w:edit'), 'readOnly')
        protection.set(qn('w:enforcement'), '1')
        doc.settings.element.append(protection)
    doc.add_paragraph('邻段不变')
    doc.add_table(rows=1, cols=1).cell(0, 0).text = '表格不变'
    doc.sections[0].header.paragraphs[0].text = '页眉不变'
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def operation(source, **values):
    target = inspect_docx(source)['blocks'][0]
    return {'kind': 'setParagraphRulerIndent', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'], **values}


@pytest.mark.parametrize('inherited', [False, True])
@pytest.mark.parametrize('values', [
    {'leftTwips': 810, 'firstLineTwips': -277},
    {'firstLineTwips': 0}, {'leftTwips': -133},
    {'leftTwips': -14400, 'firstLineTwips': 14400},
])
def test_ruler_indent_roundtrip_preserves_other_xml(inherited, values):
    source = source_docx(inherited)
    assert inspect_docx(source)['blocks'][0]['rulerIndentEditable'] is True
    result = patch_docx(source, [operation(source, **values)])
    original, reopened = Document(BytesIO(source)), Document(BytesIO(result))
    old = original.paragraphs[0]._p.pPr.find(qn('w:ind'))
    actual = reopened.paragraphs[0]._p.pPr.find(qn('w:ind'))
    expected = dict(old.attrib)
    if 'leftTwips' in values:
        expected[qn('w:left')] = str(values['leftTwips'])
    if 'firstLineTwips' in values:
        expected.pop(qn('w:firstLine'), None)
        expected.pop(qn('w:hanging'), None)
        value = values['firstLineTwips']
        expected[qn('w:hanging' if value < 0 else 'w:firstLine')] = str(abs(value))
    assert dict(actual.attrib) == expected
    normalized = []
    for doc in (original, reopened):
        para = deepcopy(doc.paragraphs[0]._p)
        para.pPr.remove(para.pPr.find(qn('w:ind')))
        normalized.append(para.xml.replace(' xml:space="preserve"', ''))
    assert normalized[0] == normalized[1]
    assert [node.xml for node in list(original._element.body)[1:]] == [node.xml for node in list(reopened._element.body)[1:]]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        assert {n for n in before.namelist() if not n.endswith('/')} == {n for n in after.namelist() if not n.endswith('/')}
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


@pytest.mark.parametrize('unsupported', ['characters', 'inherited_characters', 'rtl', 'inferred_rtl', 'columns', 'list', 'protected'])
def test_ruler_indent_rejects_unsupported_sources(unsupported):
    source = source_docx(unsupported=unsupported)
    assert inspect_docx(source)['blocks'][0]['rulerIndentEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(source, [operation(source, firstLineTwips=270)])


@pytest.mark.parametrize('values', [{}, {'leftTwips': 1.5}, {'firstLineTwips': None}, {'leftTwips': True},
                                  {'leftTwips': '120'}, {'leftTwips': 14401}, {'firstLineTwips': -14401}, {'extra': 1}])
def test_ruler_indent_rejects_invalid_values(values):
    source = source_docx()
    with pytest.raises(ValueError):
        patch_docx(source, [operation(source, **values)])


def test_ruler_indent_rejects_forged_and_mixed_or_repeated_operations():
    source = source_docx()
    op = operation(source, leftTwips=810, firstLineTwips=-277)
    for ops in [[{**op, 'expectedObjectSha256': 'f' * 64}], [op, op],
                [op, {'kind': 'setParagraphSpecialIndent', 'blockId': op['blockId'], 'expectedObjectSha256': op['expectedObjectSha256'], 'twips': 270}]]:
        with pytest.raises(ValueError):
            patch_docx(source, ops)
