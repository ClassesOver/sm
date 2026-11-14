"""图片说明显示独立于图片身份、来源绑定和其他格式。"""
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from smart_reporting.preferences.markdown_adapter import apply_markdown_preferences, strip_signature
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.draft_v1 import (
    ReportChartInput,
    ReportDraft,
    ReportDraftBlock,
    ReportDraftSection,
    ReportSectionDefinition,
    assemble_report_markdown,
)


def preferences(visible):
    return resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '编制'}, 'md': {'imageCaptions': visible}}), 'md')


def assemble(visible):
    return assemble_report_markdown(ReportDraft(sections=(ReportDraftSection(sectionCode='overview', blocks=(
        ReportDraftBlock(blockId='body', markdown='保留正文与来源。', chartIds=('chart1',), citationIds=('source1',)),)),)),
        expected_title='报告', markdown_path='reports/report.md',
        sections=(ReportSectionDefinition(code='overview', sectionNumber='1', title='概览'),),
        charts=(ReportChartInput(chartId='chart1', fileName='chart.png', title='指标分布', altText='可访问的图片说明',
            citationIds=('source1',)),), citation_ids=('source1',), markdown_preferences=preferences(visible),
        generated_date='2026-11-12')


def html(source):
    return BeautifulSoup(MarkdownIt('commonmark', {'html': True}).render(source), 'html.parser')


def test_formal_assembly_hides_only_generated_caption_keeps_image_alt_title_citations():
    visible, hidden = assemble(True), assemble(False)
    assert '图表：指标分布' in html(visible.markdown).get_text()
    assert '图表：指标分布' not in html(hidden.markdown).get_text()
    for source in (visible.markdown, hidden.markdown):
        image = html(source).find('img')
        assert image['src'] == 'chart.png'
        assert image['alt'] == '可访问的图片说明' and image['title'] == '指标分布'
        assert '[[citation:source1]]' in source and '保留正文与来源。' in source
    assert visible.chart_paths == hidden.chart_paths


def test_caption_toggle_round_trips_is_idempotent_and_preserves_user_notes():
    source = strip_signature(assemble(False).markdown) + '\n*手写说明应保留。*\n'
    assert '图表：指标分布' not in html(source).get_text()
    shown = apply_markdown_preferences(source, preferences(True))
    assert '图表：指标分布' in html(shown).get_text()
    assert '手写说明应保留。' in html(shown).get_text()
    assert apply_markdown_preferences(shown, preferences(True)) == shown
    assert apply_markdown_preferences(shown, preferences(False)) == source


def test_caption_projection_is_authenticated_and_does_not_leak_md_visibility_to_word_pdf():
    from smart_reporting.reporting.delivery.report_runtime.projection import (
        build_render_projection,
        verify_render_projection,
    )

    visible, hidden = assemble(True).markdown, assemble(False).markdown
    citations = [{'citationId': 'source1', 'label': '来源一', 'coverageItems': []}]
    projection = build_render_projection(hidden, [], citation_presentations=citations)
    assert projection.markdown == build_render_projection(visible, [], citation_presentations=citations).markdown
    assert '图表：指标分布' in projection.markdown
    assert 'report-md-caption:' not in projection.markdown
    assert any(stage.name == 'format_captions/1' for stage in projection.stages)
    assert verify_render_projection(projection.receipt, hidden, [], citation_presentations=citations)['status'] == 'verified'


def test_chart_fingerprint_and_semantic_review_are_independent_of_md_caption_visibility():
    from smart_reporting.reporting.trace.chart_subjects import chart_presentations
    from smart_reporting.reporting.trace.claim_semantics import _section_narrative

    visible, hidden = assemble(True).markdown, assemble(False).markdown
    assert chart_presentations(visible) == chart_presentations(hidden)
    assert _section_narrative(visible) == _section_narrative(hidden)


def test_caption_metadata_in_code_or_after_a_changed_image_is_not_applied():
    from smart_reporting.preferences.markdown_captions import restore_image_captions

    hidden = strip_signature(assemble(False).markdown)
    assert 'report-md-caption:v1:' in hidden
    fence = chr(96) * 3
    code = fence + 'md\n' + hidden + fence + '\n'
    assert restore_image_captions(code) == code
    changed = hidden.replace('](chart.png ', '](other.png ')
    assert changed != hidden
    assert restore_image_captions(changed) == changed
    user = '![用户图片](chart.png "指标分布")\n\n*用户手写图注。*\n'
    assert apply_markdown_preferences(user, preferences(False)) == user


def test_visible_manual_caption_edit_is_not_replaced_from_hidden_metadata():
    from smart_reporting.preferences.markdown_captions import restore_image_captions

    shown = strip_signature(assemble(True).markdown)
    changed = shown.replace('*图表：指标分布*', '*手动修订说明*')
    assert changed != shown
    assert restore_image_captions(changed) == changed
    assert apply_markdown_preferences(changed, preferences(False)) == changed


