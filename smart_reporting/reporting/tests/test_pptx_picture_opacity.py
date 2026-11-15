"""PPTX 图片透明度：真实原生 API 写入，python-pptx / OOXML 独立回读。"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.util import Pt

from smart_reporting.report_editor.native_office import _pptx_arguments, inspect_office, patch_office
from smart_reporting.reporting.tests.test_pptx_crop_arrange import _crop, _png, _presentation, _target


def _opacity(target, value):
    return {'slideIndex': 0, 'elementId': target['id'], 'expectedSha256': target['pictureSha256'],
            'expectedSize': target['pictureSize'], 'opacity': value}


def _alpha(content, name):
    slide = Presentation(BytesIO(content)).slides[0]
    shape = next(item for item in slide.shapes if item.name == name)
    nodes = shape._element.xpath('.//a:blip/a:alphaModFix')
    return int(nodes[0].get('amt')) if nodes else None


def test_opacity_roundtrips_only_on_the_target_and_combines_with_crop():
    content, _ = _presentation()
    target = _target(content)
    assert target['pictureOpacityEditable'] is True and target['pictureOpacity'] == 1
    record = _opacity(target, 0.35)
    operation = {'kind': 'editSlides', 'pictureOpacities': [record]}
    assert _pptx_arguments(operation)['picture_opacities'] == [record]
    edited = patch_office('pptx', content, [{'kind': 'editSlides', 'pictureOpacities': [record],
                                             'pictureCrops': [_crop(target, rect={'l': .1, 't': 0, 'r': 0, 'b': 0})]}])
    assert _alpha(edited, '裁切目标') == 35000
    assert _alpha(edited, '共享媒体保留') is None
    slide = Presentation(BytesIO(edited)).slides[0]
    picture = next(shape for shape in slide.shapes if shape.name == '裁切目标')
    assert picture.crop_left == pytest.approx(.1) and picture.image.blob == _png()
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(edited)) as after:
        assert before.read('ppt/slides/slide2.xml') == after.read('ppt/slides/slide2.xml')
        media = lambda archive: {name: archive.read(name) for name in archive.namelist() if name.startswith('ppt/media/') and not name.endswith('/')}
        assert media(after) == media(before)
    reopened = _target(edited)
    assert reopened['pictureOpacity'] == 0.35
    cleared = patch_office('pptx', edited, [{'kind': 'editSlides', 'pictureOpacities': [_opacity(reopened, 1)]}])
    assert _alpha(cleared, '裁切目标') is None
    assert _target(cleared)['pictureOpacity'] == 1


@pytest.mark.parametrize('patch', [
    {'opacity': 1.2}, {'opacity': -0.1}, {'opacity': 0.333}, {'opacity': '0.5'}, {'opacity': True},
    {'expectedSha256': 'f' * 64}, {'expectedSize': 1}, {'elementId': 'missing'}, {'extra': 1},
])
def test_invalid_or_stale_opacity_requests_are_rejected(patch):
    content, _ = _presentation()
    record = {**_opacity(_target(content), 0.5), **patch}
    with pytest.raises(ValueError):
        patch_office('pptx', content, [{'kind': 'editSlides', 'pictureOpacities': [record]}])


def test_duplicate_and_deleted_targets_are_rejected():
    content, _ = _presentation()
    record = _opacity(_target(content), 0.5)
    for operation in ({'pictureOpacities': [record, record]},
                      {'pictureOpacities': [record], 'deletions': [{'slideIndex': 0, 'elementId': record['elementId']}]}):
        with pytest.raises(ValueError):
            patch_office('pptx', content, [{'kind': 'editSlides', **operation}])

def test_native_picture_rotation_and_flip_preserve_center_and_media():
    content, _ = _presentation()
    target_name = _target(content)['name']
    before = next(shape for shape in Presentation(BytesIO(content)).slides[0].shapes if shape.name == target_name)
    transform = {'rot': 90 * 60000, 'flipH': True, 'flipV': False}
    edited = patch_office('pptx', content, [{'kind': 'editSlides', 'edits': [
        {'slideIndex': 0, 'elementId': _target(content)['id'], 'pictureTransform': transform},
    ]}])
    after = next(shape for shape in Presentation(BytesIO(edited)).slides[0].shapes if shape.name == target_name)
    assert after.rotation == 90
    assert (after.left, after.top, after.width, after.height) == (before.left, before.top, before.width, before.height)
    assert after.image.blob == before.image.blob
    assert after._element.xpath('.//a:xfrm')[0].get('flipH') == '1'
    assert _target(edited)['pictureTransform'] == transform
    assert [shape.rotation for shape in Presentation(BytesIO(edited)).slides[0].shapes if shape.name != target_name] == [
        shape.rotation for shape in Presentation(BytesIO(content)).slides[0].shapes if shape.name != target_name
    ]


def test_picture_crop_and_orientation_roundtrip_in_the_same_revision():
    content, _ = _presentation()
    target = _target(content)
    transform = {'rot': 90 * 60000, 'flipH': True, 'flipV': False}
    edited = patch_office('pptx', content, [{
        'kind': 'editSlides',
        'edits': [{'slideIndex': 0, 'elementId': target['id'], 'pictureTransform': transform}],
        'pictureCrops': [_crop(target, rect={'l': .25, 't': 0, 'r': 0, 'b': 0})],
    }])
    result = _target(edited)
    assert result['pictureTransform'] == transform
    picture = next(shape for shape in Presentation(BytesIO(edited)).slides[0].shapes if shape.name == target['name'])
    assert picture.crop_left == pytest.approx(.25)
    assert picture.rotation == 90
    assert picture.image.blob == _png()


def test_native_picture_outline_preserves_existing_dash_and_media():
    content, _ = _presentation()
    target_name = _target(content)['name']

    def picture(presentation, name=target_name):
        return next(shape for shape in presentation.slides[0].shapes if shape.name == name)

    source = Presentation(BytesIO(content))
    original = picture(source)
    original.line.color.rgb = RGBColor.from_string('C01A46')
    original.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    original.line.width = Pt(1)
    fixture = BytesIO()
    source.save(fixture)
    content = fixture.getvalue()

    def apply(data, **style):
        return patch_office('pptx', data, [{'kind': 'editSlides', 'shapeStyles': [
            {'slideIndex': 0, 'elementId': _target(data)['id'], **style},
        ]}])

    updated = apply(content, stroke={'color': '#123456', 'widthPt': 2.25})
    result = Presentation(BytesIO(updated))
    edited = picture(result)
    assert str(edited.line.color.rgb) == '123456'
    assert edited.line.width == Pt(2.25)
    assert edited.line.dash_style == MSO_LINE_DASH_STYLE.DASH
    assert edited.image.blob == original.image.blob
    assert picture(result, '共享媒体保留')._element.xpath('./p:spPr/a:ln') == []
    cleared = picture(Presentation(BytesIO(apply(updated, stroke=None))))
    assert cleared._element.xpath('./p:spPr/a:ln/a:noFill')
    with pytest.raises(ValueError):
        apply(content, fill='#123456')
