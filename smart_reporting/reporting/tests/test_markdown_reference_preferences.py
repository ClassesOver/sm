"""文本报告引用只改变展示，来源身份及跨格式投影保持不变。"""
import pytest
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from smart_reporting.preferences.markdown_adapter import apply_markdown_preferences, strip_signature
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.draft_v1 import (
    ReportDraft,
    ReportDraftBlock,
    ReportDraftSection,
    ReportSectionDefinition,
    assemble_report_markdown,
)


def preferences(visible):
    return resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '编制', 'dateFormat': 'iso'}, 'md': {'references': visible}}), 'md')


def assemble(visible):
    return assemble_report_markdown(ReportDraft(sections=(ReportDraftSection(sectionCode='overview', blocks=(
        ReportDraftBlock(blockId='body', markdown='保留正文1234.5600。', citationIds=('source1',)),)),)),
        expected_title='引用验证', markdown_path='report.md',
        sections=(ReportSectionDefinition(code='overview', sectionNumber='1', title='概览'),),
        citation_ids=('source1',), markdown_preferences=preferences(visible), generated_date='2026-11-12')


def html(markdown):
    return BeautifulSoup(MarkdownIt('commonmark', {'html': True}).render(markdown), 'html.parser')


def test_formal_markdown_citation_visibility_keeps_exact_registered_identity():
    shown, hidden = assemble(True).markdown, assemble(False).markdown
    for source in (shown, hidden):
        parsed = html(source)
        marker = parsed.find('span', attrs={'data-report-md-reference': 'v1'})
        assert marker and marker.has_attr('hidden')
        assert marker.get_text() == '[[citation:source1]]'
        assert '保留正文1234.5600。' in parsed.get_text()
        assert source.count('[[citation:source1]]') == 1
    assert html(shown).find('abbr').get_text() == '[来源 001]'
    assert html(hidden).find('abbr') is None


def test_reference_toggle_is_reversible_idempotent_and_preserves_manual_labels():
    from smart_reporting.preferences.markdown_references import restore_reference_markers

    hidden = strip_signature(assemble(False).markdown) + '\n手写 [来源 001] 应保留。\n'
    shown = apply_markdown_preferences(hidden, preferences(True))
    assert html(shown).find('abbr') is not None
    assert apply_markdown_preferences(shown, preferences(False)) == hidden
    assert apply_markdown_preferences(shown, preferences(True)) == shown
    assert restore_reference_markers(hidden) == restore_reference_markers(shown)
    assert '手写 [来源 001] 应保留。' in shown


def test_reference_code_examples_and_unknown_source_ids_are_not_interpreted():
    from smart_reporting.preferences.markdown_references import (
        apply_reference_preferences,
        restore_reference_markers,
    )

    source = ('正文[[citation:source1]]。未知[[citation:foreign]]。\n\n'
        '`[[citation:source1]]`\n\n~~~md\n[[citation:source1]]\n~~~\n\n'
        '<!-- [[citation:source1]] -->\n')
    presentations = [{'citationId': 'source1', 'label': '登记来源', 'coverageItems': []}]
    shown = apply_reference_preferences(source, True, presentations)
    assert shown.count('data-report-md-reference=') == 1
    assert '未知[[citation:foreign]]' in shown
    assert restore_reference_markers(shown) == source
    assert apply_reference_preferences(source, True, None) == source
    fenced = '~~~html\n' + strip_signature(assemble(True).markdown) + '~~~\n'
    assert restore_reference_markers(fenced) == fenced


def test_reference_display_does_not_change_trace_offsets_or_create_numeric_claims():
    from smart_reporting.reporting.trace.markdown_body import trace_body

    for visible in (True, False):
        source = strip_signature(assemble(visible).markdown)
        traced = trace_body(source)
        assert len(traced) == len(source)
        offset = source.index('[[citation:source1]]')
        assert traced[offset:offset + len('[[citation:source1]]')] == '[[citation:source1]]'
        assert '[来源 001]' not in traced and 'data-report-md-reference' not in traced
        assert '保留正文1234.5600。' in traced


def test_reference_projection_and_semantics_restore_registered_markers():
    from smart_reporting.reporting.delivery.report_runtime.projection import (
        build_render_projection,
        verify_render_projection,
    )
    from smart_reporting.reporting.trace.claim_semantics import _section_narrative

    shown, hidden = assemble(True).markdown, assemble(False).markdown
    presentations = [{'citationId': 'source1', 'label': '登记来源', 'coverageItems': []}]
    for include_sources in (True, False):
        projections = [build_render_projection(source, [], citation_presentations=presentations,
            include_sources=include_sources) for source in (shown, hidden)]
        assert projections[0].markdown == projections[1].markdown
        assert ('[来源 001]' in projections[0].markdown) == include_sources
        assert 'report-md-reference' not in projections[0].markdown
        assert any(stage.name == 'format_references/1' for stage in projections[0].stages)
        assert verify_render_projection(projections[0].receipt, shown, [],
            citation_presentations=presentations, include_sources=include_sources)['status'] == 'verified'
    assert _section_narrative(shown) == _section_narrative(hidden)


