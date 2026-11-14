"""维护界面开放的PPTX文字偏好必须落到可编辑的原生文本。"""
import pytest
from pptx import Presentation

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.pptx import build_editable_pptx


@pytest.mark.parametrize('aspect', ['16:9', '4:3'])
def test_pptx_supported_typography_survives_native_readback(tmp_path, aspect):
    preferences = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'TypographySigner'},
        'pptx': {'aspectRatio': aspect, 'typography': {
            'body': {'font': 'serif', 'size': 18, 'color': '#234567', 'bold': True, 'lineHeight': 1.8},
            'h1': {'font': 'sans', 'size': 28, 'color': '#765432', 'bold': False, 'lineHeight': 1.2},
        }},
    }), 'pptx')
    path = tmp_path / 'typography.pptx'
    result = build_editable_pptx(output_path=path, title='Report title', period='2026', theme='executive',
        slides=({'title': 'Content title', 'bullets': ['Editable body text']},),
        preferences=preferences, generated_date='2026-11-12')
    deck = Presentation(path)
    for value, font, size, color, bold, spacing in [
        ('Report title', 'Noto Sans CJK SC', 28, '765432', False, 1.2),
        ('Content title', 'Noto Sans CJK SC', 28, '765432', False, 1.2),
        ('Editable body text', 'Noto Serif CJK SC', 18, '234567', True, 1.8),
    ]:
        shape = next(shape for slide in deck.slides for shape in slide.shapes
            if shape.has_text_frame and shape.text == value)
        paragraph = shape.text_frame.paragraphs[0]
        run = paragraph.runs[0]
        assert run.font.name == font
        assert run.font.size.pt == size
        assert str(run.font.color.rgb) == color
        assert bool(run.font.bold) == bold
        assert paragraph.line_spacing == pytest.approx(spacing)
    assert not result.issues


def test_large_multiline_title_stays_above_body_and_returns_adjustment_warning(tmp_path):
    title = '长标题验证内容' * 15
    preferences = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': 'TypographySigner'},
        'pptx': {'typography': {'h1': {'size': 72, 'lineHeight': 3}}},
    }), 'pptx')
    path = tmp_path / 'large-title.pptx'
    result = build_editable_pptx(output_path=path, title=title, period='2026', theme='executive',
        slides=({'title': title, 'bullets': ['Body remains readable']},),
        preferences=preferences, generated_date='2026-11-12')
    deck = Presentation(path)
    for index, slide in enumerate(deck.slides):
        shape = next(shape for shape in slide.shapes if shape.has_text_frame and shape.text == (title if index < 2 else '报告落款'))
        assert shape.top + shape.height <= (370 if index == 0 else 148) * 9525
        assert shape.text_frame.paragraphs[0].runs[0].font.size.pt < 72
    assert any(issue.get('code') == 'pptx_title_font_adjusted' for issue in result.issues)
    from io import BytesIO

    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf

    pdf = PdfReader(BytesIO(libreoffice_to_pdf(path.read_bytes(), suffix='.pptx', timeout=60)))
    for page in pdf.pages[:2]:
        assert title in ''.join(page.extract_text().split())
    assert 'Body remains readable' in pdf.pages[1].extract_text()
