"""PPTX 裁切、图片几何与连接线跟随，使用真实原生 API 及独立 OOXML 回读。"""
from __future__ import annotations

import base64
from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.util import Inches

from smart_reporting.report_editor.native_office import (
    _pptx_arguments,
    inspect_office,
    patch_office,
)


def _png(color='red'):
    stream = BytesIO()
    Image.new('RGB', (80, 60), color).save(stream, format='PNG')
    return stream.getvalue()


def _presentation(*, transformed=False, connected=False):
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    title = slide.shapes.title
    inherited_left = title.left
    title.left += Inches(1)
    title.text = '未修改的标题'
    first = slide.shapes.add_picture(BytesIO(_png()), Inches(1), Inches(3), width=Inches(2))
    first.name = '裁切目标'
    second = slide.shapes.add_picture(BytesIO(_png()), Inches(4), Inches(3), width=Inches(2))
    second.name = '共享媒体保留'
    if transformed is True or transformed == 'rotation':
        first.rotation = 30
    if transformed is True or transformed == 'flip':
        first._element.spPr.xfrm.set('flipH', '1')
    if connected:
        left = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1), Inches(1), Inches(1), Inches(1))
        left.name = '左形状'
        right = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(4), Inches(2), Inches(1), Inches(1))
        right.name = '右形状'
        connector = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(2), Inches(1.5), Inches(4.5), Inches(2))
        connector.name = '跟随连接线'
        connector.begin_connect(left, 3)
        connector.end_connect(right, 0)
    untouched = presentation.slides.add_slide(presentation.slide_layouts[6])
    untouched.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1)).text = '另一页保持原样'
    output = BytesIO()
    presentation.save(output)
    return output.getvalue(), inherited_left


def _target(content, name='裁切目标'):
    return next(element for element in inspect_office('pptx', content)['slides'][0]['elements'] if element['name'] == name)


def _crop(target, *, rect=None, geometry=None):
    return {'slideIndex': 0, 'elementId': target['id'], 'expectedSha256': target['pictureSha256'],
            'expectedSize': target['pictureSize'], 'srcRect': rect,
            'geometry': geometry or {'x': 120, 'y': 300, 'width': 160, 'height': 100}}


def _patch(content, **operation):
    return patch_office('pptx', content, [{'kind': 'editSlides', **operation}])


def test_pptx_arguments_forward_picture_crops_without_mutating_the_journal():
    record = {'slideIndex': 0, 'elementId': 'picture_1', 'expectedSha256': 'a' * 64, 'expectedSize': 100,
              'srcRect': {'l': .1, 't': .2, 'r': .1, 'b': .1}, 'geometry': {'x': 10, 'y': 20, 'width': 80, 'height': 60}}
    operation = {'kind': 'editSlides', 'pictureCrops': [record]}
    assert _pptx_arguments(operation)['picture_crops'] == [record]
    assert operation['pictureCrops'] == [record]


def test_crop_is_nondestructive_for_shared_media_and_null_restores_full_image_after_reset_reorder():
    content, inherited_left = _presentation()
    target = _target(content)
    original = Presentation(BytesIO(content)).slides[0]
    original_other = next(shape for shape in original.shapes if shape.name == '共享媒体保留')
    edited = _patch(content, pictureCrops=[_crop(target, rect={'l': .1, 't': .2, 'r': .15, 'b': .05})],
                    resetLayouts=[0], order=[1, 0])
    read = Presentation(BytesIO(edited)).slides[1]
    picture = next(shape for shape in read.shapes if shape.name == '裁切目标')
    other = next(shape for shape in read.shapes if shape.name == '共享媒体保留')
    assert (picture.crop_left, picture.crop_top, picture.crop_right, picture.crop_bottom) == pytest.approx((.1, .2, .15, .05))
    assert (picture.left, picture.top, picture.width, picture.height) == tuple(value * 9525 for value in (120, 300, 160, 100))
    assert picture.image.blob == other.image.blob == _png()
    assert other._element.xml == original_other._element.xml
    assert read.shapes.title.left == inherited_left
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(edited)) as after:
        for path in before.namelist():
            if path.startswith('ppt/media/') or path == 'ppt/slides/_rels/slide1.xml.rels':
                assert before.read(path) == after.read(path), path
    target = next(element for element in inspect_office('pptx', edited)['slides'][1]['elements'] if element['name'] == '裁切目标')
    restore = _crop(target, rect=None, geometry={'x': 96, 'y': 288, 'width': 192, 'height': 144})
    restore['slideIndex'] = 1
    restored = _patch(edited, pictureCrops=[restore])
    picture = next(shape for shape in Presentation(BytesIO(restored)).slides[1].shapes if shape.name == '裁切目标')
    assert (picture.crop_left, picture.crop_top, picture.crop_right, picture.crop_bottom) == (0, 0, 0, 0)
    assert picture.image.blob == _png()


