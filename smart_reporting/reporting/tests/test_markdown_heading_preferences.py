"""标题层级只控制登记标题的Markdown展示，不改变冻结的语义层级。"""
import pytest
from markdown_it import MarkdownIt
from pydantic import ValidationError

from smart_reporting.preferences.markdown_adapter import apply_markdown_preferences
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.draft_v1 import (
    ReportDraft,
    ReportDraftBlock,
    ReportDraftSection,
    ReportSectionDefinition,
    assemble_report_markdown,
)


def preferences(level=4):
    return resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '编制'}, 'md': {'sectionHeadingLevel': level, 'toc': True}}), 'md')


def assemble(level=4):
    draft = ReportDraft(sections=(ReportDraftSection(sectionCode='overview', blocks=(
        ReportDraftBlock(blockId='body', markdown='### 子项\n\n#### 明细\n\n保留正文1234.5600。\n\n'
            '~~~text\n### 代码示例\n~~~'),)),))
    return assemble_report_markdown(draft, expected_title='标题验证', markdown_path='report.md',
        sections=(ReportSectionDefinition(code='overview', sectionNumber='1', title='概览'),),
        citation_ids=(), markdown_preferences=preferences(level), generated_date='2026-11-13')


def headings(source):
    return [(token.tag, tokens[index + 1].content.split(' <!-- report-md-heading-level:')[0])
        for tokens in [MarkdownIt('commonmark', {'html': True}).parse(source)]
        for index, token in enumerate(tokens) if token.type == 'heading_open']


@pytest.mark.parametrize(('level', 'tags'), [(2, ['h1', 'h2', 'h3', 'h4']),
    (3, ['h1', 'h3', 'h4', 'h5']), (4, ['h1', 'h4', 'h5', 'h6'])])
def test_formal_assembly_shifts_only_registered_heading_levels(level, tags):
    result = assemble(level)
    assert [tag for tag, _title in headings(result.markdown)] == tags
    assert [title for _tag, title in headings(result.markdown)] == ['标题验证', '1. 概览', '1.1 子项', '1.1.1 明细']
    assert [item.level for item in result.heading_numbers] == [2, 3, 4]
    assert '### 代码示例' in result.markdown and '保留正文1234.5600。' in result.markdown


@pytest.mark.parametrize('value', [1, 5, 2.0, True, '3'])
def test_heading_level_contract_rejects_invalid_types_and_unsupported_levels(value):
    with pytest.raises(ValidationError):
        preferences(value)


def test_display_level_is_reversible_idempotent_and_leaves_unregistered_headings_alone():
    from smart_reporting.preferences.markdown_headings import restore_heading_levels

    changed = assemble().markdown
    assert apply_markdown_preferences(changed, preferences()) == changed
    reset = apply_markdown_preferences(changed, preferences(2))
    assert headings(reset) == headings(assemble(2).markdown)
    assert 'report-md-heading-level:' not in reset
    assert restore_heading_levels(changed).count('## 1. 概览') == 1
    manual = '# 标题\n\n## 手写标题\n\n> ### 引用示例\n'
    assert headings(apply_markdown_preferences(manual, preferences())) == headings(manual)


def test_manual_heading_edits_and_code_metadata_are_not_restored_or_rewrapped():
    from smart_reporting.preferences.markdown_headings import restore_heading_levels

    changed = assemble().markdown
    edited = changed.replace('1. 概览', '1. 手工改名')
    assert '#### 1. 手工改名' in restore_heading_levels(edited)
    manual_line = next(line for line in edited.splitlines() if line.startswith('#### 1. 手工改名'))
    reapplied = apply_markdown_preferences(edited, preferences())
    assert manual_line in reapplied.splitlines()
    assert reapplied.count('report-md-heading-level:') == edited.count('report-md-heading-level:')
    example = '~~~html\n' + changed + '\n~~~\n'
    assert restore_heading_levels(example) == example


