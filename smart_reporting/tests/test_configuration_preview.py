"""配置预览复用真实五格式生成器，不发布、不改写草稿。"""
import base64
import hashlib
from io import BytesIO

import pytest
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from smart_reporting.management.configuration_preview import render_preference_preview
from smart_reporting.preferences.models import FormatPreferences


@pytest.mark.parametrize('format', ['md', 'xlsx', 'pptx', 'pdf', 'word'])
def test_actual_format_preview_preserves_frozen_signature_and_native_document(format):
    prefs = FormatPreferences.model_validate({'common': {'signer': '预览编制人', 'dateFormat': 'iso'},
        'word': {'signature': {'description': '实际原生落款'}},
        'pdf': {'signature': {'description': '实际 PDF 落款'}}})
    document = prefs.model_dump(mode='json', by_alias=True)
    result = render_preference_preview(document, format, generated_date='2026-11-12')
    native = base64.b64decode(result['artifact']['base64'])
    assert result['artifact']['sha256'] == hashlib.sha256(native).hexdigest()
    assert result['artifact']['size'] == len(native)
    assert document == prefs.model_dump(mode='json', by_alias=True)
    assert result['generatedDate'] == '2026-11-12'
    if format == 'md':
        assert '预览编制人' in native.decode() and '2026\\-11\\-12' in native.decode()
        assert result['pdf'] is None
    else:
        assert result['pdf'] is not None, result['issues']
        assert result['pages']
        assert all(base64.b64decode(page['base64']).startswith(bytes([137,80,78,71])) for page in result['pages'])
        pdf_bytes = base64.b64decode(result['pdf']['base64'])
        assert hashlib.sha256(pdf_bytes).hexdigest() == result['pdf']['sha256']
        text = ''.join(page.extract_text() for page in PdfReader(BytesIO(pdf_bytes)).pages)
        assert '预览编制人' in text and '2026-11-12' in text
        if format == 'xlsx':
            book = load_workbook(BytesIO(native))
            assert book['示例数据']['B4'].value == '=SUM(B2:B3)'
            assert book['说明']['A2'].value == '预览编制人'
        elif format == 'pptx':
            from pptx.enum.shapes import MSO_SHAPE_TYPE

            deck = Presentation(BytesIO(native))
            assert any(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for shape in deck.slides[1].shapes)
            assert any(shape.has_text_frame and '预览编制人' in shape.text for shape in deck.slides[-1].shapes)
        elif format == 'word':
            doc = Document(BytesIO(native))
            assert any(p.text == '实际原生落款' for p in doc.paragraphs)


def test_conversion_failure_keeps_generated_native_file(monkeypatch):
    from smart_reporting.management import configuration_preview as module
    def fail(*args, **kwargs):
        raise RuntimeError('private path or engine details must not leak')
    monkeypatch.setattr(module, 'libreoffice_to_pdf', fail)
    document = FormatPreferences.model_validate({'common': {'signer': '保留原生'}}).model_dump(mode='json', by_alias=True)
    result = render_preference_preview(document, 'xlsx', generated_date='2026-11-12')
    assert result['pdf'] is None
    assert base64.b64decode(result['artifact']['base64']).startswith(b'PK')
    assert result['issues'][0]['code'] == 'management_preference_preview_conversion_failed'
    assert 'private path' not in str(result)


def test_markdown_preview_uses_saved_syntax_preferences():
    document = FormatPreferences.model_validate({'common': {'signer': '编制'},
        'md': {'listMarker': '*', 'codeFence': 'tildes'}}).model_dump(mode='json', by_alias=True)
    result = render_preference_preview(document, 'md', generated_date='2026-11-12')
    text = base64.b64decode(result['artifact']['base64']).decode()
    assert '* 列表样例' in text
    assert '~~~text\n固定代码样例\n~~~' in text


