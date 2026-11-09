"""Whole-paragraph vertical alignment preserves unrelated source XML/relationships."""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source(position=None, empty=False):
    document = Document()
    paragraph = document.add_paragraph()
    paragraph._p.get_or_add_pPr().append(OxmlElement('w:mirrorIndents'))
    if not empty:
        first = paragraph.add_run('A😀')
        first.bold = True
        first.font.name = 'Calibri'
        first.font.color.rgb = RGBColor.from_string('AABBCC')
        first._r.get_or_add_rPr().append(OxmlElement('w:noProof'))
        second = paragraph.add_run('BC')
        second.italic = True
        if position:
            for run in [first, second]:
                tag = OxmlElement('w:vertAlign')
                tag.set(qn('w:val'), position)
                run._r.get_or_add_rPr().append(tag)
        link = OxmlElement('w:hyperlink')
        link.set(qn('r:id'), document.part.relate_to('https://keep.test', RT.HYPERLINK, is_external=True))
        link.set(qn('w:tooltip'), 'kept tooltip')
        run, text = OxmlElement('w:r'), OxmlElement('w:t')
        text.text = 'keep'
        run.append(text)
        link.append(run)
        paragraph._p.append(link)
    document.add_paragraph('Untouched paragraph')
    document.sections[0].header.paragraphs[0].text = 'Untouched header'
    data = BytesIO()
    document.save(data)
    return data.getvalue()


def anchor(data):
    return inspect_docx(data)['blocks'][0]


def operation(target, value, **extra):
    return {'kind': 'setParagraphVerticalAlign', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'], 'value': value, **extra}


def paragraph_xml(content):
    return Document(BytesIO(content)).paragraphs[0]._p


def without_vertical(properties):
    if properties is None:
        return None
    clone = etree.fromstring(etree.tostring(properties))
    for child in list(clone):
        if child.tag == qn('w:vertAlign'):
            clone.remove(child)
    return etree.tostring(clone, method='c14n') if len(clone) or clone.attrib else None


@pytest.mark.parametrize('value', ['superscript', 'subscript', 'baseline'])
def test_vertical_roundtrip_retains_mixed_runs_raw_properties_and_unstyled_link(value):
    content = source('superscript' if value == 'baseline' else None)
    target = anchor(content)
    edited = patch_docx(content, [operation(target, value)])
    before, after = paragraph_xml(content), paragraph_xml(edited)
    assert etree.tostring(before.find(qn('w:pPr')), method='c14n') == etree.tostring(after.find(qn('w:pPr')), method='c14n')
    before_runs, after_runs = before.findall('.//' + qn('w:r')), after.findall('.//' + qn('w:r'))
    assert len(before_runs) == len(after_runs) == 3
    assert [r.find(qn('w:t')).text for r in before_runs] == [r.find(qn('w:t')).text for r in after_runs]
    for old, new in zip(before_runs, after_runs, strict=True):
        assert without_vertical(old.find(qn('w:rPr'))) == without_vertical(new.find(qn('w:rPr')))
        position = new.find(qn('w:rPr')).find(qn('w:vertAlign')) if new.find(qn('w:rPr')) is not None else None
        assert (position.get(qn('w:val')) if position is not None else None) == value
    links = after.findall(qn('w:hyperlink'))
    assert len(links) == 1 and links[0].get(qn('w:tooltip')) == 'kept tooltip'
    link = Document(BytesIO(edited)).part.rels[links[0].get(qn('r:id'))]
    assert link.is_external and link.target_ref == 'https://keep.test'
    link_properties = links[0].find(qn('w:r')).find(qn('w:rPr'))
    assert link_properties is None or link_properties.find(qn('w:rStyle')) is None
    original_doc, changed_doc = Document(BytesIO(content)), Document(BytesIO(edited))
    assert etree.tostring(original_doc.paragraphs[1]._p) == etree.tostring(changed_doc.paragraphs[1]._p)
    with ZipFile(BytesIO(content)) as a, ZipFile(BytesIO(edited)) as b:
        names = {name for name in a.namelist() if not name.endswith('/')}
        assert names == {name for name in b.namelist() if not name.endswith('/')}
        for name in names - {'word/document.xml', 'docProps/core.xml'}:
            assert a.read(name) == b.read(name), name


@pytest.mark.parametrize('value', [None, True, 1, 'super', '<w:vertAlign/>', {}, []])
def test_vertical_protocol_rejects_invalid_values(value):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(anchor(content), value)])


@pytest.mark.parametrize('extra', [{'from': 0}, {'style': {}}, {'rawRPr': '<w:rPr/>'}, {'expectedObjectSha256': 'stale'}])
def test_vertical_protocol_rejects_unknown_fields_and_stale_hash(extra):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(anchor(content), 'superscript') | extra])


def test_vertical_requires_current_text_but_accepts_prior_composed_replacement():
    content = source(empty=True)
    target = anchor(content)
    with pytest.raises(ValueError, match='vertical_align_empty'):
        patch_docx(content, [operation(target, 'superscript')])
    changed = patch_docx(content, [{'kind': 'replaceParagraph', 'blockId': target['blockId'],
                                  'expectedObjectSha256': target['expectedObjectSha256'], 'text': 'new text'},
                                 operation(target, 'subscript')])
    assert Document(BytesIO(changed)).paragraphs[0].text == 'new text'
    assert Document(BytesIO(changed)).paragraphs[0].runs[0].font.subscript is True


def test_vertical_order_and_fresh_revision_anchors():
    content = source()
    old = anchor(content)
    changed = patch_docx(content, [operation(old, 'superscript'), operation(old, 'subscript'), operation(old, 'baseline')])
    assert all(run.find(qn('w:rPr')).find(qn('w:vertAlign')).get(qn('w:val')) == 'baseline' for run in paragraph_xml(changed).findall('.//' + qn('w:r')))
    with pytest.raises(ValueError, match='anchor_invalid'):
        patch_docx(changed, [operation(old, 'superscript')])
    patch_docx(changed, [operation(anchor(changed), 'superscript')])


@pytest.mark.parametrize('style_type', ['character', 'paragraph'])
def test_baseline_explicitly_overrides_inherited_style_alignment(style_type):
    from docx.enum.style import WD_STYLE_TYPE

    document = Document(BytesIO(source()))
    paragraph = document.paragraphs[0]
    style = document.styles.add_style('NativeRaisedText', WD_STYLE_TYPE.CHARACTER if style_type == 'character' else WD_STYLE_TYPE.PARAGRAPH)
    style.font.superscript = True
    if style_type == 'paragraph':
        paragraph.style = style
    else:
        for run in paragraph.runs:
            run.style = style
    content = BytesIO()
    document.save(content)
    data = content.getvalue()
    result = patch_docx(data, [operation(anchor(data), 'baseline')])
    saved = Document(BytesIO(result))
    assert saved.styles['NativeRaisedText'].font.superscript is True
    for run in saved.paragraphs[0]._p.findall('.//' + qn('w:r')):
        assert run.find(qn('w:rPr')).find(qn('w:vertAlign')).get(qn('w:val')) == 'baseline'
    assert all(run.font.superscript is False for run in saved.paragraphs[0].runs)
