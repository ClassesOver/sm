"""冻结偏好下长正文必须分页，不截断内容或丢失证据。"""
import pytest
from pptx import Presentation

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.pptx import build_editable_pptx


@pytest.mark.parametrize('layout,aspect', [('auto', '16:9'), ('image_left', '4:3'), ('text', '16:9')])
def test_long_pptx_body_paginates_preserves_order_notes_and_actual_total(tmp_path, layout, aspect):
    from PIL import Image

    chart = tmp_path / 'chart.png'
    Image.new('RGB', (640, 320), 'white').save(chart)
    bullets = [f'ITEM{index:03} 正文完整保留' for index in range(25)]
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': 'PaginationSigner'},
        'pptx': {'layout': layout, 'aspectRatio': aspect,
            'footer': {'right': '{slide}/{slides}'}}}), 'pptx')
    path = tmp_path / 'long.pptx'
    built = build_editable_pptx(output_path=path, title='Pagination', period='2026', theme='executive',
        slides=({'title': 'Content', 'bullets': bullets, 'chartPath': str(chart), 'evidenceIds': ['analysis_long']},),
        preferences=prefs, generated_date='2026-11-12')
    deck = Presentation(path)
    assert len(deck.slides) > 3
    actual = [shape.text for slide in list(deck.slides)[1:-1] for shape in slide.shapes
        if shape.has_text_frame and shape.text.startswith('ITEM')]
    assert actual == bullets
    for index, slide in enumerate(deck.slides):
        if 0 < index < len(deck.slides) - 1:
            assert 'analysis_long' in slide.notes_slide.notes_text_frame.text
        if index:
            assert any(shape.has_text_frame and shape.text == f'{index + 1}/{len(deck.slides)}' for shape in slide.shapes)
        for shape in slide.shapes:
            assert shape.top + shape.height <= deck.slide_height + 100
    assert built.slide_count == len(deck.slides)
    assert built.issues == ()


@pytest.mark.parametrize('aspect', ['16:9', '4:3'])
def test_long_signature_keeps_identity_together_and_description_complete(tmp_path, aspect):
    signer = '长署名验证' * 40
    description = '\n'.join(f'说明{i:02}完整保留' for i in range(30))
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': signer, 'dateFormat': 'iso'},
        'pptx': {'aspectRatio': aspect, 'signature': {'size': 36, 'description': description},
            'footer': {'right': '{slide}/{slides}'}}}), 'pptx')
    path = tmp_path / 'signature.pptx'
    built = build_editable_pptx(output_path=path, title='Signature', period='2026', theme='executive',
        slides=({'title': 'Body', 'bullets': ['Preserved body']},), preferences=prefs, generated_date='2026-11-12')
    deck = Presentation(path)
    assert len(deck.slides) > 3
    identity = [slide for slide in deck.slides if any(shape.has_text_frame and signer in shape.text for shape in slide.shapes)]
    assert len(identity) == 1
    assert any(shape.has_text_frame and '2026-11-12' in shape.text for shape in identity[0].shapes)
    text = '\n'.join(shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
    for index in range(30):
        assert text.count(f'说明{index:02}完整保留') == 1
    for slide in deck.slides:
        for shape in slide.shapes:
            assert shape.top + shape.height <= deck.slide_height + 100
    assert any(issue.get('code') == 'pptx_signature_identity_font_adjusted' for issue in built.issues)
    assert not any('overflow' in str(issue).lower() for issue in built.issues)


def test_single_body_over_engine_text_limit_is_preserved_in_continuations(tmp_path):
    value = '长正文原值123。' * 600
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': 'PaginationSigner'}}), 'pptx')
    path = tmp_path / 'single.pptx'
    build_editable_pptx(output_path=path, title='Pagination', period='2026', theme='executive',
        slides=({'title': 'Content', 'bullets': [value]},), preferences=prefs, generated_date='2026-11-12')
    deck = Presentation(path)
    chunks = [shape.text for slide in list(deck.slides)[1:-1] for shape in slide.shapes
        if shape.has_text_frame and (shape.text.startswith('长正文') or '123。' in shape.text)]
    assert ''.join(chunks) == value
    assert len(deck.slides) > 3


def test_actual_pdf_preserves_long_signature_description_and_warning(tmp_path):
    from io import BytesIO

    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf

    signer = 'Signer ' * 28
    descriptions = [f'DESC{index:02} preserved' for index in range(30)]
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': signer.strip(), 'dateFormat': 'iso'},
        'pptx': {'aspectRatio': '4:3', 'signature': {'size': 36, 'description': '\n'.join(descriptions)},
            'footer': {'right': '{slide}/{slides}'}}}), 'pptx')
    path = tmp_path / 'signature-rendered.pptx'
    built = build_editable_pptx(output_path=path, title='Signature', period='2026', theme='executive',
        slides=({'title': 'Body', 'bullets': ['Preserved body']},), preferences=prefs, generated_date='2026-11-12')
    pdf = PdfReader(BytesIO(libreoffice_to_pdf(path.read_bytes(), suffix='.pptx', timeout=60)))
    texts = [page.extract_text() for page in pdf.pages]
    text = '\n'.join(texts)
    assert len(pdf.pages) == built.slide_count
    assert text.count('Signer') == 28
    assert any('Signer' in page and '2026-11-12' in page for page in texts)
    for description in descriptions:
        assert text.count(description) == 1
    assert f'{built.slide_count}/{built.slide_count}' in texts[-1]
    assert any(issue.get('code') == 'pptx_signature_identity_font_adjusted' for issue in built.issues)
    assert not any('overflow' in str(issue).lower() for issue in built.issues)


def test_actual_pdf_preserves_continuations_last_item_and_final_signature(tmp_path):
    from io import BytesIO

    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf

    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': 'PaginationSigner'},
        'pptx': {'typography': {'body': {'size': 18}}, 'footer': {'right': '{slide}/{slides}'}}}), 'pptx')
    path = tmp_path / 'rendered.pptx'
    bullets = [f'BODY{index:03} preserved content' for index in range(25)]
    built = build_editable_pptx(output_path=path, title='Pagination', period='2026', theme='executive',
        slides=({'title': 'Content', 'bullets': bullets},), preferences=prefs, generated_date='2026-11-12')
    pdf = PdfReader(BytesIO(libreoffice_to_pdf(path.read_bytes(), suffix='.pptx', timeout=60)))
    assert len(pdf.pages) == built.slide_count
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    for bullet in bullets:
        assert text.count(bullet) == 1
    assert 'PaginationSigner' in pdf.pages[-1].extract_text()
    assert f'{built.slide_count}/{built.slide_count}' in pdf.pages[-1].extract_text()
    assert built.issues == ()
