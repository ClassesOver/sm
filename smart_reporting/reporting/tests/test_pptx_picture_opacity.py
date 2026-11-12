"""PPTX 图片透明度：真实原生 API 写入，python-pptx / OOXML 独立回读。"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from pptx import Presentation

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
