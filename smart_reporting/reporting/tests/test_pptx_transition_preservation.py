"""Native effect changes retain actual source transition metadata and related bytes."""
from __future__ import annotations

import wave
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn

from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.reporting.tests.test_pptx_transition_all import KINDS, fixture_bytes

P14 = 'http://schemas.microsoft.com/office/powerpoint/2010/main'
AUDIT = 'urn:transition-preservation-test'
MC = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
EFFECTS = set(KINDS) - {'none'}


def canonical(node):
    return etree.tostring(node, method='c14n')


def source_bytes(*, alternate=False, single_quote=False):
    content = fixture_bytes()
    if alternate:
        content = patch_office('pptx', content, [{'kind': 'editSlides', 'transitions': [{'slideIndex': 0, 'kind': 'morph'}]}])
    deck = Presentation(BytesIO(content))
    transitions = list(deck.slides[0]._element.iter(qn('p:transition')))
    for index, original in enumerate(transitions):
        # Local namespaces must survive a transition that is moved into MC branches.
        transition = etree.Element(qn('p:transition'), nsmap={'p14': P14, 'audit': AUDIT, 'mc': MC})
        transition.attrib.update(original.attrib)
        transition.set('spd', 'fast' if index == 0 else 'slow')
        transition.set('advClick', '0' if index == 0 else '1')
        transition.set('advTm', str(1234 + index))
        transition.set(f'{{{P14}}}dur', str(725 + index))
        transition.set(f'{{{MC}}}Ignorable', 'audit')
        transition.set(f'{{{AUDIT}}}note', "literal $& $` $' >")
        for child in original:
            transition.append(child)
        sound = etree.SubElement(transition, qn('p:sndAc'))
        start = etree.SubElement(sound, qn('p:stSnd'), loop='1')
        etree.SubElement(start, qn('p:snd'), {qn('r:embed'): 'rIdAudio', 'name': 'fixture.wav'})
        extensions = etree.SubElement(transition, qn('p:extLst'))
        extension = etree.SubElement(extensions, qn('p:ext'), uri='urn:test:extension')
        etree.SubElement(extension, f'{{{AUDIT}}}data').text = 'keep $& metadata'
        original.getparent().replace(original, transition)
    output = BytesIO()
    deck.save(output)
    wav = BytesIO()
    with wave.open(wav, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(1)
        audio.setframerate(8000)
        audio.writeframes(bytes([128] * 8))
    result = BytesIO()
    with ZipFile(BytesIO(output.getvalue())) as archive, ZipFile(result, 'w', ZIP_DEFLATED) as edited:
        for name in archive.namelist():
            if name.endswith('/'):
                continue
            data = archive.read(name)
            if name == 'ppt/slides/_rels/slide1.xml.rels':
                root = etree.fromstring(data)
                etree.SubElement(root, f'{{{REL}}}Relationship', Id='rIdAudio', Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio', Target='../media/fixture.wav')
                data = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
            if name == '[Content_Types].xml':
                root = etree.fromstring(data)
                etree.SubElement(root, '{http://schemas.openxmlformats.org/package/2006/content-types}Default', Extension='wav', ContentType='audio/wav')
                data = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
            if name == 'ppt/slides/slide1.xml' and single_quote:
                data = data.replace(b'advTm="1234"', b"advTm = '1234'")
            edited.writestr(name, data)
        edited.writestr('ppt/media/fixture.wav', wav.getvalue())
    return result.getvalue()


def metadata(transition):
    return dict(transition.attrib), [etree.tostring(child, method='c14n', exclusive=True) for child in transition if etree.QName(child).localname not in EFFECTS]


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('alternate', [False, True])
def test_single_effect_changes_preserve_metadata_audio_and_package(kind, alternate):
    source = source_bytes(alternate=alternate)
    before = Presentation(BytesIO(source))
    old = list(before.slides[0]._element.iter(qn('p:transition')))
    assert inspect_office('pptx', source)['slides'][0]['transitionEditSafe'] is True
    result = patch_office('pptx', source, [{'kind': 'editSlides', 'transitions': [{'slideIndex': 0, 'kind': kind}]}])
    after = Presentation(BytesIO(result))
    actual = list(after.slides[0]._element.iter(qn('p:transition')))
    expected_sources = old if alternate or kind != 'morph' else [old[0], old[0]]
    assert len(actual) == len(expected_sources)
    for previous, current in zip(expected_sources, actual, strict=True):
        assert metadata(current) == metadata(previous)
        assert current.find(qn('p:sndAc')).find(qn('p:stSnd')).find(qn('p:snd')).get(qn('r:embed')) == 'rIdAudio'
    assert inspect_office('pptx', result)['slides'][0]['transition'] == kind
    assert canonical(after.slides[0].shapes[0]._element) == canonical(before.slides[0].shapes[0]._element)
    assert canonical(after.slides[0]._element.find(qn('p:timing'))) == canonical(before.slides[0]._element.find(qn('p:timing')))
    for index in [1, 2]:
        assert canonical(after.slides[index]._element) == canonical(before.slides[index]._element)
    with ZipFile(BytesIO(source)) as original_zip, ZipFile(BytesIO(result)) as result_zip:
        names = {name for name in original_zip.namelist() if not name.endswith('/')}
        assert names == {name for name in result_zip.namelist() if not name.endswith('/')}
        for name in names - {'ppt/slides/slide1.xml', 'docProps/core.xml', 'ppt/presentation.xml'}:
            assert original_zip.read(name) == result_zip.read(name), name
    assert patch_office('pptx', source, []) == source


def test_noncanonical_attribute_quotes_and_same_effect_keep_source_transition_exact():
    source = source_bytes(single_quote=True)
    before = Presentation(BytesIO(source)).slides[0]._element.find(qn('p:transition'))
    result = patch_office('pptx', source, [{'kind': 'editSlides', 'transitions': [{'slideIndex': 0, 'kind': 'fade'}]}])
    assert canonical(Presentation(BytesIO(result)).slides[0]._element.find(qn('p:transition'))) == canonical(before)
    result = patch_office('pptx', source, [{'kind': 'editSlides', 'transitions': [{'slideIndex': 0, 'kind': 'wipe'}]}])
    assert metadata(Presentation(BytesIO(result)).slides[0]._element.find(qn('p:transition'))) == metadata(before)


def test_opaque_extension_cannot_masquerade_as_the_visual_transition():
    deck = Presentation(BytesIO(source_bytes()))
    extension = deck.slides[0]._element.find(qn('p:transition')).find(qn('p:extLst'))[0]
    etree.SubElement(extension, '{http://schemas.microsoft.com/office/powerpoint/2015/main}morph')
    output = BytesIO()
    deck.save(output)
    source = output.getvalue()
    assert inspect_office('pptx', source)['slides'][0]['transition'] == 'fade'
    result = patch_office('pptx', source, [{'kind': 'editSlides', 'transitions': [{'slideIndex': 0, 'kind': 'morph'}]}])
    assert inspect_office('pptx', result)['slides'][0]['transition'] == 'morph'
    assert any(etree.QName(child).localname == 'morph' for child in Presentation(BytesIO(result)).slides[0]._element.find('.//' + qn('p:extLst'))[0])


@pytest.mark.parametrize('case', ['single_choice', 'unknown_effect', 'duplicate'])
def test_unsupported_source_is_readonly_and_forced_request_is_rejected(case):
    deck = Presentation(BytesIO(fixture_bytes()))
    slide = deck.slides[0]._element
    original = slide.find(qn('p:transition'))
    if case == 'single_choice':
        slide.remove(original)
        wrapper = etree.SubElement(slide, f'{{{MC}}}AlternateContent', nsmap={'mc': MC, 'p14': P14})
        etree.SubElement(wrapper, f'{{{MC}}}Choice', Requires='p14').append(original)
    elif case == 'unknown_effect':
        original.remove(original[0])
        etree.SubElement(original, qn('p:blinds'), dir='horz')
    else:
        from copy import deepcopy
        slide.append(deepcopy(original))
    output = BytesIO()
    deck.save(output)
    source = output.getvalue()
    state = inspect_office('pptx', source)['slides'][0]
    assert state['transitionEditSafe'] is False
    assert state['transitionEditReason'] == 'pptx_transition_source_unsupported'
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        patch_office('pptx', source, [{'kind': 'editSlides', 'transitions': [{'slideIndex': 0, 'kind': 'wipe'}]}])
    assert patch_office('pptx', source, []) == source