def test_registered_source_names_are_escaped_and_manual_display_edits_are_preserved():
    from smart_reporting.preferences.markdown_references import (
        apply_reference_preferences,
        restore_reference_markers,
    )

    source = '正文[[citation:source1]]。\n'
    presentations = [{'citationId': 'source1', 'label': '<审阅> "来源" & 数据', 'coverageItems': []}]
    shown = apply_reference_preferences(source, True, presentations)
    assert html(shown).find('abbr')['title'] == '<审阅> "来源" & 数据'
    assert '<审阅>' not in shown and restore_reference_markers(shown) == source
    changed = shown.replace(r'\[来源 001\]', r'\[手改来源\]')
    assert restore_reference_markers(changed) == changed
    assert apply_reference_preferences(changed, False, presentations) == changed


def test_citation_examples_in_links_image_alt_html_attributes_and_escapes_are_preserved():
    from smart_reporting.preferences.markdown_references import (
        apply_reference_preferences,
        restore_reference_markers,
    )

    examples = ['[说明](https://example.invalid/[[citation:source1]])',
        '[引用示例 [[citation:source1]]](https://example.invalid)',
        '![示例 [[citation:source1]]](chart.png)', '<span title="[[citation:source1]]">文字</span>',
        r'\[[citation:source1]]']
    presentations = [{'citationId': 'source1', 'label': '登记来源', 'coverageItems': []}]
    for example in examples:
        source = example + '\n\n正文[[citation:source1]]\n'
        shown = apply_reference_preferences(source, True, presentations)
        assert shown.startswith(example + '\n\n')
        assert shown.count('data-report-md-reference=') == 1
        assert restore_reference_markers(shown) == source


def test_table_ending_block_keeps_reference_visible_outside_html_table():
    result = assemble_report_markdown(ReportDraft(sections=(ReportDraftSection(sectionCode='overview', blocks=(
        ReportDraftBlock(blockId='body', markdown='| 项目 | 金额 |\n| --- | ---: |\n| 数据 | 1234.56 |',
            citationIds=('source1',)),)),)), expected_title='引用验证', markdown_path='report.md',
        sections=(ReportSectionDefinition(code='overview', sectionNumber='1', title='概览'),),
        citation_ids=('source1',), markdown_preferences={**preferences(True), 'tableStyle': 'html'},
        generated_date='2026-11-12')
    parsed = html(result.markdown)
    reference = parsed.find('abbr')
    assert reference is not None and reference.find_parent('table') is None
    assert result.markdown.count('[[citation:source1]]') == 1


def test_reference_links_remain_user_content_and_cannot_capture_generated_number():
    from smart_reporting.preferences.markdown_references import apply_reference_preferences

    source = ('[引用示例 [[citation:source1]]][sample]\n\n正文[[citation:source1]]\n\n'
        '[sample]: https://example.invalid\n[来源 001]: https://other.invalid\n')
    shown = apply_reference_preferences(source, True, [
        {'citationId': 'source1', 'label': '登记来源', 'coverageItems': []}])
    assert shown.startswith('[引用示例 [[citation:source1]]][sample]\n')
    parsed = html(shown)
    assert parsed.find('abbr').get_text() == '[来源 001]'
    assert parsed.find('abbr').find('a') is None


def test_initial_v1_reference_markup_still_restores_after_bracket_escape_fix():
    from smart_reporting.preferences.markdown_references import (
        apply_reference_preferences,
        restore_reference_markers,
    )

    source = '正文[[citation:source1]]\n'
    presentations = [{'citationId': 'source1', 'label': '登记来源', 'coverageItems': []}]
    current = apply_reference_preferences(source, True, presentations)
    initial = current.replace(r'\[来源 001\]', '[来源 001]')
    assert initial != current
    assert restore_reference_markers(initial) == source
    assert apply_reference_preferences(initial, True, presentations) == current


def test_reference_metadata_in_code_cannot_register_an_unbound_source_elsewhere():
    example = strip_signature(assemble(True).markdown)
    fence = chr(96) * 3
    source = fence + 'html\n' + example + fence + '\n\n示例外[[citation:source1]]\n'
    assert apply_markdown_preferences(source, preferences(False)) == source


