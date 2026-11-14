"""通用字体主题色必须出现在真实产物，格式覆盖不修改公共默认。"""
import base64
from io import BytesIO

import pytest
from docx import Document
from pptx import Presentation

from smart_reporting.management.configuration_preview import render_preference_preview
from smart_reporting.preferences.models import FormatPreferences


@pytest.mark.parametrize('format', ['word', 'pdf', 'pptx'])
def test_common_style_is_consumed_by_actual_preview_with_format_override(format):
    prefs = FormatPreferences.model_validate({'common': {
        'signer': '字体颜色验证', 'font': 'serif', 'accentColor': '#456789'},
        format: {'common': {'accentColor': '#765432'}}})
    document = prefs.model_dump(mode='json', by_alias=True)
    result = render_preference_preview(document, format, generated_date='2026-11-12')
    assert not result['issues']
    native = base64.b64decode(result['artifact']['base64'])
    assert document['common']['accentColor'] == '#456789'
    if format == 'word':
        doc = Document(BytesIO(native))
        assert doc.styles['Normal'].font.name == 'Noto Serif CJK SC'
        assert str(doc.styles['Heading 1'].font.color.rgb) == '765432'
    elif format == 'pptx':
        deck = Presentation(BytesIO(native))
        runs = [run for slide in deck.slides for shape in slide.shapes if shape.has_text_frame
            for paragraph in shape.text_frame.paragraphs for run in paragraph.runs]
        assert any(run.font.name == 'Noto Serif CJK SC' for run in runs)
        assert any(run.font.color.type is not None and str(run.font.color.rgb) == '765432'
            for run in runs if run.font.color.type == 1)
    else:
        import pymupdf

        pdf = pymupdf.open(stream=native, filetype='pdf')
        spans = [span for page in pdf for block in page.get_text('dict')['blocks']
            for line in block.get('lines', []) for span in line['spans']]
        assert any('Serif' in span['font'] and span['color'] == 0x765432 for span in spans)
        assert '1234.56' in ''.join(page.get_text() for page in pdf)