def test_markdown_preview_uses_saved_navigation_and_preserves_values():
    document = FormatPreferences.model_validate({'common': {'signer': '编制'}, 'md': {'toc': True}}).model_dump(mode='json', by_alias=True)
    result = render_preference_preview(document, 'md', generated_date='2026-11-12')
    text = base64.b64decode(result['artifact']['base64']).decode()
    assert '[1\\. 样例概览](#report-md-heading-1)' in text
    assert text.count('1234.56') == 1 and text.count('-234.56') == 1
    assert text.count('<!-- report-signature:v1 -->') == 1
    assert result['issues'] == []


@pytest.mark.parametrize('format', ['word', 'pdf'])
@pytest.mark.parametrize('include_sources', [True, False])
def test_native_preview_uses_document_structure_and_registered_sample_sources(format, include_sources):
    from pathlib import Path

    model = FormatPreferences.model_validate({'common': {'signer': '排版编制', 'dateFormat': 'iso'},
        format: {'cover': not include_sources, 'toc': not include_sources, 'sources': include_sources}})
    document = model.model_dump(mode='json', by_alias=True)
    preview = render_preference_preview(document, format, generated_date='2026-11-13')
    native = base64.b64decode(preview['artifact']['base64'])
    pdf_bytes = base64.b64decode(preview['pdf']['base64'])
    pages = [page.extract_text() for page in PdfReader(BytesIO(pdf_bytes)).pages]
    text = '\n'.join(pages)
    assert ('固定排版样例，非业务数据' in text) == include_sources
    assert ('实际引用附录' in text) == include_sources
    assert ('[来源 001]' in text) == include_sources
    assert ('目录' in text) == (not include_sources)
    assert '以下仅为排版样例，不代表真实业务数据。' in text
    assert '1234.56' in text and '-234.56' in text and '2026-11-13' in text
    assert '排版编制' in text and '[[citation:' not in text
    if not include_sources:
        assert '样例概览' not in pages[0] and '格式偏好预览' in pages[0]
    if format == 'word':
        doc = Document(BytesIO(native))
        fields = doc.element.xpath('//w:instrText')
        assert any('TOC ' in (field.text or '') for field in fields) == (not include_sources)
        assert len(doc.tables) == 1
        assert sum(paragraph.text == '排版编制' for paragraph in doc.paragraphs) >= 1
    assert document == model.model_dump(mode='json', by_alias=True)
    output = Path('output/system-config-preferences/document-output')
    output.mkdir(exist_ok=True)
    name = format + ('-sources' if include_sources else '-frontmatter')
    (output / (name + ('.docx' if format == 'word' else '.pdf'))).write_bytes(native)
    if format == 'word':
        (output / (name + '.pdf')).write_bytes(pdf_bytes)
    for index, page in enumerate(preview['pages'], 1):
        (output / (name + '-' + str(index) + '.png')).write_bytes(base64.b64decode(page['base64']))


@pytest.mark.parametrize('keep', [True, False])
def test_word_preview_contains_native_image_and_consumes_chart_pagination(keep):
    model = FormatPreferences.model_validate({'common': {'signer': '图文编制', 'dateFormat': 'iso'},
        'word': {'cover': False, 'toc': False, 'charts': {'keepWithCaption': keep}}})
    preview = render_preference_preview(model.model_dump(mode='json', by_alias=True), 'word', generated_date='2026-11-13')
    document = Document(BytesIO(base64.b64decode(preview['artifact']['base64'])))
    assert len(document.inline_shapes) == 1
    picture = next(item for item in document.paragraphs if item._p.xpath('.//w:drawing'))
    caption = next(item for item in document.paragraphs if item.text == '图表：固定排版示例')
    assert picture.paragraph_format.keep_with_next is keep
    assert caption.paragraph_format.keep_together is keep
    text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(base64.b64decode(preview['pdf']['base64']))).pages)
    assert '固定排版示例' in text and '1234.56' in text and '-234.56' in text
    assert '图文编制' in text and '2026-11-13' in text
