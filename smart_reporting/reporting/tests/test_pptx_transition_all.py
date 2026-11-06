"""Apply-all uses existing source-indexed transition operations; independent file proof."""
from io import BytesIO
from zipfile import ZipFile

import pytest
from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches

from smart_reporting.report_editor.native_office import inspect_office, patch_office

KINDS = ['none', 'morph', 'fade', 'push', 'wipe', 'split', 'circle', 'cover', 'pull', 'dissolve', 'zoom', 'random']


def fixture_bytes():
    deck = Presentation()
    for index, effect in enumerate(['fade', 'push', None]):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = f'Source {index}'
        transition = OxmlElement('p:transition')
        transition.set('advTm', str(1000 * (index + 1)))
        if effect:
            transition.append(OxmlElement(f'p:{effect}'))
        slide._element.append(transition)
        timing = OxmlElement('p:timing')
        timing.append(OxmlElement('p:tnLst'))
        slide._element.append(timing)
    stream = BytesIO()
    deck.save(stream)
    return stream.getvalue()


def xml(node):
    return etree.tostring(node, method='c14n')


@pytest.mark.parametrize('kind', KINDS)
def test_effects_all_keep_source_timing_and_object_identity_through_reorder(kind):
    source = fixture_bytes()
    order = [2, 0, 1]
    edited = patch_office('pptx', source, [{'kind': 'editSlides', 'order': order,
                                          'transitions': [{'slideIndex': index, 'kind': kind} for index in order]}])
    before, after = Presentation(BytesIO(source)), Presentation(BytesIO(edited))
    assert [slide.shapes[0].text for slide in after.slides] == [f'Source {index}' for index in order]
    assert [slide['transition'] for slide in inspect_office('pptx', edited)['slides']] == [kind] * 3
    for output_index, source_index in enumerate(order):
        old, new = before.slides[source_index], after.slides[output_index]
        assert xml(old.shapes[0]._element) == xml(new.shapes[0]._element)
        assert xml(old._element.find(qn('p:timing'))) == xml(new._element.find(qn('p:timing')))
        transitions = [node for node in new._element.iter() if node.tag == qn('p:transition')]
        assert transitions and {node.get('advTm') for node in transitions} == {str(1000 * (source_index + 1))}
        effects = [etree.QName(node).localname for transition in transitions for node in transition]
        if kind == 'none':
            assert effects == []
        elif kind == 'morph':
            assert 'morph' in effects
        else:
            assert effects == [kind]
    with ZipFile(BytesIO(source)) as old, ZipFile(BytesIO(edited)) as new:
        files = {name for name in old.namelist() if not name.endswith('/')}
        assert files == {name for name in new.namelist() if not name.endswith('/')}
        allowed = {'ppt/presentation.xml', 'docProps/core.xml', *(f'ppt/slides/slide{i}.xml' for i in [1, 2, 3])}
        for name in files - allowed:
            assert old.read(name) == new.read(name), name


def test_partial_order_is_rejected_instead_of_dropping_source_slides():
    source = fixture_bytes()
    with pytest.raises(ValueError):
        patch_office('pptx', source, [{'kind': 'editSlides', 'order': [2, 0],
                                      'transitions': [{'slideIndex': 2, 'kind': 'wipe'}, {'slideIndex': 0, 'kind': 'wipe'}]}])


@pytest.mark.parametrize('setting', ['spd', 'advClick', 'sound', 'variant', 'extension', 'single_choice'])
def test_source_extra_transition_settings_are_inspected_readonly_for_apply_all(setting):
    original = Presentation(BytesIO(fixture_bytes()))
    transition = original.slides[0]._element.find(qn('p:transition'))
    if setting in {'spd', 'advClick'}:
        transition.set(setting, 'slow' if setting == 'spd' else '0')
    elif setting == 'sound':
        sound = OxmlElement('p:sndAc')
        sound.append(OxmlElement('p:endSnd'))
        transition.append(sound)
    elif setting == 'single_choice':
        parent = transition.getparent()
        parent.remove(transition)
        mc = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
        wrapper = etree.Element(f'{{{mc}}}AlternateContent', nsmap={'mc': mc, 'p14': 'http://schemas.microsoft.com/office/powerpoint/2010/main'})
        choice = etree.SubElement(wrapper, f'{{{mc}}}Choice', Requires='p14')
        choice.append(transition)
        parent.append(wrapper)
    elif setting == 'variant':
        transition[0].set('thruBlk', '1')
    else:
        transition.append(OxmlElement('p:extLst'))
    stream = BytesIO()
    original.save(stream)
    content = stream.getvalue()
    model = inspect_office('pptx', content)
    assert model['slides'][0]['transitionApplyAllSafe'] is False
    assert model['slides'][0]['transitionApplyAllReason'] == 'pptx_transition_additional_settings'
    assert all(slide['transitionApplyAllSafe'] is True for slide in model['slides'][1:])
    assert patch_office('pptx', content, []) == content
    assert xml(next(Presentation(BytesIO(content)).slides[0]._element.iter(qn('p:transition')))) == xml(transition)


def test_pinned_writer_default_effect_variant_is_modeled_but_source_timing_stays_individual():
    content = patch_office('pptx', fixture_bytes(), [{'kind': 'editSlides', 'transitions': [{'slideIndex': 0, 'kind': 'wipe'}]}])
    model = inspect_office('pptx', content)
    assert all(slide['transitionApplyAllSafe'] is True for slide in model['slides'])
    assert Presentation(BytesIO(content)).slides[0]._element.find(qn('p:transition')).get('advTm') == '1000'
