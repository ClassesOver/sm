"""冻结图注偏好必须落入原生可编辑文字，并为图片保留独立空间。"""
import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.pptx import build_editable_pptx


@pytest.mark.parametrize(('layout', 'aspect', 'numbering'), [
    ('auto', '16:9', True), ('image_left', '4:3', False), ('text', '16:9', True),
])
def test_chart_caption_preferences_reach_editable_native_text_without_covering_image(
    tmp_path, layout, aspect, numbering,
):
    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'CaptionSigner'}, 'pptx': {
            'layout': layout, 'aspectRatio': aspect, 'charts': {'captionNumbering': numbering},
            'typography': {'caption': {'font': 'serif', 'size': 13, 'color': '#123456',
                'bold': True, 'lineHeight': 1.4}},
        }}), 'pptx')
    path = tmp_path / 'captions.pptx'
    result = build_editable_pptx(output_path=path, title='Chart report', period='2026', theme='executive',
        slides=({'title': 'Revenue trend', 'bullets': ['BODY preserved'], 'chartPath': str(chart)},
            {'title': 'Text only', 'bullets': ['No chart here']},
            {'title': 'Cost trend', 'bullets': ['COST preserved'], 'chartPath': str(chart)}),
        preferences=prefs, generated_date='2026-11-12')
    deck = Presentation(path)
    for slide_index, title, number in [(1, 'Revenue trend', 1), (3, 'Cost trend', 2)]:
        slide = deck.slides[slide_index]
        label = f'图 {number} {title}' if numbering else title
        caption = next((shape for shape in slide.shapes if shape.has_text_frame and shape.text == label
            and shape.text_frame.paragraphs[0].runs[0].font.size.pt == 13), None)
        assert caption is not None, f'缺少原生图注: {label}'
        paragraph = caption.text_frame.paragraphs[0]
        font = paragraph.runs[0].font
        assert font.name == 'Noto Serif CJK SC' and font.bold
        assert str(font.color.rgb) == '123456'
        assert paragraph.line_spacing == pytest.approx(1.4)
        picture = next(shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
        assert picture.top + picture.height <= caption.top
        assert caption.top + caption.height < deck.slide_height * 660 / 720
        assert picture.image.blob == chart.read_bytes()
        assert picture.width / picture.height == pytest.approx(2, rel=1e-5)
    assert not any(shape.has_text_frame and shape.text.startswith('图 ') for shape in deck.slides[2].shapes)
    assert result.issues == ()


def test_chart_continuations_keep_original_number_and_caption_title(tmp_path):
    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'CaptionSigner'}, 'pptx': {'layout': 'text'}}), 'pptx')
    path = tmp_path / 'continuations.pptx'
    bullets = [f'BODY{index:03} preserved' for index in range(16)]
    result = build_editable_pptx(output_path=path, title='Chart report', period='2026', theme='executive',
        slides=({'title': 'Revenue trend', 'bullets': bullets, 'chartPath': str(chart)},
            {'title': 'Cost trend', 'bullets': ['COST preserved'], 'chartPath': str(chart)}),
        preferences=prefs, generated_date='2026-11-12')
    deck = Presentation(path)
    content = list(deck.slides)[1:-1]
    assert len(content) > 2
    assert [shape.text for slide in content for shape in slide.shapes
        if shape.has_text_frame and shape.text.startswith('BODY')] == bullets
    for slide in content[:-1]:
        assert any(shape.has_text_frame and shape.text == '图 1 Revenue trend' for shape in slide.shapes)
    assert any(shape.has_text_frame and shape.text == '图 2 Cost trend' for shape in content[-1].shapes)
    assert result.issues == ()