def test_saved_reference_preference_changes_real_preview_and_preserves_source_identity():
    import base64

    from smart_reporting.management.configuration_preview import render_preference_preview

    for visible in (True, False):
        document = FormatPreferences.model_validate({'common': {'signer': '编制'}, 'md': {'references': visible}})
        preview = render_preference_preview(document.model_dump(mode='json', by_alias=True), 'md', generated_date='2026-11-12')
        source = base64.b64decode(preview['artifact']['base64']).decode()
        parsed = html(source)
        assert (parsed.find('abbr') is not None) == visible
        assert source.count('[[citation:preview-source]]') == 1
        assert parsed.find('span', hidden=True).get_text() == '[[citation:preview-source]]'
        if visible:
            assert parsed.find('abbr')['title'] == '固定排版样例，非业务数据'


def test_reference_markup_does_not_consume_claim_window_or_invalidate_semantic_context():
    from smart_reporting.preferences.markdown_references import apply_reference_preferences
    from smart_reporting.reporting.trace.claim_semantics import _claim_context
    from smart_reporting.reporting.trace.review_readability import _displayed
    from smart_reporting.reporting.trace.subject_builder import claim_status

    source = '本期收入1234.56元[[citation:source1]][[claim:claim1]]。'
    presentations = [{'citationId': 'source1', 'label': '登记来源' * 40, 'coverageItems': []}]
    expected = claim_status(source, 'claim1', 1234.56, expected_unit='元')
    assert expected['status'] == 'valid'
    for visible in (True, False):
        decorated = apply_reference_preferences(source, visible, presentations)
        assert claim_status(decorated, 'claim1', 1234.56, expected_unit='元') == expected
        assert _claim_context(decorated, 'claim1', include_previous=False, include_section=False) == (
            _claim_context(source, 'claim1', include_previous=False, include_section=False))
        assert _displayed(decorated, None) == _displayed(source, None)


@pytest.mark.parametrize('visible', [True, False])
def test_actual_word_and_pdf_keep_independent_source_visibility(tmp_path, visible):
    import hashlib
    from pathlib import Path

    from docx import Document
    from pypdf import PdfReader

    from smart_reporting.preferences.document_adapter import document_design
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime

    source = tmp_path / 'report.md'
    source.write_text(assemble(visible).markdown)
    model = FormatPreferences.model_validate({'common': {'signer': '编制', 'dateFormat': 'iso'},
        'word': {'cover': False, 'toc': False, 'sources': True},
        'pdf': {'cover': False, 'toc': False, 'sources': False}})
    formats = {format: resolve_format_preferences(model, format) for format in ('word', 'pdf')}
    state = {'jobId': 'md-references-validation', 'sources': [{'path': source.name,
        'size': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}],
        '_citationPresentations': [{'citationId': 'source1', 'label': '冻结登记来源', 'coverageItems': []}],
        '_documentContext': {'title': '引用验证', 'periodLabel': '2026', 'organizationName': '编制',
            'generatedByLabel': 'Reporting Agent', 'watermarkText': '', 'generatedDate': '2026-11-12',
            'sections': [{'code': 'overview', 'sectionNumber': '1', 'title': '概览'}], 'sectionNumbers': ['1'],
            'headingNumbers': [{'level': 2, 'number': '1', 'title': '概览',
                'sectionCode': 'overview', 'anchor': 'report-section-overview'}]},
        '_formatPreferences': formats,
        '_formatDesigns': {format: document_design(value).compact() for format, value in formats.items()}}
    result = ReportRuntime(tmp_path).render_markdown(state, 'report.md', 'revision/report.pdf',
        '.reporting-tmp/workspace-report-md-references-render/render.pdf')
    assert result['status'] == 'rendered'
    word = '\n'.join(paragraph.text for paragraph in Document(tmp_path / 'revision/report.docx').paragraphs)
    pdf = '\n'.join(page.extract_text() for page in PdfReader(tmp_path / 'revision/report.pdf').pages)
    assert '[来源 001]' in word and '冻结登记来源' in word
    assert '[来源 001]' not in pdf and '冻结登记来源' not in pdf
    for text in (word, pdf):
        assert '保留正文1234.5600。' in text and '2026-11-12' in text
        assert 'report-md-reference' not in text and '[[citation:' not in text
    output = Path('output/system-config-preferences/md-references')
    output.mkdir(exist_ok=True)
    for path in (source, tmp_path / 'revision/report.docx', tmp_path / 'revision/report.pdf'):
        (output / (('shown' if visible else 'hidden') + path.suffix)).write_bytes(path.read_bytes())
