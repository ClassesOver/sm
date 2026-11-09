"""Multi-section page setup and section breaks through the native docx bridge."""
from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.oxml.ns import qn
from docx.shared import Twips

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def two_sections() -> bytes:
    doc = Document()
    doc.add_paragraph('first section')
    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_paragraph('second section')
    doc.add_paragraph('second tail')
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def block(model, text):
    return next(item for item in model['blocks'] if item['text'] == text)


def test_inspect_exposes_every_section_with_block_ranges():
    model = inspect_docx(two_sections())
    sections = model['sections']
    assert len(sections) == 2
    assert sections[0]['firstBlockIndex'] == 0 and sections[0]['lastBlockIndex'] < sections[1]['firstBlockIndex']
    assert all(set(section) >= {'sectionId', 'expectedSectionSha256', 'settings', 'startType'} for section in sections)


def test_layout_of_a_middle_section_patches_only_its_break_paragraph():
    source = two_sections()
    first = inspect_docx(source)['sections'][0]
    patched = patch_docx(source, [{'kind': 'setSectionLayout', 'sectionId': first['sectionId'], 'expectedSectionSha256': first['expectedSectionSha256'],
                                   'values': {'orientation': 'landscape', 'pageWidth': 15840, 'pageHeight': 12240, 'marginLeft': 720}}])
    sections = Document(BytesIO(patched)).sections
    assert sections[0].orientation == WD_ORIENT.LANDSCAPE and sections[0].page_width == Twips(15840) and sections[0].left_margin == Twips(720)
    assert sections[1].orientation == WD_ORIENT.PORTRAIT and sections[1].page_width == Twips(12240)
    assert [p.text for p in Document(BytesIO(patched)).paragraphs if p.text] == ['first section', 'second section', 'second tail']


@pytest.mark.parametrize(('kind', 'start'), [('nextPage', WD_SECTION.NEW_PAGE), ('continuous', WD_SECTION.CONTINUOUS), ('oddPage', WD_SECTION.ODD_PAGE)])
def test_section_break_splits_the_anchor_section_and_sets_the_new_section_start(kind, start):
    source = two_sections()
    anchor = block(inspect_docx(source), 'second section')
    patched = patch_docx(source, [{'kind': 'insertSectionBreak', 'blockId': anchor['blockId'], 'expectedObjectSha256': anchor['expectedObjectSha256'], 'type': kind}])
    doc = Document(BytesIO(patched))
    assert len(doc.sections) == 3
    assert doc.sections[2].start_type == start
    # the inserted break paragraph carries a copy of the section's sectPr right after the anchor
    paragraphs = doc.paragraphs
    index = next(i for i, p in enumerate(paragraphs) if p.text == 'second section')
    assert paragraphs[index + 1]._p.pPr.find(qn('w:sectPr')) is not None
    assert [p.text for p in paragraphs if p.text] == ['first section', 'second section', 'second tail']


def test_section_break_in_a_middle_section_retypes_its_break_paragraph():
    source = two_sections()
    anchor = block(inspect_docx(source), 'first section')
    patched = patch_docx(source, [{'kind': 'insertSectionBreak', 'blockId': anchor['blockId'], 'expectedObjectSha256': anchor['expectedObjectSha256'], 'type': 'continuous'}])
    doc = Document(BytesIO(patched))
    assert len(doc.sections) == 3
    assert doc.sections[1].start_type == WD_SECTION.CONTINUOUS
    assert doc.sections[2].start_type == WD_SECTION.NEW_PAGE


def test_section_operations_reject_conflicts_and_bad_input():
    source = two_sections()
    model = inspect_docx(source)
    second = model['sections'][1]
    anchor = block(model, 'second section')
    tail = block(model, 'second tail')
    brk = lambda target, kind='nextPage': {'kind': 'insertSectionBreak', 'blockId': target['blockId'], 'expectedObjectSha256': target['expectedObjectSha256'], 'type': kind}
    layout = {'kind': 'setSectionLayout', 'sectionId': second['sectionId'], 'expectedSectionSha256': second['expectedSectionSha256'], 'values': {'columns': 2}}
    for operations in ([brk(anchor), brk(tail)], [brk(anchor), layout], [brk(anchor, 'nextColumn')],
                       [{**brk(anchor), 'expectedObjectSha256': 'stale'}], [{**layout, 'sectionId': 'forged'}]):
        with pytest.raises(ValueError):
            patch_docx(source, operations)
    break_paragraph = next(item for item in model['blocks'] if item['blockId'] not in {anchor['blockId'], tail['blockId']} and item['text'] == '')
    with pytest.raises(ValueError, match='section_break_anchor_invalid'):
        patch_docx(source, [brk(break_paragraph)])