def test_hidden_caption_payload_cannot_inject_text_not_present_in_image_title():
    import base64
    import re

    from smart_reporting.preferences.markdown_captions import restore_image_captions

    hidden = strip_signature(assemble(False).markdown)
    for text in ('*图表：伪造说明*', '*图表：指标分布*\n\n额外业务断言。', '<script>payload</script>'):
        encoded = base64.b64encode(text.encode()).decode()
        forged = re.sub(r'(report-md-caption:v1:[0-9a-f]{64}:)[A-Za-z0-9+/=]+',
            lambda match: match.group(1) + encoded, hidden)
        assert restore_image_captions(forged) == forged
        assert apply_markdown_preferences(forged, preferences(True)) == forged


def test_saved_caption_preference_changes_real_md_preview_without_external_image_dependency():
    import base64

    from smart_reporting.management.configuration_preview import render_preference_preview

    for visible in (True, False):
        model = FormatPreferences.model_validate({'common': {'signer': '编制'}, 'md': {'imageCaptions': visible}})
        preview = render_preference_preview(model.model_dump(mode='json', by_alias=True), 'md', generated_date='2026-11-12')
        source = base64.b64decode(preview['artifact']['base64']).decode()
        parsed = html(source)
        assert ('示例图片说明' in parsed.get_text()) == visible
        image = parsed.find('img')
        assert image and image['src'].startswith('data:image/png;base64,')
        assert source.count('<!-- report-signature:v1 -->') == 1


def test_generated_caption_with_escaped_punctuation_round_trips_and_broken_metadata_is_ignored():
    from smart_reporting.preferences.markdown_captions import restore_image_captions
    from smart_reporting.reporting.delivery.draft_v1 import _chart_figure_markdown

    chart = ReportChartInput(chartId='chart1', fileName='chart.png',
        title='收入 *含税* [A] & "样例"', altText='指标图片', citationIds=('source1',))
    legacy = _chart_figure_markdown(chart, 'chart.png')
    hidden = _chart_figure_markdown(chart, 'chart.png', caption_preferences=preferences(False))
    assert restore_image_captions(hidden) == legacy
    shown = apply_markdown_preferences(hidden, preferences(True))
    assert restore_image_captions(shown) == legacy
    for broken in (hidden.replace('<!-- /report-md-caption:v1 -->', ''),
        hidden.replace(' -->', '! -->', 1), '> ' + hidden.replace('\n', '\n> ')):
        assert restore_image_captions(broken) == broken


def test_actual_word_pdf_restore_hidden_md_caption_and_keep_native_image(tmp_path):
    import hashlib
    import shutil
    from pathlib import Path

    from docx import Document
    from PIL import Image
    from pypdf import PdfReader

    from smart_reporting.preferences.document_adapter import document_design
    from smart_reporting.preferences.markdown_captions import image_caption_markdown
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.tests.test_report_runtime import _docx_postprocess_context

    image = tmp_path / 'chart.png'
    Image.new('RGB', (240, 100), '#174a66').save(image)
    source = tmp_path / 'report.md'
    source.write_text('# 格式偏好预览\n\n## 1. 样例概览\n\n[[section:overview]]\n\n保留正文。\n\n' +
        image_caption_markdown('![指标图](chart.png "指标分布")', '*图表：指标分布*', visible=False) + '\n')
    model = FormatPreferences.model_validate({'common': {'signer': '编制', 'dateFormat': 'iso'},
        'md': {'imageCaptions': False}, 'pdf': {'cover': False, 'toc': False}, 'word': {'cover': False, 'toc': False}})
    formats = {format: resolve_format_preferences(model, format) for format in ('pdf', 'word')}
    context = _docx_postprocess_context()
    context.update(title='格式偏好预览', generatedDate='2026-11-12',
        sections=[{'code': 'overview', 'sectionNumber': '1', 'title': '样例概览'}], sectionNumbers=['1'],
        headingNumbers=[{'level': 2, 'number': '1', 'title': '样例概览',
            'sectionCode': 'overview', 'anchor': 'report-section-overview'}])
    state = {'jobId': 'md-caption-validation',
        'sources': [{'path': file.name, 'size': file.stat().st_size,
            'sha256': hashlib.sha256(file.read_bytes()).hexdigest()} for file in (source, image)],
        '_documentContext': context, '_formatPreferences': formats,
        '_formatDesigns': {format: document_design(value).compact() for format, value in formats.items()}}
    result = ReportRuntime(tmp_path).render_markdown(state, 'report.md', 'revision/report.pdf',
        '.reporting-tmp/workspace-report-md-caption-render/render.pdf')
    assert result['status'] == 'rendered'
    document = Document(tmp_path / 'revision/report.docx')
    paragraphs = '\n'.join(paragraph.text for paragraph in document.paragraphs)
    assert paragraphs.count('图表：指标分布') == 1
    assert '保留正文。' in paragraphs and '2026-11-12' in paragraphs
    assert len(document.inline_shapes) == 1
    pdf = PdfReader(tmp_path / 'revision/report.pdf')
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert text.count('图表：指标分布') == 1
    assert '保留正文。' in text and '2026-11-12' in text
    assert sum(len(page.images) for page in pdf.pages) == 1
    assert 'report-md-caption' not in text + paragraphs
    output = Path('output/system-config-preferences/md-captions')
    output.mkdir(exist_ok=True)
    for suffix in ('docx', 'pdf'):
        shutil.copyfile(tmp_path / ('revision/report.' + suffix), output / ('restored-caption.' + suffix))
