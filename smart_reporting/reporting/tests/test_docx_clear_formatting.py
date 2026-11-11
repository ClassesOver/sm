"""Clear-all formatting: native atomic operation and independent OOXML readback."""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    doc = Document()
    p = doc.add_paragraph(style='Heading 1')
    p.paragraph_format.left_indent = Pt(36)
    p.paragraph_format.space_after = Pt(12)
    p.paragraph_format.page_break_before = True
    run = p.add_run('abcd')
    run.bold = True
    run.italic = True
    run.font.name = 'Arial'
    run.font.size = Pt(14)
    run = p.add_run('ef')
    run.italic = True
    doc.add_paragraph('untouched')
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def operation(data, ranges):
    block = inspect_docx(data)['blocks'][0]
    return {'kind': 'clearParagraphFormatting', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'ranges': ranges}


def test_partial_clear_restores_default_style_and_sheds_majority_direct_properties():
    data = source()
    patched = patch_docx(data, [operation(data, [{'from': 0, 'to': 1}])])
    p = Document(BytesIO(patched)).paragraphs[0]
    assert p.text == 'abcdef'
    assert p.style.style_id == 'Normal'
    assert p.paragraph_format.left_indent is None
    assert p.paragraph_format.space_after is None
    assert p.paragraph_format.page_break_before in (None, False)
    assert [(r.text, r.bold, r.italic, r.font.name) for r in p.runs] == [('a', None, None, None), ('bcd', True, None, 'Arial'), ('ef', None, None, None)]
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(patched)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name
    assert Document(BytesIO(patched)).paragraphs[1].text == 'untouched'


def test_full_clear_removes_direct_run_properties_but_keeps_list_numbering():
    doc = Document()
    p = doc.add_paragraph('abc', style='List Number')
    num = OxmlElement('w:numPr')
    level = OxmlElement('w:ilvl'); level.set(qn('w:val'), '0')
    ident = OxmlElement('w:numId'); ident.set(qn('w:val'), '5')
    num.extend([level, ident]); p._p.get_or_add_pPr().append(num)
    p.runs[0].bold = True
    stream = BytesIO(); doc.save(stream); data = stream.getvalue()
    patched = patch_docx(data, [operation(data, [{'from': 0, 'to': 3}])])
    p = Document(BytesIO(patched)).paragraphs[0]
    assert p.style.style_id == 'Normal'
    assert p.runs[0].bold is None
    assert p._p.pPr.numPr.numId.val == 5


@pytest.mark.parametrize('ranges', [[], [{'from': 0, 'to': 0}], [{'from': -1, 'to': 2}], [{'from': 0, 'to': 99}], [{'from': 0, 'to': 2, 'extra': True}]])
def test_clear_rejects_invalid_ranges(ranges):
    data = source()
    with pytest.raises(ValueError):
        patch_docx(data, [operation(data, ranges)])


def test_majority_font_clear_keeps_minority_ascii_slot_and_unrelated_xml():
    doc = Document()
    p = doc.add_paragraph()
    first = p.add_run('abcdef'); first.font.name = 'Arial'
    second = p.add_run('ghij')
    fonts = OxmlElement('w:rFonts'); fonts.set(qn('w:eastAsia'), 'SimSun')
    second._r.get_or_add_rPr().append(fonts)
    lang = OxmlElement('w:lang'); lang.set(qn('w:val'), 'en-US')
    first._r.get_or_add_rPr().append(lang)
    bidi = OxmlElement('w:bidi'); p._p.get_or_add_pPr().append(bidi)
    stream = BytesIO(); doc.save(stream); data = stream.getvalue()
    patched = patch_docx(data, [operation(data, [{'from': 0, 'to': 1}])])
    p = Document(BytesIO(patched)).paragraphs[0]
    assert p.runs[1].text == 'bcdef'
    assert p.runs[1].font.name == 'Arial'
    assert p.runs[1]._r.rPr.find(qn('w:lang')).get(qn('w:val')) == 'en-US'
    assert p._p.pPr.find(qn('w:bidi')) is not None


def test_majority_font_clear_preserves_east_asian_slot_without_ascii_or_cs():
    doc = Document()
    run = doc.add_paragraph().add_run('abcdefghij')
    run.font.name = 'Arial'
    run._r.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
    stream = BytesIO(); doc.save(stream); data = stream.getvalue()
    patched = patch_docx(data, [operation(data, [{'from': 0, 'to': 1}])])
    p = Document(BytesIO(patched)).paragraphs[0]
    assert p.runs[1].text == 'bcdefghij'
    assert p.runs[1]._r.rPr.rFonts.get(qn('w:eastAsia')) == 'SimSun'
    assert p.runs[1].font.name is None


def test_clear_materializes_numbering_inherited_from_previous_style():
    doc = Document()
    doc.add_paragraph('abc', style='List Number')
    stream = BytesIO(); doc.save(stream); data = stream.getvalue()
    before = inspect_docx(data)['blocks'][0]
    assert before['editable']
    patched = patch_docx(data, [operation(data, [{'from': 0, 'to': 3}])])
    p = Document(BytesIO(patched)).paragraphs[0]
    assert p.style.style_id == 'Normal'
    assert p._p.pPr.numPr is not None
    assert p._p.pPr.numPr.numId.val == 5
