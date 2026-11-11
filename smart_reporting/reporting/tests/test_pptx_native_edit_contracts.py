"""本轮原生图片与图表请求必须通过严格宿主协议后才能进入文件引擎。"""
from base64 import b64encode
from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.native_office import (
    _pptx_arguments,
    inspect_office,
    patch_office,
)


def image_record():
    data = BytesIO()
    Image.new('RGB', (3, 2), 'red').save(data, 'PNG')
    return {'slideIndex': 0, 'bytesBase64': b64encode(data.getvalue()).decode(),
        'extension': 'png', 'geometry': {'x': 1, 'y': 2, 'width': 30, 'height': 20}}


def test_native_picture_insertions_forward_without_ai_candidate_protocol():
    record = image_record()
    assert _pptx_arguments({'kind': 'editSlides', 'images': [record]})['native_images'] == [record]


def test_native_picture_preserves_positive_subpixel_geometry():
    record = image_record()
    record['geometry'].update(width=0.5, height=0.25)
    assert _pptx_arguments({'kind': 'editSlides', 'images': [record]})['native_images'] == [record]


def test_native_picture_replacement_binds_original_media_identity():
    record = image_record()
    record.pop('geometry')
    record.update(elementId='picture-1', expectedSha256='a' * 64, expectedSize=74)
    assert _pptx_arguments({'kind': 'editSlides', 'pictureReplacements': [record]})['picture_replacements'] == [record]


def test_native_chart_data_and_kind_share_the_existing_revision_operation():
    record = {'slideIndex': 0, 'elementId': 'chart-1', 'kind': 'line',
        'categories': ['甲', '乙'], 'series': [{'name': '收入', 'values': [1, 2]}]}
    assert _pptx_arguments({'kind': 'editSlides', 'chartEdits': [record]})['chart_edits'] == [record]


@pytest.mark.parametrize('changes', [
    {'images': [dict(image_record(), bytesBase64='not base64')]},
    {'images': [dict(image_record(), slideIndex=True)]},
    {'images': [dict(image_record(), extension='svg')]},
    {'images': [dict(image_record(), bytesBase64=b64encode(b'not an image').decode())]},
    {'images': [dict(image_record(), geometry={'x': 0, 'y': 0, 'width': 0, 'height': 1})]},
    {'chartEdits': [{'slideIndex': 0, 'elementId': 'chart-1', 'categories': ['甲']}]},
    {'chartEdits': [{'slideIndex': 0, 'elementId': 'chart-1', 'kind': 'unknown'}]},
    {'chartEdits': [{'slideIndex': 0, 'elementId': 'chart-1', 'kind': 'line', 'extra': 1}]},
    {'chartEdits': [{'slideIndex': 0, 'elementId': 'chart-1', 'categories': ['甲'], 'series': [{'name': '甲', 'values': [True]}]}]},
    {'pictureReplacements': [{'slideIndex': 0, 'elementId': 'picture-1', 'expectedSha256': 'wrong'}]},
])
def test_invalid_native_media_and_chart_requests_are_rejected(changes):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', **changes})


def test_native_media_and_text_edits_roundtrip_together_on_original_page_identity(tmp_path):
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = '收入 收入'
    original_image = image_record()
    import base64
    slide.shapes.add_picture(BytesIO(base64.b64decode(original_image['bytesBase64'])), Inches(2), Inches(2))
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = '保留来源页'
    content = BytesIO()
    deck.save(content)
    source = patch_office('pptx', content.getvalue(), [{'kind': 'editSlides', 'charts': [{
        'slideIndex': 0, 'kind': 'bar', 'categories': ['甲', '乙'], 'series': [{'name': '收入', 'values': [1, 2]}]}]}])
    inspected = inspect_office('pptx', source)
    elements = inspected['slides'][0]['elements']
    picture = next(element for element in elements if element['type'] == 'picture')
    chart = next(element for element in elements if element['type'] == 'chart')
    text = next(element for element in elements if element['type'] == 'text')
    assert text['findReplaceEditable'] is True
    assert chart['chartEditSafe'] is True
    replacement_data = BytesIO()
    Image.new('RGB', (5, 4), 'blue').save(replacement_data, 'PNG')
    replacement = dict(original_image, bytesBase64=b64encode(replacement_data.getvalue()).decode())
    replacement.pop('geometry')
    replacement.update(elementId=picture['id'], expectedSha256=picture['pictureSha256'], expectedSize=picture['pictureSize'])
    revised = patch_office('pptx', source, [{'kind': 'editSlides', 'order': [1, 0],
        'images': [original_image], 'pictureReplacements': [replacement],
        'chartEdits': [{'slideIndex': 0, 'elementId': chart['id'], 'kind': 'line',
            'categories': ['一', '二'], 'series': [{'name': '营收', 'values': [15, 25]}]}],
        'edits': [{'slideIndex': 0, 'elementId': text['id'], 'text': '营收 营收'}]}])
    (tmp_path / 'source.pptx').write_bytes(source)
    (tmp_path / 'edited.pptx').write_bytes(revised)
    actual = Presentation(BytesIO(revised))
    assert actual.slides[0].shapes[0].text == '保留来源页'
    assert actual.slides[1].shapes[0].text == '营收 营收'
    charts = [shape.chart for shape in actual.slides[1].shapes if shape.has_chart]
    assert charts[0].chart_type.name == 'LINE_MARKERS'
    assert [item.label for item in charts[0].plots[0].categories] == ['一', '二']
    assert list(charts[0].series[0].values) == [15, 25]
    pictures = [shape.image.blob for shape in actual.slides[1].shapes if shape.shape_type == 13]
    assert replacement_data.getvalue() in pictures
    assert len(pictures) == 2
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(revised)) as after:
        assert before.read('ppt/slides/slide2.xml') == after.read('ppt/slides/slide2.xml')
        assert before.read('ppt/slideMasters/slideMaster1.xml') == after.read('ppt/slideMasters/slideMaster1.xml')
