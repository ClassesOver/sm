from io import BytesIO
from itertools import permutations
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_paragraph_borders import W, make_doc, op as border_op, pbdr_of, single
from smart_reporting.reporting.tests.test_docx_paragraph_shading import op as shade_op, shd_of


def body_op(data):
    block = inspect_docx(data)['blocks'][0]
    return {'kind': 'patchParagraphRuns', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'runs': [
        {'sourceFrom': 0, 'sourceTo': 6}, {'text': '新增', 'inheritFrom': 0, 'style': {'italic': True}}, {'sourceFrom': 6, 'sourceTo': 11, 'style': {'color': '0070C0'}},
    ]}


@pytest.mark.parametrize('order', list(permutations(range(3))))
def test_final_body_with_borders_and_shading_composes_on_current_paragraph(order):
    doc = Document(BytesIO(make_doc()))
    doc.paragraphs[0].runs[0]._r.get_or_add_rPr().append(OxmlElement('w:noProof'))
    out = BytesIO(); doc.save(out); data = out.getvalue()
    ops = [body_op(data), shade_op(data, 'edf5fc'), border_op(data, [single('bottom', 'FF0000', 1)])]
    result = patch_docx(data, [ops[index] for index in order])
    saved = Document(BytesIO(result))
    assert saved.paragraphs[0].text == 'target新增 keep'
    assert [(run.text, bool(run.italic)) for run in saved.paragraphs[0].runs] == [('target', False), ('新增', True), (' keep', False)]
    assert saved.paragraphs[0].runs[0]._r.rPr.find(qn('w:noProof')) is not None
    assert saved.paragraphs[0].runs[1]._r.rPr.find(qn('w:noProof')) is not None
    assert saved.paragraphs[0].runs[2].bold is True
    assert str(saved.paragraphs[0].runs[2].font.color.rgb) == '0070C0'
    assert saved.paragraphs[0].paragraph_format.keep_with_next is True
    assert pbdr_of(result)['bottom']['color'] == 'FF0000'
    assert shd_of(result) == ('clear', 'auto', 'edf5fc')
    assert etree.tostring(saved.paragraphs[1]._p) == etree.tostring(doc.paragraphs[1]._p)
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(result)) as after:
        assert {name for name in before.namelist() if before.read(name) != after.read(name)} == {'word/document.xml'}


@pytest.mark.parametrize('fill,clear,borders', [('0070c0', False, None), (None, True, [single('top')]), (None, False, None)])
def test_body_plan_composes_with_removal_and_auto(fill, clear, borders):
    data = make_doc([f'<w:shd xmlns:w="{W}" w:val="clear" w:color="auto" w:fill="FFF2CC"/>', f'<w:pBdr xmlns:w="{W}"><w:top w:val="single"/></w:pBdr>'])
    result = patch_docx(data, [shade_op(data, fill, clear), body_op(data), border_op(data, borders)])
    assert Document(BytesIO(result)).paragraphs[0].text == 'target新增 keep'
    assert shd_of(result) == (('clear', 'auto', fill or 'auto') if fill or clear else None)
    assert (pbdr_of(result) is None) == (borders is None)


def test_body_decoration_composition_keeps_other_conflicts_and_identity_rejected():
    data = make_doc(); body = body_op(data); shade = shade_op(data, 'edf5fc'); border = border_op(data, [single('bottom')])
    for batch in [
        [body, shade, border, dict(shade)], [body, shade, border, dict(border)], [body, dict(body), shade, border],
        [{**body, 'expectedObjectSha256': 'foreign'}, shade, border], [body, {**shade, 'expectedObjectSha256': 'foreign'}, border],
        [body, shade, {**border, 'extra': 1}], [body, shade, border, {**{k: v for k, v in body.items() if k in ('blockId', 'expectedObjectSha256')}, 'kind': 'setParagraphPageBreakBefore', 'value': True}],
    ]:
        with pytest.raises(ValueError): patch_docx(data, batch)


