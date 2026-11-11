"""隐藏页使用固定源原生属性；独立回读来源身份和部件保全。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from lxml import etree
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.native_office import _pptx_arguments, inspect_office, patch_office


def fixture_bytes():
    deck = Presentation()
    for index in range(3):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = f'来源页{index}'
        if index == 1:
            slide._element.set('show', '0')
    stream = BytesIO()
    deck.save(stream)
    return stream.getvalue()


def test_inspect_reads_native_hidden_flag():
    assert [s['hidden'] for s in inspect_office('pptx', fixture_bytes())['slides']] == [False, True, False]


def test_hidden_toggle_follows_source_through_reorder_and_preserves_other_parts(tmp_path):
    source = fixture_bytes()
    updated = patch_office('pptx', source, [{'kind': 'editSlides', 'order': [2, 0, 1],
        'hiddenSlides': [{'slideIndex': 0, 'hidden': True}, {'slideIndex': 1, 'hidden': False}]}])
    (tmp_path / 'source.pptx').write_bytes(source)
    (tmp_path / 'hidden.pptx').write_bytes(updated)
    deck = Presentation(BytesIO(updated))
    assert [s.shapes[0].text for s in deck.slides] == ['来源页2', '来源页0', '来源页1']
    assert [s._element.get('show', '1') for s in deck.slides] == ['1', '0', '1']
    assert [s['hidden'] for s in inspect_office('pptx', updated)['slides']] == [False, True, False]
    with ZipFile(BytesIO(source)) as old, ZipFile(BytesIO(updated)) as new:
        allowed = {'ppt/slides/slide1.xml', 'ppt/slides/slide2.xml', 'ppt/presentation.xml', 'docProps/core.xml'}
        assert {name for name in old.namelist() if not name.endswith('/')} == {name for name in new.namelist() if not name.endswith('/')}
        for name in old.namelist():
            if name not in allowed:
                assert old.read(name) == new.read(name), name
        for name in ['ppt/slides/slide1.xml', 'ppt/slides/slide2.xml']:
            before, after = etree.fromstring(old.read(name)), etree.fromstring(new.read(name))
            before.attrib.pop('show', None)
            after.attrib.pop('show', None)
            assert etree.tostring(before, method='c14n') == etree.tostring(after, method='c14n')


@pytest.mark.parametrize('records', [[{'slideIndex': 0, 'hidden': 1}], [{'slideIndex': True, 'hidden': True}],
    [{'slideIndex': -1, 'hidden': True}], [{'slideIndex': 0, 'hidden': True, 'extra': 1}],
    [{'slideIndex': 0, 'hidden': True}, {'slideIndex': 0, 'hidden': False}], None])
def test_invalid_hidden_records_rejected_before_engine(records):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'hiddenSlides': records})


def test_bool_hidden_records_forward_to_engine():
    records = [{'slideIndex': 0, 'hidden': False}]
    assert _pptx_arguments({'kind': 'editSlides', 'hiddenSlides': records})['hidden_slides'] == records


@pytest.mark.parametrize('record', [{'slideIndex': 3, 'hidden': True}, {'slideIndex': 0, 'hidden': 'true'}])
def test_direct_engine_rejects_invalid_hidden_records(record):
    from smart_reporting.report_editor.slides import ReportSlidesEditorService
    from smart_reporting.reporting.models import ReportingError
    with pytest.raises(ReportingError, match="hidden_slides_invalid"):
        ReportSlidesEditorService._run_engine(fixture_bytes(), 'edit', hidden_slides=[record])


def test_cannot_hide_and_delete_the_same_source_slide():
    with pytest.raises(ValueError):
        patch_office('pptx', fixture_bytes(), [{'kind': 'editSlides', 'order': [1, 2], 'deletedSlides': [0],
            'hiddenSlides': [{'slideIndex': 0, 'hidden': True}]}])


def test_ai_candidate_keeps_manual_hidden_flags_and_original_base():
    from copy import deepcopy
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    base = [{'kind': 'editSlides', 'hiddenSlides': [{'slideIndex': 0, 'hidden': True}], 'order': [1, 0]}]
    original = deepcopy(base)
    candidate = [{'kind': 'editSlides', 'edits': [{'slideIndex': 1, 'elementId': 'title', 'text': 'AI标题'}]}]
    combined = NativeSlidesAIService._combined_operations(None, base, candidate)
    assert combined[0]['hiddenSlides'] == base[0]['hiddenSlides']
    assert combined[0]['order'] == [1, 0]
    assert base == original
