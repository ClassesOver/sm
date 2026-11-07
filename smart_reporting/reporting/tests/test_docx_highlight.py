"""OOXML named highlight changes preserve mixed runs, links and unrelated ZIP entries."""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_vertical_align import source


COLORS = ['yellow', 'green', 'cyan', 'magenta', 'blue', 'red', 'darkBlue', 'darkCyan',
          'darkGreen', 'darkMagenta', 'darkRed', 'darkYellow', 'darkGray', 'lightGray', 'black', 'white', 'none']


def highlighted_source():
    document = Document(BytesIO(source()))
    paragraph = document.paragraphs[0]
    for run, color in zip(paragraph._p.findall('.//' + qn('w:r')), ['yellow', 'cyan', 'magenta'], strict=True):
        props = run.find(qn('w:rPr'))
        if props is None:
            props = OxmlElement('w:rPr')
            run.insert(0, props)
        tag = OxmlElement('w:highlight')
        tag.set(qn('w:val'), color)
        props.append(tag)
    # Theme-based font color and character shading are unrelated to named highlight.
    color = paragraph.runs[0]._r.rPr.find(qn('w:color'))
    color.set(qn('w:themeColor'), 'accent1')
    color.set(qn('w:themeTint'), '99')
    shade = OxmlElement('w:shd')
    shade.set(qn('w:val'), 'clear')
    shade.set(qn('w:fill'), 'EEEEEE')
    paragraph.runs[1]._r.rPr.append(shade)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def operation(content, value, **extra):
    target = inspect_docx(content)['blocks'][0]
    assert target['editable']
    return {'kind': 'formatParagraph', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'], 'style': {'highlight': value}, **extra}


def without_highlight(properties):
    if properties is None:
        return None
    clone = etree.fromstring(etree.tostring(properties))
    for child in list(clone):
        if child.tag == qn('w:highlight'):
            clone.remove(child)
    return etree.tostring(clone, method='c14n') if len(clone) or clone.attrib else None


@pytest.mark.parametrize('value', COLORS)
def test_highlight_roundtrip_keeps_mixed_source_properties_links_and_zip(value):
    content = highlighted_source()
    result = patch_docx(content, [operation(content, value)])
    before, after = Document(BytesIO(content)), Document(BytesIO(result))
    old, new = before.paragraphs[0]._p, after.paragraphs[0]._p
    assert etree.tostring(old.find(qn('w:pPr')), method='c14n') == etree.tostring(new.find(qn('w:pPr')), method='c14n')
    old_runs, new_runs = old.findall('.//' + qn('w:r')), new.findall('.//' + qn('w:r'))
    assert len(old_runs) == len(new_runs) == 3
    for a, b in zip(old_runs, new_runs, strict=True):
        assert a.find(qn('w:t')).text == b.find(qn('w:t')).text
        assert without_highlight(a.find(qn('w:rPr'))) == without_highlight(b.find(qn('w:rPr')))
        highlights = b.find(qn('w:rPr')).findall(qn('w:highlight'))
        assert len(highlights) == 1 and highlights[0].get(qn('w:val')) == value
    old_link, new_link = old.find(qn('w:hyperlink')), new.find(qn('w:hyperlink'))
    assert old_link.attrib == new_link.attrib
    assert after.part.rels[new_link.get(qn('r:id'))].target_ref == 'https://keep.test'
    assert new_link.find(qn('w:r')).find(qn('w:rPr')).find(qn('w:rStyle')) is None
    assert etree.tostring(before.paragraphs[1]._p) == etree.tostring(after.paragraphs[1]._p)
    with ZipFile(BytesIO(content)) as a, ZipFile(BytesIO(result)) as b:
        names = {name for name in a.namelist() if not name.endswith('/')}
        assert names == {name for name in b.namelist() if not name.endswith('/')}
        for name in names - {'word/document.xml', 'docProps/core.xml'}:
            assert a.read(name) == b.read(name), name


@pytest.mark.parametrize('style_type', ['paragraph', 'character'])
def test_clear_highlight_explicit_none_overrides_source_style_and_survives_fresh_edit(style_type):
    document = Document(BytesIO(highlighted_source()))
    paragraph = document.paragraphs[0]
    style = document.styles.add_style('InheritedHighlight', WD_STYLE_TYPE.PARAGRAPH if style_type == 'paragraph' else WD_STYLE_TYPE.CHARACTER)
    tag = OxmlElement('w:highlight')
    tag.set(qn('w:val'), 'green')
    style.element.get_or_add_rPr().append(tag)
    if style_type == 'paragraph':
        paragraph.style = style
    else:
        for run in paragraph.runs:
            run.style = style
    for run in paragraph._p.findall('.//' + qn('w:r')):
        props = run.find(qn('w:rPr'))
        for tag in props.findall(qn('w:highlight')):
            props.remove(tag)
    buffer = BytesIO()
    document.save(buffer)
    content = buffer.getvalue()
    result = patch_docx(content, [operation(content, 'none')])
    saved = Document(BytesIO(result))
    assert saved.styles['InheritedHighlight'].element.rPr.find(qn('w:highlight')).get(qn('w:val')) == 'green'
    for run in saved.paragraphs[0]._p.findall('.//' + qn('w:r')):
        assert run.find(qn('w:rPr')).find(qn('w:highlight')).get(qn('w:val')) == 'none'
    # A fresh parsed revision edited for another property must keep the explicit cancellation.
    later = operation(result, 'none')
    later['style'] = {'bold': True}
    again = patch_docx(result, [later])
    assert all(run.find(qn('w:rPr')).find(qn('w:highlight')).get(qn('w:val')) == 'none'
               for run in Document(BytesIO(again)).paragraphs[0]._p.findall('.//' + qn('w:r')))
    with pytest.raises(ValueError, match='anchor_invalid'):
        patch_docx(result, [operation(content, 'yellow')])


@pytest.mark.parametrize('value', [None, True, 1, '#FFFF00', 'FFFF00', 'accent1', 'Yellow', '', {}, []])
def test_highlight_rejects_non_ooxml_enums(value):
    content = highlighted_source()
    with pytest.raises(ValueError, match='highlight_invalid'):
        patch_docx(content, [operation(content, value)])


@pytest.mark.parametrize('extra', [{'from': 0}, {'rawRPr': '<w:rPr/>'}, {'expectedObjectSha256': 'foreign'}])
def test_highlight_rejects_foreign_identity_and_extra_operation_fields(extra):
    content = highlighted_source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, 'none', **extra)])


def test_highlight_rejects_theme_confusion_and_empty_source():
    content = highlighted_source()
    op = operation(content, 'yellow')
    op['style']['themeColor'] = 'accent1'
    with pytest.raises(ValueError):
        patch_docx(content, [op])
    empty = source(empty=True)
    with pytest.raises(ValueError, match='highlight_empty'):
        patch_docx(empty, [operation(empty, 'yellow')])
