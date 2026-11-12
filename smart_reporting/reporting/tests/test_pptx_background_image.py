"""PPTX 图片背景（拉伸/平铺/应用到多页）：真实原生 API 写入，python-pptx / OOXML 独立回读。"""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.native_office import _pptx_arguments, inspect_office, patch_office


def _png(color='#3366aa'):
    stream = BytesIO()
    Image.new('RGB', (40, 30), color).save(stream, format='PNG')
    return base64.b64encode(stream.getvalue()).decode()


def _deck():
    presentation = Presentation()
    for text in ('第一页', '第二页', '第三页'):
        presentation.slides.add_slide(presentation.slide_layouts[6]).shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = text
    output = BytesIO(); presentation.save(output)
    return output.getvalue()


def _record(indices, *, tile=False, data=None):
    return {'slideIndices': indices, 'bytesBase64': data or _png(), 'extension': 'png', 'tile': tile}


def test_background_image_applies_to_selected_slides_with_one_media_part():
    content = _deck()
    record = _record([0, 2], tile=True)
    assert _pptx_arguments({'kind': 'editSlides', 'backgroundImages': [record]})['background_images'] == [record]
    edited = patch_office('pptx', content, [{'kind': 'editSlides', 'backgroundImages': [record]}])
    model = inspect_office('pptx', edited)
    assert [slide['backgroundImage'] for slide in model['slides']] == [{'mode': 'tile'}, None, {'mode': 'tile'}]
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(edited)) as after:
        media = [name for name in after.namelist() if name.startswith('ppt/media/') and not name.endswith('/')]
        assert len(media) == 1 and hashlib.sha256(after.read(media[0])).hexdigest() == hashlib.sha256(base64.b64decode(record['bytesBase64'])).hexdigest()
        assert before.read('ppt/slides/slide2.xml') == after.read('ppt/slides/slide2.xml')
        for path in ('ppt/slides/slide1.xml', 'ppt/slides/slide3.xml'):
            assert '<a:tile' in after.read(path).decode()
    texts = [[shape.text for shape in slide.shapes] for slide in Presentation(BytesIO(edited)).slides]
    assert texts == [['第一页'], ['第二页'], ['第三页']]
    stretched = patch_office('pptx', edited, [{'kind': 'editSlides', 'backgroundImages': [_record([0])]}])
    assert inspect_office('pptx', stretched)['slides'][0]['backgroundImage'] == {'mode': 'stretch'}


@pytest.mark.parametrize('operation', [
    {'backgroundImages': [_record([])]},
    {'backgroundImages': [_record([0, 0])]},
    {'backgroundImages': [_record([0]), _record([0])]},
    {'backgroundImages': [_record([9])]},
    {'backgroundImages': [{**_record([0]), 'tile': 'yes'}]},
    {'backgroundImages': [{**_record([0]), 'extension': 'jpg'}]},
    {'backgroundImages': [{**_record([0]), 'extra': 1}]},
    {'backgroundImages': [_record([0], data='AAAA')]},
    {'backgroundImages': [_record([0])], 'backgrounds': [{'slideIndex': 0, 'color': '#FFFFFF'}]},
])
def test_invalid_background_images_are_rejected(operation):
    with pytest.raises(ValueError):
        patch_office('pptx', _deck(), [{'kind': 'editSlides', **operation}])


def test_gradient_reset_and_hidden_graphics_roundtrip_through_the_canonical_op():
    content = _deck()
    edited = patch_office('pptx', content, [{'kind': 'editSlides',
        'backgroundGradients': [{'slideIndices': [0, 1], 'from': '#FF0000', 'to': '#0000ff', 'angleDeg': 45, 'radial': False}],
        'backgroundGraphics': [{'slideIndex': 2, 'hidden': True}]}])
    slides = inspect_office('pptx', edited)['slides']
    assert [slide['backgroundGradient'] for slide in slides[:2]] == [{'from': '#FF0000', 'to': '#0000FF', 'radial': False, 'angleDeg': 45}] * 2
    assert [slide['backgroundGraphicsHidden'] for slide in slides] == [False, False, True]
    with ZipFile(BytesIO(edited)) as archive:
        assert '<a:lin ang="2700000"' in archive.read('ppt/slides/slide1.xml').decode()
        assert 'showMasterSp="0"' in archive.read('ppt/slides/slide3.xml').decode()
    reset = patch_office('pptx', edited, [{'kind': 'editSlides', 'backgroundResets': [0], 'backgroundGraphics': [{'slideIndex': 2, 'hidden': False}]}])
    slides = inspect_office('pptx', reset)['slides']
    assert slides[0]['backgroundOwn'] is False and slides[0]['backgroundGradient'] is None
    assert slides[1]['backgroundGradient']['angleDeg'] == 45 and slides[2]['backgroundGraphicsHidden'] is False
    texts = [[shape.text for shape in slide.shapes] for slide in Presentation(BytesIO(reset)).slides]
    assert texts == [['第一页'], ['第二页'], ['第三页']]


@pytest.mark.parametrize('operation', [
    {'backgroundGradients': [{'slideIndices': [0], 'from': '#FF0000', 'to': '#0000FF', 'angleDeg': 30, 'radial': False}]},
    {'backgroundGradients': [{'slideIndices': [0], 'from': '#FF0000', 'to': '#0000FF', 'angleDeg': 90, 'radial': True}]},
    {'backgroundGradients': [{'slideIndices': [0], 'from': 'red', 'to': '#0000FF', 'angleDeg': 0, 'radial': False}]},
    {'backgroundGradients': [{'slideIndices': [0], 'from': '#FF0000', 'to': '#0000FF', 'angleDeg': 0, 'radial': False}], 'backgroundResets': [0]},
    {'backgroundGradients': [{'slideIndices': [0], 'from': '#FF0000', 'to': '#0000FF', 'angleDeg': 0, 'radial': False}], 'backgrounds': [{'slideIndex': 0, 'color': '#FFFFFF'}]},
    {'backgroundResets': [0]},
    {'backgroundResets': [0, 0]},
    {'backgroundGraphics': [{'slideIndex': 0, 'hidden': 'yes'}]},
    {'backgroundGraphics': [{'slideIndex': 0, 'hidden': True}, {'slideIndex': 0, 'hidden': False}]},
])
def test_invalid_background_ops_are_rejected(operation):
    with pytest.raises(ValueError):
        patch_office('pptx', _deck(), [{'kind': 'editSlides', **operation}])