def test_extreme_caption_keeps_full_text_body_and_image_in_actual_pdf(tmp_path):
    from io import BytesIO

    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf

    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    title = 'Long caption Revenue trend ' * 24
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'CaptionSigner'}, 'pptx': {'layout': 'text',
            'typography': {'caption': {'size': 72, 'lineHeight': 3}}}}), 'pptx')
    path = tmp_path / 'extreme.pptx'
    result = build_editable_pptx(output_path=path, title='Chart report', period='2026', theme='executive',
        slides=({'title': title, 'bullets': ['BODY sentinel preserved'], 'chartPath': str(chart)},),
        preferences=prefs, generated_date='2026-11-12')
    deck = Presentation(path)
    slide = deck.slides[1]
    caption = next(shape for shape in slide.shapes if shape.has_text_frame and shape.text == '图 1 ' + title)
    assert caption.text_frame.paragraphs[0].runs[0].font.size.pt < 72
    picture = next(shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
    body = next(shape for shape in slide.shapes if shape.has_text_frame and shape.text == 'BODY sentinel preserved')
    assert body.top + body.height < picture.top
    assert picture.height > 0 and picture.top + picture.height <= caption.top
    assert caption.top + caption.height <= deck.slide_height * 640 / 720 + 1
    assert any(issue.get('code') == 'pptx_caption_font_adjusted' for issue in result.issues)
    assert not any('overflow' in str(issue).lower() for issue in result.issues), result.issues
    pdf = libreoffice_to_pdf(path.read_bytes(), suffix='.pptx', timeout=60)
    (tmp_path / 'extreme.pdf').write_bytes(pdf)
    page_text = PdfReader(BytesIO(pdf)).pages[1].extract_text()
    assert 'BODY sentinel preserved' in page_text
    # 标题与图注各保留一份源标题，忽略PDF换行。
    assert ' '.join(page_text.split()).count('Long caption') == 48


def test_legacy_slides_without_frozen_preferences_keep_existing_chart_output(tmp_path):
    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    path = tmp_path / 'legacy.pptx'
    result = build_editable_pptx(output_path=path, title='Legacy', period='2026', theme='executive',
        slides=({'title': 'Revenue trend', 'bullets': ['BODY preserved'], 'chartPath': str(chart)},))
    deck = Presentation(path)
    assert len(deck.slides) == 2
    assert [shape.text for shape in deck.slides[1].shapes if shape.has_text_frame].count('Revenue trend') == 1
    assert not any(shape.has_text_frame and shape.text.startswith('图 ') for shape in deck.slides[1].shapes)
    picture = next(shape for shape in deck.slides[1].shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
    assert picture.image.blob == chart.read_bytes()
    assert result.issues == ()


@pytest.mark.parametrize('aspect', ['16:9', '4:3'])
def test_extremely_long_multiline_caption_cannot_consume_the_image_box(tmp_path, aspect):
    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    title = '超长图注😀  原始标题' * 25 + '\n ' + '图注原文😀  原始标题' * 25
    prefs = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'CaptionSigner'}, 'pptx': {'layout': 'text', 'aspectRatio': aspect, 'footer': {'right': '{slide}/{slides}'},
            'typography': {'caption': {'size': 72, 'lineHeight': 3, 'font': 'serif', 'bold': True}}}}), 'pptx')
    path = tmp_path / 'very-long.pptx'
    result = build_editable_pptx(output_path=path, title='Chart report', period='2026', theme='executive',
        slides=({'title': title, 'bullets': ['BODY sentinel preserved'], 'chartPath': str(chart)},),
        preferences=prefs, generated_date='2026-11-12')
    deck = Presentation(path)
    captions = []
    for page_index, slide in enumerate(list(deck.slides)[1:-1], start=2):
        caption = next(shape for shape in slide.shapes if shape.has_text_frame and shape.text.startswith('图 1 ')
            and shape.top >= 174 * 9525)
        assert caption.text_frame.paragraphs[0].runs[0].font.size.pt >= 6
        picture = next(shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
        assert picture.height > 0
        assert picture.top + picture.height <= caption.top
        assert caption.top + caption.height <= deck.slide_height * 640 / 720 + 1
        # python-pptx用VT表示OOXML的a:br；仅还原这一种原生换行，不折叠空白。
        captions.append(caption.text.removeprefix('图 1 ').replace('\v', '\n'))
        assert picture.image.blob == chart.read_bytes()
        assert any(shape.has_text_frame and shape.text == f'{page_index}/{len(deck.slides)}'
            for shape in slide.shapes)
    assert len(captions) > 1
    assert ''.join(captions) == title
    assert sum(shape.has_text_frame and shape.text == 'BODY sentinel preserved'
        for slide in deck.slides for shape in slide.shapes) == 1
    assert any(issue.get('code') == 'pptx_caption_continued' for issue in result.issues)
    assert not any('overflow' in str(issue).lower() for issue in result.issues), result.issues
    from io import BytesIO

    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf

    pdf = PdfReader(BytesIO(libreoffice_to_pdf(path.read_bytes(), suffix='.pptx', timeout=60)))
    assert len(pdf.pages) == len(deck.slides)
    for page, fragment in zip(list(pdf.pages)[1:-1], captions, strict=True):
        # 彩色emoji在PDF中单独绘制，抽取顺序独立；正文只折叠渲染换行，emoji另核总数。
        expected = ''.join(fragment.replace('😀', '').split())
        actual = ''.join(page.extract_text().replace('😀', '').split())
        assert expected in actual
    assert sum(page.extract_text().count('😀') for page in pdf.pages) == title.count('😀')
    assert any(issue.get('code') == 'pptx_chart_title_shortened' for issue in result.issues)
