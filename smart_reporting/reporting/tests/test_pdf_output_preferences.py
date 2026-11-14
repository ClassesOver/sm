"""PDF 输出偏好必须作用于最终文件，保留业务文字及来源图片。"""
import hashlib
import json

from PIL import Image
from pypdf import PdfReader

from smart_reporting.preferences.document_adapter import document_design
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.report_design import ReportDesign, resolve_design


def test_pdf_output_design_maps_options_preserves_overrides_and_legacy_hash():
    prefs = FormatPreferences.model_validate({'common': {'signer': '编制'},
        'pdf': {'bookmarks': False, 'imageQuality': 55}})
    design = document_design(resolve_format_preferences(prefs, 'pdf'))
    assert design.pdf_output.bookmarks is False and design.pdf_output.image_quality == 55
    assert document_design(resolve_format_preferences(prefs, 'word')).pdf_output is None
    restored = resolve_design({'_formatDesigns': {'pdf': design.compact()},
        '_reportDesign': {'pdfOutput': {'imageQuality': 85}}})
    assert restored.pdf_output.bookmarks is False and restored.pdf_output.image_quality == 85
    old = ReportDesign()
    document = old.model_dump(mode='json', by_alias=True)
    for key in ('page', 'signature', 'headerFooter', 'tables', 'pdfOutput'):
        document.pop(key, None)
    assert old.digest() == hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def test_chart_image_dpi_is_frozen_per_document_format_and_keeps_legacy_digest():
    prefs = FormatPreferences.model_validate({'common': {'signer': '编制'},
        'pdf': {'charts': {'imageDpi': 240}}, 'word': {'charts': {'imageDpi': 300}}})
    pdf = document_design(resolve_format_preferences(prefs, 'pdf'))
    word = document_design(resolve_format_preferences(prefs, 'word'))
    assert pdf.charts.image_dpi == 240
    assert word.charts.image_dpi == 300
    assert ReportDesign.model_validate(pdf.compact()).charts.image_dpi == 240
    assert document_design(resolve_format_preferences(prefs, 'word'),
        overrides={'charts': {'imageDpi': 360}}).charts.image_dpi == 360
    old = ReportDesign.model_validate({'charts': {'keepWithCaption': False}})
    assert old.compact() == {'charts': {'keepWithCaption': False}}
    assert old.digest() == '42b52eb2bdc0ae5d6eeb0eff792cfc91df0dac65791b9da70b8ea617b66186cf'


def _render(root, *, bookmarks, quality, embed_fonts=True):
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime

    root.mkdir(parents=True)
    # 固定像素含足够纹理，使两档JPEG压缩的实际差异可测。
    pixels = bytes((index * 37 + index // 17) % 256 for index in range(640 * 320 * 3))
    image = root / 'chart.jpg'
    Image.frombytes('RGB', (640, 320), pixels).save(image, quality=98)
    image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    source = root / 'report.md'
    source.write_text('# PDF偏好验证\n\n[[section:overview]]\n## 1. 经营概览\n\n业务原值 1234.56。\n\n![图像质量样例](chart.jpg)\n', encoding='utf-8')
    prefs = FormatPreferences.model_validate({'common': {'signer': '输出验证编制'},
        'pdf': {'bookmarks': bookmarks, 'imageQuality': quality, 'embedFonts': embed_fonts, 'cover': False, 'toc': False},
        'word': {'cover': False, 'toc': False}})
    formats = {key: resolve_format_preferences(prefs, key) for key in ('pdf', 'word')}
    context = {'title': 'PDF偏好验证', 'periodLabel': '2026年', 'organizationName': '输出验证编制',
        'generatedByLabel': '', 'watermarkText': '', 'generatedDate': '2026-11-12', 'sectionNumbers': ['1'],
        'sections': [{'code': 'overview', 'sectionNumber': '1', 'title': '经营概览'}],
        'headingNumbers': [{'level': 2, 'number': '1', 'title': '经营概览',
            'sectionCode': 'overview', 'anchor': 'report-section-overview'}]}
    state = {'jobId': 'pdf-output-test', '_documentContext': context, '_formatPreferences': formats,
        '_formatDesigns': {key: document_design(value).compact() for key, value in formats.items()},
        'sources': [{'path': source.name, 'size': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]}
    result = ReportRuntime(root).render_markdown(state, 'report.md', 'revision/report.pdf',
        '.reporting-tmp/workspace-report-pdfoutput-render/render.pdf')
    assert result['status'] == 'rendered'
    assert hashlib.sha256(image.read_bytes()).hexdigest() == image_hash
    return PdfReader(root / 'revision/report.pdf'), root / 'revision/report.docx', result


def test_pdf_always_embeds_actual_fonts_and_legacy_disable_is_explicit_warning(tmp_path):
    reader, _, result = _render(tmp_path / 'embedded', bookmarks=True, quality=90, embed_fonts=False)
    embedded = []
    for page in reader.pages:
        for reference in page['/Resources']['/Font'].get_object().values():
            font = reference.get_object()
            for descendant in font.get('/DescendantFonts', [font]):
                descriptor = descendant.get_object().get('/FontDescriptor')
                assert descriptor is not None
                descriptor = descriptor.get_object()
                stream = descriptor.get('/FontFile2') or descriptor.get('/FontFile3') or descriptor.get('/FontFile')
                assert stream is not None
                assert stream.get_object().get_data()
                embedded.append(stream)
    assert embedded
    assert any(issue['code'] == 'pdf_font_embedding_required' for issue in result['renderIssues'])


def test_actual_pdf_bookmarks_and_jpeg_quality_preserve_content_and_native_word(tmp_path):
    from docx import Document

    low, low_word, _ = _render(tmp_path / 'low', bookmarks=False, quality=50)
    high, high_word, _ = _render(tmp_path / 'high', bookmarks=True, quality=100)
    assert low.outline == []
    assert high.outline
    sizes = []
    for reader in (low, high):
        text = '\n'.join(page.extract_text() for page in reader.pages)
        assert '1234.56' in text and '输出验证编制' in text
        streams = [image.get_object() for page in reader.pages for image in page['/Resources'].get('/XObject', {}).get_object().values()
            if image.get_object().get('/Subtype') == '/Image']
        jpeg = [image for image in streams if '/DCTDecode' in str(image.get('/Filter'))]
        assert jpeg
        assert all(int(image['/Width']) == 640 and int(image['/Height']) == 320 for image in jpeg)
        sizes.append(sum(len(image._data) for image in jpeg))
    assert sizes[0] < sizes[1] * 0.8
    assert len(low.pages) == len(high.pages)
    for path in (low_word, high_word):
        document = Document(path)
        assert '1234.56' in '\n'.join(paragraph.text for paragraph in document.paragraphs)
        assert document.inline_shapes