def test_word_pdf_projection_restores_semantic_levels_with_authenticated_stage():
    from smart_reporting.reporting.delivery.report_runtime.projection import (
        build_render_projection,
        verify_render_projection,
    )

    source = assemble().markdown
    sections = [{'code': 'overview', 'title': '概览'}]
    projected = build_render_projection(source, sections)
    assert [tag for tag, _ in headings(projected.markdown)] == ['h1', 'h2', 'h3', 'h4']
    assert 'report-md-heading-level:' not in projected.markdown
    assert any(stage.name == 'format_heading_levels/1' for stage in projected.stages)
    assert verify_render_projection(projected.receipt, source, sections)['status'] == 'verified'


def test_trace_offsets_and_section_semantics_survive_display_level_changes():
    from smart_reporting.reporting.trace.claim_semantics import _section_narrative
    from smart_reporting.reporting.trace.markdown_body import trace_body

    source = assemble().markdown
    traced = trace_body(source)
    assert len(traced) == len(source)
    offset = source.index('[[section:overview]]')
    assert traced[offset:offset + len('[[section:overview]]')] == '[[section:overview]]'
    assert [tag for tag, _ in headings(traced)] == ['h1', 'h2', 'h3', 'h4']
    assert _section_narrative(source) == _section_narrative(assemble(2).markdown)


def test_registered_heading_numbers_are_not_mistaken_for_business_quantities():
    from smart_reporting.reporting.trace.claim_semantics import project_semantic_headings

    rendered = assemble()
    projected = project_semantic_headings(rendered.markdown, rendered.heading_numbers)
    assert headings(projected) == [('h1', '标题验证'), ('h2', '1. 概览'), ('h3', '子项'), ('h4', '明细')]


def test_heading_display_metadata_does_not_change_registered_statement_identity():
    import hashlib

    from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprint

    source = '### 1.1 收入1234.56[[citation:source1]][[claim:claim1]]\n'
    changed = apply_markdown_preferences(source, {**preferences(), 'toc': False},
        heading_numbers=[{'level': 3, 'number': '1.1', 'title': '收入1234.56'}],
        citation_presentations=[{'citationId': 'source1', 'label': '登记来源', 'coverageItems': []}])
    expected = hashlib.sha256('###1.1收入1234.56'.encode()).hexdigest()
    assert statement_fingerprint(source, 'claim1') == expected
    assert statement_fingerprint(changed, 'claim1') == expected


def test_actual_saved_preview_uses_selected_heading_level():
    import base64

    from smart_reporting.management.configuration_preview import render_preference_preview

    model = FormatPreferences.model_validate({'common': {'signer': '编制'}, 'md': {'sectionHeadingLevel': 4}})
    result = render_preference_preview(model.model_dump(mode='json', by_alias=True), 'md', generated_date='2026-11-13')
    source = base64.b64decode(result['artifact']['base64']).decode()
    assert headings(source)[:2] == [('h1', '格式偏好预览'), ('h4', '1. 样例概览')]


def test_reference_toggles_keep_heading_metadata_reversible():
    from smart_reporting.preferences.markdown_headings import restore_heading_levels

    source = '# 标题\n\n## 1. 概览[[citation:source1]]\n\n正文1234.56。\n'
    registered = [{'level': 2, 'number': '1', 'title': '概览'}]
    citations = [{'citationId': 'source1', 'label': '登记来源', 'coverageItems': []}]
    shown = apply_markdown_preferences(source, preferences(), heading_numbers=registered, citation_presentations=citations)
    hidden = apply_markdown_preferences(shown, {**preferences(), 'references': False})
    assert [tag for tag, _ in headings(hidden)] == ['h1', 'h4']
    assert restore_heading_levels(hidden).count('## 1. 概览') == 1
    restored = apply_markdown_preferences(hidden, preferences())
    assert restored == shown


