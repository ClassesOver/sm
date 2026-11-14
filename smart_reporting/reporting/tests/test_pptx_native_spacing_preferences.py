"""段落偏好同时约束原生XML与真实分页，不靠字号外观推断消费成功。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pypdf import PdfReader

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf
from smart_reporting.reporting.delivery.pptx import build_editable_pptx


@pytest.mark.parametrize('aspect', ['16:9', '4:3'])
def test_native_paragraph_spacing_and_footer_line_height_keep_frozen_values(tmp_path, aspect):
    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    preferences = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'SpacingSigner'}, 'pptx': {
            'aspectRatio': aspect, 'footer': {'right': 'PAGE {slide}/{slides}'},
            'typography': {
                'body': {'size': 18, 'spaceBefore': 9, 'spaceAfter': 24},
                'h1': {'size': 24, 'spaceBefore': 12, 'spaceAfter': 18},
                'caption': {'size': 12, 'spaceBefore': 15, 'spaceAfter': 12},
            },
            'footerStyle': {'size': 10, 'lineHeight': 2.2, 'spaceBefore': 6, 'spaceAfter': 9},
        }}), 'pptx')
    frozen = deepcopy(preferences)
    path = tmp_path / 'native-spacing.pptx'
    result = build_editable_pptx(output_path=path, title='Spacing report', period='2026', theme='executive',
        slides=({'title': 'Native spacing title', 'bullets': ['BODY preserved'], 'chartPath': str(chart)},),
        preferences=preferences, generated_date='2026-11-12')
    deck = Presentation(path)
    content = deck.slides[1]
    for value, before, after, line in [
        ('Native spacing title', 12, 18, 1.6), ('BODY preserved', 9, 24, 1.6),
        ('图 1 Native spacing title', 15, 12, 1.6), (f'PAGE 2/{len(deck.slides)}', 6, 9, 2.2),
    ]:
        shape = next(shape for shape in content.shapes if shape.has_text_frame and shape.text == value)
        paragraph = shape.text_frame.paragraphs[0]
        assert paragraph.space_before is not None, f'{value}: 段前未进入原生XML'
        assert paragraph.space_before.pt == before
        assert paragraph.space_after.pt == after
        assert paragraph.line_spacing == pytest.approx(line)
    picture = next(shape for shape in content.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
    caption = next(shape for shape in content.shapes if shape.has_text_frame and shape.text.startswith('图 1 '))
    footer = next(shape for shape in content.shapes if shape.has_text_frame and shape.text.startswith('PAGE '))
    assert picture.top + picture.height <= caption.top
    assert caption.top + caption.height < footer.top
    assert preferences == frozen
    assert not any('overflow' in str(issue).lower() for issue in result.issues), result.issues


@pytest.mark.parametrize('layout', ['text', 'image_left'])
def test_large_native_spacing_paginates_body_caption_and_signature_above_footer(tmp_path, layout):
    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    title = 'Caption source preserved ' * 28
    bullets = [f'BODY{index:03} preserved' for index in range(8 if layout == 'text' else 1)]
    preferences = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'SpacingSigner'}, 'pptx': {
            'layout': layout, 'aspectRatio': '4:3', 'footer': {'right': 'PAGE {slide}/{slides}'},
            'typography': {
                'body': {'size': 18, 'bold': True, 'spaceBefore': 72, 'spaceAfter': 72},
                'h1': {'size': 24, 'spaceBefore': 72, 'spaceAfter': 72},
                'caption': {'size': 24, 'spaceBefore': 72, 'spaceAfter': 72},
            },
            'footerStyle': {'size': 24, 'lineHeight': 3, 'spaceBefore': 72, 'spaceAfter': 72},
            'signature': {'description': '\n'.join(f'DESC{index:02} preserved' for index in range(6))},
        }}), 'pptx')
    frozen = deepcopy(preferences)
    path = tmp_path / 'large-spacing.pptx'
    result = build_editable_pptx(output_path=path, title='Spacing report', period='2026', theme='executive',
        slides=({'title': title, 'bullets': bullets, 'chartPath': str(chart)},),
        preferences=preferences, generated_date='2026-11-12')
    deck = Presentation(path)
    assert len(deck.slides) > 4
    actual_body = []
    captions = []
    caption_pages = []
    for page_number, slide in enumerate(deck.slides, start=1):
        footer = next((shape for shape in slide.shapes if shape.has_text_frame and shape.text.startswith('PAGE ')), None)
        if page_number > 1:
            assert footer is not None
            assert footer.text == f'PAGE {page_number}/{len(deck.slides)}'
            assert footer.text_frame.paragraphs[0].space_after.pt == 72
            assert footer.top + footer.height <= deck.slide_height
            if footer.text_frame.paragraphs[0].runs[0].font.size.pt < 24:
                assert any(issue.get('code') == 'pptx_footer_font_adjusted' and issue['page'] == page_number
                    for issue in result.issues)
        for shape in slide.shapes:
            assert shape.top + shape.height <= deck.slide_height + 1
            if shape.has_text_frame and shape.text.startswith('BODY'):
                actual_body.append(shape.text)
            if footer is not None and shape._element is not footer._element and shape.has_text_frame:
                assert shape.top + shape.height < footer.top, shape.text
        text_boxes = sorted((shape for shape in slide.shapes if shape.has_text_frame and shape.text
            and (footer is None or shape._element is not footer._element)), key=lambda shape: shape.top)
        for left, right in zip(text_boxes, text_boxes[1:]):
            if left.left < right.left + right.width and right.left < left.left + left.width:
                assert left.top + left.height <= right.top
        pictures = [shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE]
        if pictures:
            caption = next(shape for shape in slide.shapes if shape.has_text_frame and shape.text.startswith('图 1 ')
                and shape.top >= 174 * 9525)
            picture = pictures[0]
            assert picture.height > 0 and picture.top + picture.height <= caption.top
            assert picture.height >= 60 * 9525 - 1
            assert caption.top + caption.height < footer.top
            derivation = next(item for item in result.image_derivations if item['slide'] == page_number)
            assert derivation['sourceSha256'] == sha256(chart.read_bytes()).hexdigest()
            assert derivation['embeddedSha256'] == sha256(picture.image.blob).hexdigest()
            assert derivation['withinLimit'] is True
            captions.append(caption.text.removeprefix('图 1 ').replace('\v', '\n'))
            caption_pages.append(page_number - 1)
    cover_text = sorted((shape for shape in deck.slides[0].shapes if shape.has_text_frame and shape.text),
        key=lambda shape: shape.top)
    assert all(left.top + left.height < right.top for left, right in zip(cover_text, cover_text[1:]))
    assert actual_body == bullets
    assert ''.join(captions) == title
    assert preferences == frozen
    assert not any('overflow' in str(issue).lower() for issue in result.issues), result.issues
    pdf_bytes = libreoffice_to_pdf(path.read_bytes(), suffix='.pptx', timeout=60)
    (tmp_path / 'large-spacing.pdf').write_bytes(pdf_bytes)
    pdf = PdfReader(BytesIO(pdf_bytes))
    assert len(pdf.pages) == result.slide_count
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    for bullet in bullets:
        assert text.count(bullet) == 1
    for index in range(6):
        assert text.count(f'DESC{index:02} preserved') == 1
    for index, fragment in zip(caption_pages, captions, strict=True):
        assert ''.join(fragment.split()) in ''.join(pdf.pages[index].extract_text().split())
    assert f'PAGE {len(deck.slides)}/{len(deck.slides)}' in pdf.pages[-1].extract_text()


def test_footer_budget_cannot_loop_on_large_signature_or_hide_impossible_spacing(tmp_path, monkeypatch):
    from functools import partial

    from smart_reporting.reporting.delivery import pptx as delivery
    from smart_reporting.reporting.delivery.office_engine import run_bridge

    # 仍运行真实桥接；缩短超时让单字无法放下时的空续页循环成为可定位的失败。
    monkeypatch.setattr(delivery, 'run_bridge', partial(run_bridge, timeout=10))
    preferences = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'SpacingSigner'}, 'pptx': {
            'footer': {'right': 'PAGE {slide}/{slides}'},
            'footerStyle': {'size': 24, 'lineHeight': 3, 'spaceAfter': 72},
            'signature': {'size': 72, 'lineHeight': 3, 'dateGap': 72, 'spaceAfter': 72,
                'description': 'DESC impossible size preserved'},
        }}), 'pptx')
    frozen = deepcopy(preferences)
    path = tmp_path / 'signature-budget.pptx'
    result = build_editable_pptx(output_path=path, title='Signature budget', period='2026', theme='executive',
        slides=({'title': 'Body', 'bullets': ['BODY preserved']},),
        preferences=preferences, generated_date='2026-11-12')
    deck = Presentation(path)
    description = next(shape for slide in deck.slides for shape in slide.shapes
        if shape.has_text_frame and shape.text == 'DESC impossible size preserved')
    assert description.text_frame.paragraphs[0].runs[0].font.size.pt < 72
    assert description.text_frame.paragraphs[0].space_after.pt == 72
    codes = {issue.get('code') for issue in result.issues}
    assert 'pptx_signature_description_font_adjusted' in codes
    assert 'pptx_signature_identity_spacing_unfit' in codes
    assert result.size == path.stat().st_size > 0
    assert result.sha256 and preferences == frozen


def test_unfit_repeated_title_footer_keeps_bounded_budget_and_actual_artifact(tmp_path, monkeypatch):
    import json
    from dataclasses import asdict
    from functools import partial
    from hashlib import sha256

    from smart_reporting.reporting.delivery import pptx as delivery
    from smart_reporting.reporting.delivery.office_engine import run_bridge

    monkeypatch.setattr(delivery, 'run_bridge', partial(run_bridge, timeout=10))
    title = 'Long footer source preserved ' * 20
    preferences = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'FooterSigner'}, 'pptx': {
            'footer': {'right': '{title}' * 28},
            'footerStyle': {'size': 6, 'lineHeight': 3, 'spaceAfter': 72},
            'signature': {'description': 'DESC still preserved'},
        }}), 'pptx')
    frozen = deepcopy(preferences)
    path = tmp_path / 'repeated-title-footer.pptx'
    result = build_editable_pptx(output_path=path, title=title, period='2026', theme='executive',
        slides=({'title': 'Body title', 'bullets': ['BODY still preserved']},),
        preferences=preferences, generated_date='2026-11-12')
    deck = Presentation(path)
    assert len(deck.slides) == result.slide_count == 3
    footers = [shape for slide in deck.slides for shape in slide.shapes
        if shape.has_text_frame and shape.text == title * 28]
    assert len(footers) == 2
    for footer in footers:
        assert footer.height <= 200 * 9525
        assert footer.top + footer.height <= deck.slide_height
        assert footer.text_frame.paragraphs[0].runs[0].font.size.pt == 6
        assert footer.text_frame.paragraphs[0].space_after.pt == 72
    unfit = [issue for issue in result.issues if issue.get('code') == 'pptx_footer_content_unfit']
    assert len(unfit) == 2
    assert all('排版未通过' in issue['message'] and '不能保证完整可见' in issue['message'] for issue in unfit)
    text = '\n'.join(shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
    assert 'BODY still preserved' in text and 'DESC still preserved' in text
    assert result.size == path.stat().st_size > 0
    assert result.sha256 == sha256(path.read_bytes()).hexdigest() and preferences == frozen
    (tmp_path / 'receipt.json').write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2))