@pytest.mark.parametrize('decoration', ['shading', 'borders'])
@pytest.mark.parametrize('body_first', [False, True])
def test_body_with_a_single_decoration(decoration, body_first):
    data = make_doc(); body = body_op(data)
    changed = shade_op(data, 'edf5fc') if decoration == 'shading' else border_op(data, [single('bottom')])
    result = patch_docx(data, [body, changed] if body_first else [changed, body])
    assert Document(BytesIO(result)).paragraphs[0].text == 'target新增 keep'
    assert (shd_of(result) is not None) == (decoration == 'shading')
    assert (pbdr_of(result) is not None) == (decoration == 'borders')


@pytest.mark.parametrize('source', [
    f'<w:shd xmlns:w="{W}" w:val="pct10" w:fill="FFF2CC"/>',
    f'<w:pBdr xmlns:w="{W}"><w:top w:val="double"/></w:pBdr>',
])
def test_final_body_does_not_normalize_unsupported_source_decorations(source):
    data = make_doc(source)
    with pytest.raises(ValueError):
        patch_docx(data, [body_op(data), shade_op(data, 'edf5fc'), border_op(data, [single('bottom')])])


def test_final_body_does_not_bypass_document_protection_or_inline_boundaries():
    doc = Document(BytesIO(make_doc()))
    protection = OxmlElement('w:documentProtection'); protection.set(qn('w:edit'), 'readOnly'); protection.set(qn('w:enforcement'), '1')
    doc.settings.element.append(protection)
    out = BytesIO(); doc.save(out); data = out.getvalue()
    with pytest.raises(ValueError): patch_docx(data, [body_op(data), shade_op(data, 'edf5fc'), border_op(data, [single('bottom')])])
    data = make_doc(); body = body_op(data)
    for runs in [[{'text': 'evil', 'inheritFrom': 0, 'rawRPr': '<evil/>'}], [{'noteKind': 'footnote', 'noteId': '1', 'referenceIndex': 0}]]:
        with pytest.raises(ValueError): patch_docx(data, [{**body, 'runs': runs}, shade_op(data, 'edf5fc'), border_op(data, [single('bottom')])])


@pytest.mark.parametrize('clear', [False, True])
def test_body_decorations_keep_style_inheritance_and_explicit_auto_distinct(clear):
    doc = Document(BytesIO(make_doc()))
    style = doc.styles['Normal']
    style.element.get_or_add_pPr().append(etree.fromstring(f'<w:shd xmlns:w="{W}" w:val="clear" w:fill="FFF2CC"/>'))
    out = BytesIO(); doc.save(out); data = out.getvalue()
    result = patch_docx(data, [body_op(data), shade_op(data, None, clear), border_op(data, [single('bottom')])])
    assert Document(BytesIO(result)).paragraphs[0].text == 'target新增 keep'
    assert shd_of(result) == (('clear', 'auto', 'auto') if clear else None)
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(result)) as after:
        assert before.read('word/styles.xml') == after.read('word/styles.xml')


def test_notes_reference_source_uses_independent_decoration_capabilities():
    from smart_reporting.reporting.tests.test_docx_notes import source, insert

    data = source(); data = patch_docx(data, [insert(inspect_docx(data))])
    block = inspect_docx(data)['blocks'][0]
    body = {'kind': 'patchParagraphRuns', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'runs': [
        {'sourceFrom': 0, 'sourceTo': 3}, {'noteKind': 'footnote', 'noteId': '1', 'referenceIndex': 0}, {'sourceFrom': 4, 'sourceTo': 7},
    ]}
    assert block['editable'] is False
    assert block['paragraphShadingEditable'] is True and block['paragraphBordersEditable'] is True
    for decoration in [shade_op(data, 'edf5fc'), border_op(data, [single('bottom')])]:
        result = patch_docx(data, [body, decoration])
        assert inspect_docx(result)['notes']['footnotes'][0]['id'] == '1'


def test_new_note_reference_composes_with_body_and_decorations():
    from smart_reporting.reporting.tests.test_docx_notes import insert

    data = make_doc(); model = inspect_docx(data)
    body = body_op(data)
    body['runs'] = [{'sourceFrom': 0, 'sourceTo': 3}, {'noteOperationIndex': 0}, {'sourceFrom': 3, 'sourceTo': 11}]
    result = patch_docx(data, [insert(model), body, shade_op(data, 'edf5fc'), border_op(data, [single('bottom')])])
    assert Document(BytesIO(result)).paragraphs[0].text == 'target keep'
    assert inspect_docx(result)['notes']['footnotes'][0]['id'] == '1'
