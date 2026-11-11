"""内部对象剪贴板与对象链接的真实桥接、媒体保真和拒绝契约。"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from smart_reporting.report_editor.native_office import (
    _pptx_arguments,
    inspect_office,
    patch_office,
)

URL = 'https://example.com/path?a=$&b=2&encoded=%26'


def _source():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    for index, name in enumerate(('A', 'B', 'After')):
        shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, Inches(1 + index * 2.5), Inches(1), Inches(2), Inches(1))
        shape.name = name
        shape.text = f'来源 {name}'
        paragraph = shape.text_frame.paragraphs[0]
        paragraph.alignment = PP_ALIGN.CENTER if index == 0 else PP_ALIGN.RIGHT
        font = paragraph.runs[0].font
        font.name = 'Arial' if index == 0 else 'Calibri'
        font.size = Pt(32 if index == 0 else 16)
        font.bold = index == 0
        font.italic = False
        font.underline = False
        font.color.rgb = RGBColor.from_string('123456' if index == 0 else '987654')
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string('55AA77' if index == 0 else 'EEEEEE')
        shape.line.color.rgb = RGBColor.from_string('224466' if index == 0 else '222222')
        shape.line.width = Pt(2 if index == 0 else 1)
    stream = BytesIO()
    Image.new('RGB', (100, 80), 'blue').save(stream, format='PNG')
    picture = slide.shapes.add_picture(BytesIO(stream.getvalue()), Inches(1), Inches(3), Inches(2), Inches(1.6))
    picture.name = 'Image'
    picture.crop_left = .125
    picture.crop_top = .25
    second = deck.slides.add_slide(deck.slide_layouts[6])
    second.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = '另一页内容'
    output = BytesIO()
    deck.save(output)
    content = output.getvalue()
    return content, inspect_office('pptx', content)


def _patch(content, **changes):
    return patch_office('pptx', content, [{'kind': 'editSlides', **changes}])


def _by_name(model, index=0):
    return {item['name']: item for item in model['slides'][index]['elements']}


def _paste(image, slide=1, dx=20):
    return {'sourceSlideIndex': 0, 'elementIds': [image['id']], 'slideIndex': slide, 'dx': dx, 'dy': dx}


def _same_other_parts(before, after, changed):
    with ZipFile(BytesIO(before)) as a, ZipFile(BytesIO(after)) as b:
        files = {item.filename for item in a.infolist() if not item.is_dir()}
        assert files == {item.filename for item in b.infolist() if not item.is_dir()}
        for path in files - set(changed):
            assert a.read(path) == b.read(path), path


def test_native_protocol_forwards_reference_only_clipboard_and_links():
    paste = {'sourceSlideIndex': 0, 'elementIds': ['source'], 'slideIndex': 1, 'dx': 20, 'dy': 20}
    link = {'slideIndex': 0, 'elementId': 'link', 'target': {'kind': 'url', 'url': URL}}
    arguments = _pptx_arguments({'kind': 'editSlides', 'clipboardPastes': [paste], 'linkEdits': [link]})
    assert arguments['clipboard_pastes'] == [paste]
    assert arguments['link_edits'] == [link]
    for changes in ({'clipboardPastes': [{**paste, 'xml': '<p:sp/>'}]},
                    {'clipboardPastes': [{**paste, 'elementIds': ['source', 'source']}]},
                    {'linkEdits': [link, link]}):
        with pytest.raises(ValueError):
            _pptx_arguments({'kind': 'editSlides', **changes})


def test_real_inspect_reports_clipboard_brush_and_link_capabilities():
    _, model = _source()
    elements = _by_name(model)
    assert elements['Image']['clipboardEditable'] is True
    assert elements['A']['clipboardEditable'] is True
    assert elements['A']['brushSource']['supported'] is True
    assert elements['A']['brushSource']['text']['fontSizePt'] == 32
    assert elements['A']['brushSource']['align'] == 'center'
    assert elements['After']['linkEditable'] is True
    assert elements['After']['elementLink'] is None


def test_combined_multiple_links_pastes_and_source_edit_preserve_copy_at_time():
    content, model = _source()
    elements = _by_name(model)
    edited = _patch(content,
                    clipboardPastes=[_paste(elements['Image'], 0), _paste(elements['Image'], 1, 40),
                                     {'sourceSlideIndex': 0, 'elementIds': [elements['A']['id']], 'slideIndex': 1, 'dx': 20, 'dy': 20}],
                    linkEdits=[{'slideIndex': 0, 'elementId': elements[name]['id'], 'target': {'kind': 'url', 'url': URL + name}} for name in ('After', 'B')],
                    edits=[{'slideIndex': 0, 'elementId': elements['A']['id'], 'text': '后来修改'}])
    read = Presentation(BytesIO(edited))
    assert len(read.slides[0].shapes) == 5
    assert len(read.slides[1].shapes) == 3
    assert read.slides[0].shapes[0].text == '后来修改'
    assert read.slides[1].shapes[-1].text == '来源 A'
    source_image = read.slides[0].shapes[3]
    for picture, offset in ((read.slides[0].shapes[-1], 20), (read.slides[1].shapes[-2], 40)):
        assert picture.image.blob == source_image.image.blob
        assert (picture.crop_left, picture.crop_top) == (.125, .25)
        assert (picture.left, picture.top) == (source_image.left + offset * 9525, source_image.top + offset * 9525)
    refreshed = _by_name(inspect_office('pptx', edited))
    for name in ('After', 'B'):
        assert refreshed[name]['elementLink']['url'] == URL + name
    _same_other_parts(content, edited, {'ppt/slides/slide1.xml', 'ppt/slides/slide2.xml',
                                     'ppt/slides/_rels/slide1.xml.rels', 'ppt/slides/_rels/slide2.xml.rels'})


def test_cut_deletes_unique_source_before_paste_and_restores_media_identity():
    content, model = _source()
    image = _by_name(model)['Image']
    edited = _patch(content, deletions=[{'slideIndex': 0, 'elementId': image['id']}], clipboardPastes=[_paste(image)])
    read = Presentation(BytesIO(edited))
    assert all(shape.name != 'Image' for shape in read.slides[0].shapes)
    picture = read.slides[1].shapes[-1]
    source = Presentation(BytesIO(content)).slides[0].shapes[-1]
    assert picture.image.blob == source.image.blob
    assert (picture.crop_left, picture.crop_top) == (.125, .25)
    refreshed = inspect_office('pptx', edited)['slides'][1]['elements'][-1]
    assert refreshed['pictureSha256'] == image['pictureSha256']
    _same_other_parts(content, edited, {'ppt/slides/slide1.xml', 'ppt/slides/slide2.xml',
                                     'ppt/slides/_rels/slide1.xml.rels', 'ppt/slides/_rels/slide2.xml.rels'})


def test_url_to_slide_survives_order_and_link_can_be_removed_after_reinspect():
    content, model = _source()
    after = _by_name(model)['After']
    linked = _patch(content, linkEdits=[{'slideIndex': 0, 'elementId': after['id'], 'target': {'kind': 'url', 'url': URL}}])
    updated = _by_name(inspect_office('pptx', linked))['After']
    assert updated['elementLink']['url'] == URL
    moved = _patch(linked, linkEdits=[{'slideIndex': 0, 'elementId': updated['id'], 'target': {'kind': 'slide', 'slideIndex': 1}}], order=[1, 0])
    moved_after = _by_name(inspect_office('pptx', moved), 1)['After']
    assert moved_after['elementLink']['kind'] == 'slide'
    assert moved_after['elementLink']['slideIndex'] == 0
    cleared = _patch(moved, linkEdits=[{'slideIndex': 1, 'elementId': moved_after['id'], 'target': None}])
    assert _by_name(inspect_office('pptx', cleared), 1)['After']['elementLink'] is None


def test_dangerous_external_payloads_and_involved_page_conflicts_are_atomic_rejections():
    content, model = _source()
    elements = _by_name(model)
    valid = _paste(elements['Image'])
    link = {'slideIndex': 0, 'elementId': elements['After']['id'], 'target': {'kind': 'url', 'url': URL}}
    for url in ('javascript:alert(1)', 'file:///tmp/private', 'data:text/plain,hello', 'https://example.com/\\evil'):
        with pytest.raises(ValueError):
            _patch(content, clipboardPastes=[valid], linkEdits=[link, {'slideIndex': 0, 'elementId': elements['B']['id'], 'target': {'kind': 'url', 'url': url}}])
    for changes in ({'groupEdits': [{'slideIndex': 0, 'kind': 'group', 'elementIds': [elements['A']['id'], elements['B']['id']]}]},
                    {'newSlides': [{'duplicateOf': 0}], 'order': [0, 1, 2]}, {'theme': 'modern'},
                    {'resetLayouts': [1]}, {'deletedSlides': [0], 'order': [1]},
                    {'clipboardPastes': [{**valid, 'elementIds': [elements['Image']['id'], 'unknown']}]},
                    {'clipboardPastes': [{**valid, 'rels': []}]}):
        with pytest.raises(ValueError):
            _patch(content, **{'clipboardPastes': [valid], 'linkEdits': [link], **changes})
