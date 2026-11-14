"""排版维护复用真实Word样式与PDF可见文字，不改业务内容。"""
import base64
from io import BytesIO

import pytest
from docx import Document

from smart_reporting.management.configuration_preview import render_preference_preview
from smart_reporting.preferences.models import FormatPreferences


def test_editor_partial_design_preserves_actual_pdf_word_typography(tmp_path):
    import hashlib

    import pymupdf

    from smart_reporting.management.configuration_preview import MARKDOWN
    from smart_reporting.preferences.document_adapter import document_design
    from smart_reporting.preferences.models import resolve_format_preferences
    from smart_reporting.report_editor.design import (
        editor_base_design,
        editor_design_overrides,
        restore_format_defaults,
    )
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.tests.test_report_editor import _context
    from smart_reporting.reporting.tests.test_report_runtime import (
        _docx_postprocess_context,
    )

    prefs = FormatPreferences.model_validate({'common': {'signer': '冻结署名'},
        'pdf': {'cover': False, 'toc': False, 'typography': {'body': {'size': 14}}},
        'word': {'cover': False, 'toc': False, 'typography': {'body': {'size': 12}}}})
    formats = {fmt: resolve_format_preferences(prefs, fmt) for fmt in ('pdf', 'word')}
    source = tmp_path / 'report.md'
    source.write_text(MARKDOWN, encoding='utf-8')
    context = _docx_postprocess_context()
    context.update(title='格式偏好预览', sections=[{'code': 'overview', 'sectionNumber': '1', 'title': '样例概览'}],
        sectionNumbers=['1'], headingNumbers=[{'level': 2, 'number': '1', 'title': '样例概览',
            'sectionCode': 'overview', 'anchor': 'report-section-overview'}])
    state = {'jobId': 'editor-frozen', 'sources': [{'path': 'report.md', 'size': source.stat().st_size,
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}], '_documentContext': context,
        '_formatPreferences': formats, '_formatDesigns': {fmt: document_design(value).compact() for fmt, value in formats.items()}}
    editor_context = _context().model_copy(update={'job': state})
    # 恢复历史时必须移除当前样式，再叠加编辑器明确修改。
    state = restore_format_defaults({'jobId': 'editor-frozen', 'sources': state['sources'], '_formatDesigns': {
        'pdf': {'typography': {'body': {'size': 18}}}, 'word': {'typography': {'body': {'size': 16}}}}}, editor_context)
    design = editor_base_design(editor_context)
    design.typography.h1.size = 23
    state['_reportDesign'] = editor_design_overrides(editor_context, design)
    result = ReportRuntime(tmp_path).render_markdown(state, 'report.md', 'revision/report.pdf',
        '.reporting-tmp/workspace-report-editor-frozen-render/render.pdf')
    assert result['status'] == 'rendered'
    doc = Document(tmp_path / 'revision/report.docx')
    assert doc.styles['Normal'].font.size.pt == 12
    assert doc.styles['Heading 1'].font.size.pt == 23
    pdf = pymupdf.open(tmp_path / 'revision/report.pdf')
    spans = [span for page in pdf for block in page.get_text('dict')['blocks'] for line in block.get('lines', []) for span in line['spans']]
    body = next(span for span in spans if '以下仅为排版样例' in span['text'])
    assert body['size'] == pytest.approx(14, abs=.1)


@pytest.mark.parametrize('format', ['word', 'pdf'])
def test_actual_typography_keeps_body_values_and_consumes_role_styles(format):
    typography = {'body': {'size': 12, 'lineHeight': 1.8, 'spaceBefore': 3, 'spaceAfter': 7, 'indent': 18},
        'h1': {'size': 19, 'color': '#654321', 'spaceBefore': 10, 'spaceAfter': 5},
        'table': {'size': 10, 'color': '#345678'}, 'caption': {'size': 9, 'font': 'serif'}}
    prefs = FormatPreferences.model_validate({'common': {'signer': '排版验证'}, format: {
        'cover': False, 'toc': False, 'typography': typography}})
    result = render_preference_preview(prefs.model_dump(mode='json', by_alias=True), format, generated_date='2026-11-12')
    assert not result['issues']
    raw = base64.b64decode(result['artifact']['base64'])
    if format == 'word':
        doc = Document(BytesIO(raw))
        body = doc.styles['Normal']
        assert body.font.size.pt == 12
        assert body.paragraph_format.line_spacing == 1.8
        assert body.paragraph_format.first_line_indent.pt == 18
        assert body.paragraph_format.space_before.pt == 3
        assert body.paragraph_format.space_after.pt == 7
        assert doc.styles['Heading 1'].font.size.pt == 19
        assert str(doc.styles['Heading 1'].font.color.rgb) == '654321'
        assert doc.styles['Caption'].font.name == 'Noto Serif CJK SC'
        amount = next(cell for table in doc.tables for row in table.rows for cell in row.cells if cell.text == '1234.56')
        assert amount.paragraphs[0].runs[0].font.size.pt == 10
        assert str(amount.paragraphs[0].runs[0].font.color.rgb) == '345678'
    else:
        import pymupdf

        pdf = pymupdf.open(stream=raw, filetype='pdf')
        spans = [span for page in pdf for block in page.get_text('dict')['blocks'] for line in block.get('lines', []) for span in line['spans']]
        heading = next(span for span in spans if '样例概览' in span['text'])
        assert heading['size'] == pytest.approx(19, abs=.1)
        assert heading['color'] == 0x654321
        amount = next(span for span in spans if span['text'] == '1234.56')
        assert amount['size'] == pytest.approx(10, abs=.1)
        assert amount['color'] == 0x345678