def test_generic_picture_geometry_preserves_source_rotation_flip_and_unrelated_parts():
    content, _ = _presentation(transformed=True)
    target = _target(content)
    edited = _patch(content, edits=[{'slideIndex': 0, 'elementId': target['id'],
                                    'geometry': {'x': 30, 'y': 60, 'width': 240, 'height': 180}}])
    picture = next(shape for shape in Presentation(BytesIO(edited)).slides[0].shapes if shape.name == '裁切目标')
    assert (picture.left, picture.top, picture.width, picture.height) == tuple(value * 9525 for value in (30, 60, 240, 180))
    assert picture.rotation == 30
    assert picture._element.spPr.xfrm.get('flipH') == '1'
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(edited)) as after:
        for path in before.namelist():
            if path != 'ppt/slides/slide1.xml':
                assert before.read(path) == after.read(path), path


def test_arranging_a_shape_updates_attached_connector_and_preserves_untouched_slide():
    content, _ = _presentation(connected=True)
    target = _target(content, '右形状')
    edited = _patch(content, edits=[{'slideIndex': 0, 'elementId': target['id'],
                                    'geometry': {'x': 600, 'y': 150, 'width': 96, 'height': 96}}])
    slide = Presentation(BytesIO(edited)).slides[0]
    right = next(shape for shape in slide.shapes if shape.name == '右形状')
    line = next(shape for shape in slide.shapes if shape.name == '跟随连接线')
    assert (line.end_x, line.end_y) == (right.left + right.width // 2, right.top)
    assert (line.begin_x, line.begin_y) == (Inches(2), Inches(1.5))
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(edited)) as after:
        for path in before.namelist():
            if path != 'ppt/slides/slide1.xml':
                assert before.read(path) == after.read(path), path


def test_crop_rejects_invalid_rect_identity_unsafe_sources_and_same_target_replacement():
    content, _ = _presentation()
    target = _target(content)
    for rect in ({'l': -.1, 't': 0, 'r': 0, 'b': 0}, {'l': .5, 't': 0, 'r': .5, 'b': 0},
                 {'l': 0, 't': 0, 'r': 0, 'b': True}, {'l': 0, 't': 0, 'r': 0, 'b': 0, 'extra': 1}):
        with pytest.raises(ValueError):
            _patch(content, pictureCrops=[_crop(target, rect=rect)])
    invalid_identity = _crop(target)
    invalid_identity['expectedSha256'] = '0' * 64
    with pytest.raises(ValueError):
        _patch(content, pictureCrops=[invalid_identity])
    invalid_size = _crop(target)
    invalid_size['expectedSize'] += 1
    with pytest.raises(ValueError):
        _patch(content, pictureCrops=[invalid_size])
    replacement = {key: value for key, value in _crop(target).items() if key not in ('srcRect', 'geometry')}
    replacement.update(extension='png', bytesBase64=base64.b64encode(_png('blue')).decode())
    with pytest.raises(ValueError):
        _patch(content, pictureCrops=[_crop(target)], pictureReplacements=[replacement])
    for transformation in ('rotation', 'flip'):
        unsafe, _ = _presentation(transformed=transformation)
        with pytest.raises(ValueError):
            _patch(unsafe, pictureCrops=[_crop(_target(unsafe))])
