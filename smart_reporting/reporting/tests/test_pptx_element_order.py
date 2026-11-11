"""完整来源对象层级排列的原生 API 与真实 OOXML 保真契约。"""
from __future__ import annotations

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


def _source():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    inherited_left = slide.shapes.title.left
    slide.shapes.title.text = '保留标题'
    slide.shapes.title.left += Inches(1)
    for name, text, x in [('A', '甲', 1), ('B', '乙', 3), ('C', '丙', 5)]:
        shape = slide.shapes.add_textbox(Inches(x), Inches(2), Inches(1.5), Inches(1))
        shape.name = name
        shape.text = text
    image = BytesIO()
    Image.new('RGB', (80, 60), 'red').save(image, format='PNG')
    picture = slide.shapes.add_picture(BytesIO(image.getvalue()), Inches(1), Inches(4), Inches(2), Inches(1))
    picture.name = '裁切图片'
    picture.crop_left = .125
    picture.crop_top = .25
    other = presentation.slides.add_slide(presentation.slide_layouts[6])
    other.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1)).text = '未改页面'
    stream = BytesIO()
    presentation.save(stream)
    content = stream.getvalue()
    elements = inspect_office('pptx', content)['slides'][0]['elements']
    return content, elements, inherited_left


def _patch(content, **operation):
    return patch_office('pptx', content, [{'kind': 'editSlides', **operation}])


def test_native_arguments_forward_complete_source_element_orders():
    records = [{'slideIndex': 0, 'elementIds': ['text_1', 'picture_2']}]
    arguments = _pptx_arguments({'kind': 'editSlides', 'elementOrders': records})
    assert arguments['element_orders'] == records
    assert records == [{'slideIndex': 0, 'elementIds': ['text_1', 'picture_2']}]


def test_element_order_preserves_source_ids_shape_bytes_and_every_unrelated_zip_part():
    content, elements, _ = _source()
    expected = list(reversed(elements))
    original = Presentation(BytesIO(content))
    source_shapes = {shape.shape_id: shape._element.xml for shape in original.slides[0].shapes}
    edited = _patch(content, elementOrders=[{'slideIndex': 0, 'elementIds': [item['id'] for item in expected]}])
    read = Presentation(BytesIO(edited))
    assert [shape.name for shape in read.slides[0].shapes] == [item['name'] for item in expected]
    assert {shape.shape_id: shape._element.xml for shape in read.slides[0].shapes} == source_shapes
    picture = next(shape for shape in read.slides[0].shapes if shape.name == '裁切图片')
    assert (picture.crop_left, picture.crop_top) == (.125, .25)
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(edited)) as after:
        before_files = {item.filename for item in before.infolist() if not item.is_dir()}
        after_files = {item.filename for item in after.infolist() if not item.is_dir()}
        assert before_files == after_files
        for path in before_files:
            if path != 'ppt/slides/slide1.xml':
                assert before.read(path) == after.read(path), path


def test_element_order_composes_with_source_edit_delete_layout_reset_and_slide_reorder():
    content, elements, inherited_left = _source()
    by_name = {item['name']: item for item in elements}
    expected = list(reversed(elements))
    edited = _patch(content,
                    elementOrders=[{'slideIndex': 0, 'elementIds': [item['id'] for item in expected]}],
                    edits=[{'slideIndex': 0, 'elementId': by_name['B']['id'], 'text': '修改乙',
                            'geometry': {'x': 250, 'y': 180, 'width': 144, 'height': 96}}],
                    deletions=[{'slideIndex': 0, 'elementId': by_name['C']['id']}],
                    resetLayouts=[0], order=[1, 0])
    read = Presentation(BytesIO(edited))
    target = read.slides[1]
    assert [shape.name for shape in target.shapes] == [item['name'] for item in expected if item['name'] != 'C']
    changed = next(shape for shape in target.shapes if shape.name == 'B')
    assert changed.text == '修改乙'
    assert (changed.left, changed.top, changed.width, changed.height) == tuple(value * 9525 for value in (250, 180, 144, 96))
    assert target.shapes.title.left == inherited_left
    picture = next(shape for shape in target.shapes if shape.name == '裁切图片')
    assert (picture.crop_left, picture.crop_top) == (.125, .25)
    assert read.slides[0].shapes[0].text == '未改页面'


def test_element_order_is_copied_into_a_same_batch_duplicate():
    content, elements, _ = _source()
    expected = list(reversed(elements))
    edited = _patch(content, elementOrders=[{'slideIndex': 0, 'elementIds': [item['id'] for item in expected]}],
                    newSlides=[{'duplicateOf': 0}], order=[0, 2, 1])
    read = Presentation(BytesIO(edited))
    assert len(read.slides) == 3
    for index in (0, 1):
        assert [shape.name for shape in read.slides[index].shapes] == [item['name'] for item in expected]
    assert read.slides[2].shapes[0].text == '未改页面'


def test_element_order_rejects_nonpermutations_duplicate_slide_records_and_deleted_source_pages():
    content, elements, _ = _source()
    ids = [item['id'] for item in elements]
    valid = {'slideIndex': 0, 'elementIds': ids}
    for records in ([{'slideIndex': 0, 'elementIds': ids[:-1]}],
                    [{'slideIndex': 0, 'elementIds': [*ids[:-1], ids[0]]}],
                    [{'slideIndex': 0, 'elementIds': [*ids[:-1], 'unknown']}],
                    [valid, valid], [{'slideIndex': 2, 'elementIds': ids}]):
        with pytest.raises(ValueError):
            _patch(content, elementOrders=records)
    with pytest.raises(ValueError):
        _patch(content, elementOrders=[valid], deletedSlides=[0], order=[1])
