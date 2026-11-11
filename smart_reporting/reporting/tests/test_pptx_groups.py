"""来源对象受限组合/取消组合的真实 OOXML 保真与拒绝契约。"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_CONNECTOR
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches

from smart_reporting.report_editor.native_office import (
    _pptx_arguments,
    inspect_office,
    patch_office,
)


def _source(unsafe=None):
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    for name, x in [('Before', .2), ('A', 1), ('B', 3)]:
        shape = slide.shapes.add_textbox(Inches(x), Inches(1), Inches(1.5), Inches(.6))
        shape.name = name
        shape.text = f'来源文字 {name}'
    image = BytesIO()
    Image.new('RGB', (80, 60), 'blue').save(image, format='PNG')
    picture = slide.shapes.add_picture(BytesIO(image.getvalue()), Inches(5), Inches(1), Inches(1), Inches(.75))
    picture.name = 'Image'
    picture.crop_left = .125
    picture.crop_top = .25
    after = slide.shapes.add_textbox(Inches(7), Inches(1), Inches(1), Inches(.6))
    after.name = 'After'
    after.text = '保留前景'
    target = slide.shapes[1]
    if unsafe == 'rotation':
        target.rotation = 15
    elif unsafe == 'flip':
        target._element.spPr.xfrm.set('flipH', '1')
    elif unsafe == 'placeholder':
        target._element.nvSpPr.nvPr.append(OxmlElement('p:ph'))
    elif unsafe == 'picture3d':
        picture._element.spPr.append(OxmlElement('a:scene3d'))
    elif unsafe == 'connector':
        line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(1), Inches(2), Inches(4), Inches(2))
        line.begin_connect(target, 0)
    elif unsafe == 'animation':
        timing = OxmlElement('p:timing')
        timing.append(OxmlElement('p:tnLst'))
        par = OxmlElement('p:par')
        ctn = OxmlElement('p:cTn')
        ctn.set('id', '1')
        child = OxmlElement('p:childTnLst')
        anim = OxmlElement('p:animEffect')
        behavior = OxmlElement('p:cBhvr')
        behavior.append(OxmlElement('p:cTn'))
        target_element = OxmlElement('p:tgtEl')
        ref = OxmlElement('p:spTgt')
        ref.set('spid', str(target.shape_id))
        target_element.append(ref)
        behavior.append(target_element)
        anim.append(behavior)
        child.append(anim)
        ctn.append(child)
        par.append(ctn)
        timing[0].append(par)
        slide._element.append(timing)
    other = deck.slides.add_slide(deck.slide_layouts[6])
    other.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1)).text = '另页内容'
    stream = BytesIO()
    deck.save(stream)
    content = stream.getvalue()
    return content, inspect_office('pptx', content)


def _patch(content, **changes):
    return patch_office('pptx', content, [{'kind': 'editSlides', **changes}])


def _group(model):
    ids = {item['name']: item['id'] for item in model['slides'][0]['elements']}
    return {'slideIndex': 0, 'kind': 'group', 'elementIds': [ids['Image'], ids['B'], ids['A']]}


def _unchanged_parts(before, after, changed=('ppt/slides/slide1.xml',)):
    with ZipFile(BytesIO(before)) as a, ZipFile(BytesIO(after)) as b:
        files = {item.filename for item in a.infolist() if not item.is_dir()}
        assert files == {item.filename for item in b.infolist() if not item.is_dir()}
        for path in files - set(changed):
            assert a.read(path) == b.read(path), path


def test_native_group_arguments_forward_and_reject_ambiguous_records():
    record = {'slideIndex': 0, 'kind': 'group', 'elementIds': ['a', 'b']}
    assert _pptx_arguments({'kind': 'editSlides', 'groupEdits': [record]})['group_edits'] == [record]
    for records in ([record, record], [{**record, 'slideIndex': index} for index in range(51)],
                    [{'slideIndex': 0, 'kind': 'ungroup', 'elementIds': ['a', 'b']}],
                    [{'slideIndex': 0, 'kind': 'group', 'elementIds': ['a', 'a']}],
                    [{'slideIndex': 0, 'kind': 'group', 'elementIds': ['a']}],
                    [{'slideIndex': 0, 'kind': 'other', 'elementId': 'a'}]):
        with pytest.raises(ValueError):
            _pptx_arguments({'kind': 'editSlides', 'groupEdits': records})


def test_group_preserves_contiguous_slot_source_child_order_and_all_other_parts():
    content, model = _source()
    original = Presentation(BytesIO(content))
    edited = _patch(content, groupEdits=[_group(model)])
    shapes = Presentation(BytesIO(edited)).slides[0].shapes
    assert len(shapes) == 3
    assert shapes[0].name == 'Before'
    assert shapes[2].name == 'After'
    group = shapes[1]
    assert [shape.name for shape in group.shapes] == ['A', 'B', 'Image']
    assert {shape.shape_id: shape._element.xml for shape in group.shapes} == {
        shape.shape_id: shape._element.xml for shape in list(original.slides[0].shapes)[1:4]}
    assert shapes[0]._element.xml == original.slides[0].shapes[0]._element.xml
    assert shapes[2]._element.xml == original.slides[0].shapes[4]._element.xml
    _unchanged_parts(content, edited)


def test_saved_group_reinspect_then_ungroup_restores_slot_text_geometry_and_media():
    content, model = _source()
    grouped = _patch(content, groupEdits=[_group(model)])
    group_model = inspect_office('pptx', grouped)
    source_group = next(item for item in group_model['slides'][0]['elements'] if item['type'] == 'group')
    restored = _patch(grouped, groupEdits=[{'slideIndex': 0, 'kind': 'ungroup', 'elementId': source_group['id']}])
    before = Presentation(BytesIO(content)).slides[0]
    after = Presentation(BytesIO(restored)).slides[0]
    assert [(shape.shape_id, shape.name, shape.text if shape.has_text_frame else None,
             shape.left, shape.top, shape.width, shape.height) for shape in after.shapes] == [
        (shape.shape_id, shape.name, shape.text if shape.has_text_frame else None,
         shape.left, shape.top, shape.width, shape.height) for shape in before.shapes]
    image = next(shape for shape in after.shapes if shape.name == 'Image')
    assert (image.crop_left, image.crop_top, image.crop_right, image.crop_bottom) == (.125, .25, 0, 0)
    _unchanged_parts(content, restored)


def test_group_allows_independent_other_page_edit_and_final_slide_order():
    content, model = _source()
    other = model['slides'][1]['elements'][0]
    edited = _patch(content, groupEdits=[_group(model)],
                    edits=[{'slideIndex': 1, 'elementId': other['id'], 'text': '另页修改'}], order=[1, 0])
    read = Presentation(BytesIO(edited))
    assert read.slides[0].shapes[0].text == '另页修改'
    assert [shape.name for shape in read.slides[1].shapes[1].shapes] == ['A', 'B', 'Image']


def test_group_rejects_unknown_duplicate_noncontiguous_or_partial_targets():
    content, model = _source()
    record = _group(model)
    ids = {item['name']: item['id'] for item in model['slides'][0]['elements']}
    for targets in ([ids['A'], ids['B'], 'unknown'], [ids['A'], ids['A']],
                    [ids['A'], ids['After']], [ids['A']], ['unknown', ids['B']]):
        with pytest.raises(ValueError):
            _patch(content, groupEdits=[{**record, 'elementIds': targets}])
    with pytest.raises(ValueError):
        _patch(content, groupEdits=[record, record])


@pytest.mark.parametrize('unsafe', ['rotation', 'flip', 'placeholder', 'picture3d', 'connector', 'animation'])
def test_group_rejects_unsupported_source_without_partial_success(unsafe):
    content, model = _source(unsafe)
    with pytest.raises(ValueError):
        _patch(content, groupEdits=[_group(model)])


def test_group_rejects_same_page_changes_or_duplicate_source():
    content, model = _source()
    record = _group(model)
    target = model['slides'][0]['elements'][1]
    ids = [item['id'] for item in model['slides'][0]['elements']]
    image = next(item for item in model['slides'][0]['elements'] if item['type'] == 'picture')
    conflicts = [
        {'edits': [{'slideIndex': 0, 'elementId': target['id'], 'text': '冲突'}]},
        {'elementOrders': [{'slideIndex': 0, 'elementIds': list(reversed(ids))}]},
        {'deletions': [{'slideIndex': 0, 'elementId': ids[-1]}]},
        {'resetLayouts': [0]},
        {'pictureCrops': [{'slideIndex': 0, 'elementId': image['id'], 'expectedSha256': image['pictureSha256'],
                           'srcRect': {'l': .1, 't': 0, 'r': 0, 'b': 0}, 'geometry': image['geometry']}]},
        {'deletedSlides': [0], 'order': [1]},
        {'newSlides': [{'duplicateOf': 0}], 'order': [0, 1, 2]},
        {'slideSize': {'cx': 960 * 9525, 'cy': 540 * 9525}},
        {'slideLayouts': [{'slideIndex': 0, 'layoutPath': 'ppt/slideLayouts/slideLayout7.xml'}]},
    ]
    for changes in conflicts:
        with pytest.raises(ValueError):
            _patch(content, groupEdits=[record], **changes)


@pytest.mark.parametrize('unsafe', ['rotation', 'flip', 'scaled', 'nested', 'picture3d', 'placeholder'])
def test_ungroup_rejects_complex_group_transforms_or_children(unsafe):
    content, _ = _source()
    deck = Presentation(BytesIO(content))
    slide = deck.slides[0]
    group = slide.shapes.add_group_shape(list(slide.shapes)[1:4])
    if unsafe == 'rotation':
        group.rotation = 15
    elif unsafe == 'flip':
        group._element.grpSpPr.xfrm.set('flipV', '1')
    elif unsafe == 'scaled':
        group._element.grpSpPr.xfrm.ext.cx += 9525
    elif unsafe == 'nested':
        group.shapes.add_group_shape(list(group.shapes)[:2])
    elif unsafe == 'picture3d':
        group.shapes[2]._element.spPr.append(OxmlElement('a:scene3d'))
    elif unsafe == 'placeholder':
        group.shapes[0]._element.nvSpPr.nvPr.append(OxmlElement('p:ph'))
    stream = BytesIO()
    deck.save(stream)
    content = stream.getvalue()
    model = inspect_office('pptx', content)
    source = next(item for item in model['slides'][0]['elements'] if item['type'] == 'group')
    with pytest.raises(ValueError):
        _patch(content, groupEdits=[{'slideIndex': 0, 'kind': 'ungroup', 'elementId': source['id']}])