def test_legacy_snapshot_without_heading_field_keeps_original_levels():
    old = preferences(2)
    old.pop('sectionHeadingLevel')
    source = '# 标题\n\n## 1. 概览\n'
    result = apply_markdown_preferences(source, old, heading_numbers=[{'level': 2, 'number': '1', 'title': '概览'}])
    assert [tag for tag, _ in headings(result)] == ['h1', 'h2']


def test_closing_hashes_inline_format_and_crlf_preserve_visible_heading_text():
    from bs4 import BeautifulSoup

    from smart_reporting.preferences.markdown_headings import restore_heading_levels

    source = '# 标题\r\n\r\n### 1.1 **加粗** `代码` ###\r\n\r\n正文[[claim:claim1]]。\r\n'
    result = apply_markdown_preferences(source, {**preferences(), 'toc': False}, heading_numbers=[
        {'level': 3, 'number': '1.1', 'title': '加粗 代码'}])
    parser = MarkdownIt('commonmark', {'html': True})
    before = parser.render(source)
    after = parser.render(result)
    assert '<h5>1.1 <strong>加粗</strong> <code>代码</code>' in after
    assert BeautifulSoup(after, 'html.parser').find('h5').get_text().strip() == '1.1 加粗 代码'
    assert restore_heading_levels(result) == source
    assert apply_markdown_preferences(result, {**preferences(), 'toc': False}) == result
    assert '正文[[claim:claim1]]。' in result and '<h3>' in before


def test_actual_word_pdf_keep_semantic_headings_from_markdown_level_four(tmp_path):
    import hashlib
    from pathlib import Path

    from docx import Document
    from pypdf import PdfReader

    from smart_reporting.preferences.document_adapter import document_design
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime

    rendered = assemble()
    source = tmp_path / 'report.md'
    source.write_text(rendered.markdown)
    model = FormatPreferences.model_validate({'common': {'signer': '编制', 'dateFormat': 'iso'},
        'word': {'cover': False, 'toc': False}, 'pdf': {'cover': False, 'toc': False}})
    formats = {format: resolve_format_preferences(model, format) for format in ('word', 'pdf')}
    state = {'jobId': 'md-heading-level-validation', 'sources': [{'path': source.name,
        'size': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}],
        '_documentContext': {'title': '标题验证', 'periodLabel': '2026', 'organizationName': '编制',
            'generatedByLabel': 'Reporting Agent', 'watermarkText': '', 'generatedDate': '2026-11-13',
            'sections': [{'code': 'overview', 'sectionNumber': '1', 'title': '概览'}], 'sectionNumbers': ['1'],
            'headingNumbers': [item.model_dump(mode='json', by_alias=True) for item in rendered.heading_numbers]},
        '_formatPreferences': formats,
        '_formatDesigns': {format: document_design(value).compact() for format, value in formats.items()}}
    result = ReportRuntime(tmp_path).render_markdown(state, 'report.md', 'revision/report.pdf',
        '.reporting-tmp/workspace-report-md-heading-level-render/render.pdf')
    assert result['status'] == 'rendered'
    document = Document(tmp_path / 'revision/report.docx')
    native_headings = [(paragraph.style.name, paragraph.text) for paragraph in document.paragraphs
        if paragraph.style.name.startswith('Heading')]
    assert native_headings == [('Heading 1', '1. 概览'), ('Heading 2', '1.1 子项'), ('Heading 3', '1.1.1 明细')]
    pdf_text = '\n'.join(page.extract_text() for page in PdfReader(tmp_path / 'revision/report.pdf').pages)
    for text in ('概览', '子项', '明细', '保留正文1234.5600。', '2026-11-13'):
        assert text in pdf_text
    assert 'report-md-heading-level' not in pdf_text
    output = Path('output/system-config-preferences/md-heading-level')
    output.mkdir(exist_ok=True)
    for path in (source, tmp_path / 'revision/report.docx', tmp_path / 'revision/report.pdf'):
        (output / path.name).write_bytes(path.read_bytes())
