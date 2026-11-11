"""演讲者纯文本备注的真实OOXML往返、来源映射和拒绝契约。"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Inches

from smart_reporting.report_editor.native_office import (
    _pptx_arguments,
    inspect_office,
    patch_office,
)

TEXT = '  中文😀 $& & < > 字面&#10;\r\n\r内部空行\r\n末行  \r\n\n'
NORMALIZED = '  中文😀 $& & < > 字面&#10;\n\n内部空行\n末行  '
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
NOTES_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide'


def _source(*, register_master=True):
    deck = Presentation()
    for index in range(3):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = f'来源 {index}'
        if index == 0:
            slide.notes_slide.notes_text_frame.text = '已有备注\n第二行'
            image = BytesIO()
            Image.new('RGB', (32, 24), 'blue').save(image, 'PNG')
            slide.shapes.add_picture(BytesIO(image.getvalue()), Inches(1), Inches(3), Inches(2), Inches(1.5))
    if register_master:
        master_rel = next(rel for rel in deck.part.rels.values() if rel.reltype == RT.NOTES_MASTER)
        master_ids = etree.Element(qn('p:notesMasterIdLst'))
        etree.SubElement(master_ids, qn('p:notesMasterId')).set(qn('r:id'), master_rel.rId)
        deck._element.insert(deck._element.index(deck._element.find(qn('p:sldMasterIdLst'))) + 1, master_ids)
    output = BytesIO()
    deck.save(output)
    return output.getvalue()


def _patch(content, **changes):
    return patch_office('pptx', content, [{'kind': 'editSlides', **changes}])


def _notes(content):
    return {slide.shapes[0].text: slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ''
            for slide in Presentation(BytesIO(content)).slides}


def _parts(content):
    with ZipFile(BytesIO(content)) as archive:
        return {item.filename: archive.read(item.filename) for item in archive.infolist() if not item.is_dir()}


def _preserved(before, after, *, order=False, added=False):
    original, current = _parts(before), _parts(after)
    for path, data in original.items():
        if path.startswith('ppt/notesSlides/'):
            continue
        if added and path in ('[Content_Types].xml', 'ppt/slides/_rels/slide2.xml.rels'):
            continue
        if order and path in ('ppt/presentation.xml', 'ppt/_rels/presentation.xml.rels'):
            continue
        assert current[path] == data, path
    assert {path: data for path, data in original.items() if path.startswith('ppt/media/')} == {
        path: data for path, data in current.items() if path.startswith('ppt/media/')}


def _rewrite(content, updates):
    output = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(output, 'w') as target:
        for item in source.infolist():
            if not item.is_dir():
                target.writestr(item, updates.get(item.filename, source.read(item.filename)))
    return output.getvalue()


def test_notes_protocol_validates_reference_only_raw_utf16_limits():
    edits = [{'slideIndex': 0, 'text': '备注😀'}, {'slideIndex': 1, 'text': ''}]
    assert _pptx_arguments({'kind': 'editSlides', 'notesEdits': edits})['notes_edits'] == edits
    for accepted in ([{'slideIndex': 0, 'text': '😀' * 10000}],
                     [{'slideIndex': index, 'text': ''} for index in range(200)],
                     [{'slideIndex': index, 'text': 'a' * 20000} for index in range(10)]):
        assert _pptx_arguments({'kind': 'editSlides', 'notesEdits': accepted})['notes_edits'] == accepted
    invalid = [
        [{'slideIndex': True, 'text': 'x'}], [{'slideIndex': -1, 'text': 'x'}],
        [{'slideIndex': 0, 'text': None}], [{'slideIndex': 0, 'text': 'x', 'xml': '<p:notes/>'}],
        [{'slideIndex': 0, 'text': 'a'}, {'slideIndex': 0, 'text': 'b'}],
        [{'slideIndex': 0, 'text': '😀' * 10001}],
        [{'slideIndex': 0, 'text': '\r\n' * 10001}],
        [{'slideIndex': index, 'text': ''} for index in range(201)],
        [{'slideIndex': index, 'text': 'a' * 20000} for index in range(11)],
    ]
    for value in invalid:
        with pytest.raises(ValueError):
            _pptx_arguments({'kind': 'editSlides', 'notesEdits': value})


def test_notes_inspection_exposes_existing_and_absent_plain_text_sources():
    model = inspect_office('pptx', _source())
    assert [slide['notesText'] for slide in model['slides']] == ['已有备注\n第二行', '', '']
    assert all(slide['notesEditable'] is True and slide['notesReason'] is None for slide in model['slides'])


def test_notes_write_old_and_new_preserves_entities_spaces_and_unrelated_parts():
    content = _source()
    edited = _patch(content, notesEdits=[{'slideIndex': 0, 'text': TEXT}, {'slideIndex': 1, 'text': '新备注\n\n保留内部空行'}])
    assert _notes(edited) == {'来源 0': NORMALIZED, '来源 1': '新备注\n\n保留内部空行', '来源 2': ''}
    model = inspect_office('pptx', edited)
    assert [slide['notesText'] for slide in model['slides']] == [NORMALIZED, '新备注\n\n保留内部空行', '']
    _preserved(content, edited, added=True)


def test_notes_clear_existing_source_and_keep_other_notes_and_media():
    content = _source()
    edited = _patch(content, notesEdits=[{'slideIndex': 0, 'text': '\r\n\n'}])
    assert _notes(edited)['来源 0'] == ''
    assert inspect_office('pptx', edited)['slides'][0]['notesText'] == ''
    _preserved(content, edited)


def test_notes_edits_follow_original_slide_identity_after_reorder():
    content = _source()
    edited = _patch(content, notesEdits=[{'slideIndex': 0, 'text': '第零页新备注'}, {'slideIndex': 1, 'text': '第一页新备注'}], order=[2, 0, 1])
    deck = Presentation(BytesIO(edited))
    assert [slide.shapes[0].text for slide in deck.slides] == ['来源 2', '来源 0', '来源 1']
    assert _notes(edited) == {'来源 2': '', '来源 0': '第零页新备注', '来源 1': '第一页新备注'}
    assert [slide['notesText'] for slide in inspect_office('pptx', edited)['slides']] == ['', '第零页新备注', '第一页新备注']
    _preserved(content, edited, added=True, order=True)


def test_notes_invalid_source_delete_and_duplicate_conflicts_reject_atomically():
    content = _source()
    before = _parts(content)
    for changes in (
        {'notesEdits': [{'slideIndex': 0, 'text': '有效'}, {'slideIndex': 9, 'text': '无效'}]},
        {'deletedSlides': [0], 'order': [1, 2]},
        {'newSlides': [{'duplicateOf': 0}], 'order': [0, 1, 2, 3]},
    ):
        with pytest.raises(ValueError):
            _patch(content, **{'notesEdits': [{'slideIndex': 0, 'text': '不应部分写入'}], **changes})
        assert _parts(content) == before


def test_notes_shared_or_rich_sources_are_read_only_and_rejected():
    content = _source()
    parts = _parts(content)
    source_rels = etree.fromstring(parts['ppt/slides/_rels/slide1.xml.rels'])
    notes = next(item for item in source_rels if item.get('Type') == NOTES_REL)
    other_rels = etree.fromstring(parts['ppt/slides/_rels/slide2.xml.rels'])
    shared = etree.SubElement(other_rels, f'{{{REL_NS}}}Relationship')
    shared.set('Id', 'rIdNotesShared')
    shared.set('Type', NOTES_REL)
    shared.set('Target', notes.get('Target'))
    shared_content = _rewrite(content, {'ppt/slides/_rels/slide2.xml.rels': etree.tostring(other_rels)})
    rich_deck = Presentation(BytesIO(content))
    rich_deck.slides[0].notes_slide.notes_text_frame.paragraphs[0].runs[0].font.bold = True
    output = BytesIO()
    rich_deck.save(output)
    for unsafe in (shared_content, output.getvalue()):
        model = inspect_office('pptx', unsafe)
        assert model['slides'][0]['notesEditable'] is False
        assert model['slides'][0]['notesReason']
        before = _parts(unsafe)
        with pytest.raises(ValueError):
            _patch(unsafe, notesEdits=[{'slideIndex': 2, 'text': '有效'}, {'slideIndex': 0, 'text': '不安全'}])
        assert _parts(unsafe) == before


def test_unregistered_notes_master_is_read_only_and_patch_rejected():
    content = _source(register_master=False)
    model = inspect_office('pptx', content)
    assert model['slides'][0]['notesText'] == '已有备注\n第二行'
    assert all(slide['notesEditable'] is False and 'master_registration' in slide['notesReason'] for slide in model['slides'])
    before = _parts(content)
    with pytest.raises(ValueError):
        _patch(content, notesEdits=[{'slideIndex': 0, 'text': '不能使用未登记母版'}])
    assert _parts(content) == before
