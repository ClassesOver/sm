"""MD表格外观可逆，跨格式投影仍使用原始业务表。"""
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from smart_reporting.preferences.markdown_adapter import apply_markdown_preferences
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.report_runtime.projection import (
    build_render_projection,
    verify_render_projection,
)

TABLE = '| 项目 | 金额 |\n| :--- | ---: |\n| **收入** | 1234.5600 |\n| [成本](https://example.invalid) | -234.56 |\n| A\\|B | `x < y` |\n'


def prefs(style):
    return resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '编制'}, 'md': {'tableStyle': style}}), 'md')


def test_html_table_preserves_cells_inline_styles_alignment_and_exact_pipe_source():
    source = '## 明细\n\n' + TABLE + '\n表后原文。\n'
    changed = apply_markdown_preferences(source, prefs('html'))
    assert '<table data-report-md-source=' in changed
    html = BeautifulSoup(changed, 'html.parser')
    assert [cell.get_text() for cell in html.find_all('td')] == ['收入', '1234.5600', '成本', '-234.56', 'A|B', 'x < y']
    assert html.find('strong').text == '收入'
    assert html.find('a')['href'] == 'https://example.invalid'
    assert html.find_all('th')[1]['style'] == 'text-align:right'
    assert apply_markdown_preferences(changed, prefs('html')) == changed
    assert apply_markdown_preferences(changed, prefs('pipe')) == source


def test_table_transform_ignores_code_and_user_html_and_restores_multiple_tables():
    user_html = '<table><tr><td>原生HTML 5678</td></tr></table>\n'
    fence = chr(96) * 3
    fenced = fence + 'md\n' + TABLE + fence + '\n'
    source = user_html + '\n' + TABLE + '\n' + fenced + '\n' + TABLE
    changed = apply_markdown_preferences(source, prefs('html'))
    assert changed.count('<table data-report-md-source=') == 2
    assert user_html in changed and fenced in changed
    assert apply_markdown_preferences(changed, prefs('pipe')) == source
    parser = MarkdownIt('commonmark', {'html': True}).enable('table')
    assert BeautifulSoup(parser.render(changed), 'html.parser').get_text().split() == BeautifulSoup(parser.render(source), 'html.parser').get_text().split()


def test_foreign_or_edited_table_metadata_is_not_used_to_replace_visible_data():
    changed = apply_markdown_preferences(TABLE, prefs('html'))
    assert '<table data-report-md-source=' in changed
    edited = changed.replace('<td style="text-align:right">1234.5600</td>', '<td style="text-align:right">9999</td>')
    assert edited != changed
    assert apply_markdown_preferences(edited, prefs('pipe')) == edited
    invalid = '<table data-report-md-source="not-valid"><tr><td>保留</td></tr></table>\n'
    assert apply_markdown_preferences(invalid, prefs('pipe')) == invalid
    fenced = '~~~html\n' + changed + '~~~\n'
    assert apply_markdown_preferences(fenced, prefs('pipe')).count('data-report-md-source=') == 1


def test_pdf_word_projection_restores_table_before_business_transforms_and_attests_it():
    source = '# 报告\n\n## 1. 明细\n\n' + TABLE
    changed = apply_markdown_preferences(source, prefs('html'))
    projection = build_render_projection(changed, [])
    assert any(stage.name == 'format_tables/1' for stage in projection.stages)
    assert projection.markdown == build_render_projection(source, []).markdown
    assert 'data-report-md-source=' not in projection.markdown
    assert verify_render_projection(projection.receipt, changed, [])['status'] == 'verified'


def test_adjacent_text_no_final_newline_and_nested_tables_round_trip():
    for source in [TABLE.rstrip('\n'), TABLE + '紧跟正文\n', '前文\n\n' + TABLE,
        '> 引用\n>\n' + ''.join('> ' + line for line in TABLE.splitlines(keepends=True))]:
        changed = apply_markdown_preferences(source, prefs('html'))
        assert apply_markdown_preferences(changed, prefs('pipe')) == source
        assert apply_markdown_preferences(changed, prefs('html')) == changed


def test_saved_html_table_preference_reaches_actual_markdown_preview():
    import base64

    from smart_reporting.management.configuration_preview import render_preference_preview

    model = FormatPreferences.model_validate({'common': {'signer': '编制'}, 'md': {'tableStyle': 'html'}})
    preview = render_preference_preview(model.model_dump(mode='json', by_alias=True), 'md', generated_date='2026-11-12')
    source = base64.b64decode(preview['artifact']['base64']).decode()
    assert '<table data-report-md-source=' in source
    assert source.count('<!-- report-signature:v1 -->') == 1
    assert '1234.56' in source and '-234.56' in source


def test_actual_pdf_word_restore_md_tables_and_preserve_native_business_cells(tmp_path):
    import hashlib

    from docx import Document
    from pypdf import PdfReader

    from smart_reporting.preferences.document_adapter import document_design
    from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime
    from smart_reporting.reporting.tests.test_report_runtime import _docx_postprocess_context

    model = FormatPreferences.model_validate({'common': {'signer': '编制'},
        'pdf': {'cover': False, 'toc': False}, 'word': {'cover': False, 'toc': False}})
    formats = {format: resolve_format_preferences(model, format) for format in ('pdf', 'word')}
    source = tmp_path / 'report.md'
    table = TABLE.replace('[成本](https://example.invalid)', '成本')
    source.write_text(apply_markdown_preferences('# 格式偏好预览\n\n## 1. 样例概览\n\n[[section:overview]]\n\n' + table, prefs('html')))
    context = _docx_postprocess_context()
    context.update(title='格式偏好预览', sections=[{'code': 'overview', 'sectionNumber': '1', 'title': '样例概览'}],
        sectionNumbers=['1'], headingNumbers=[{'level': 2, 'number': '1', 'title': '样例概览',
            'sectionCode': 'overview', 'anchor': 'report-section-overview'}])
    state = {'jobId': 'md-table-validation', 'sources': [{'path': source.name, 'size': source.stat().st_size,
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}], '_documentContext': context,
        '_formatPreferences': formats, '_formatDesigns': {format: document_design(value).compact() for format, value in formats.items()}}
    result = ReportRuntime(tmp_path).render_markdown(state, 'report.md', 'revision/report.pdf',
        '.reporting-tmp/workspace-report-md-table-render/render.pdf')
    assert result['status'] == 'rendered'
    doc = Document(tmp_path / 'revision/report.docx')
    assert any(cell.text == '1234.5600' for table in doc.tables for row in table.rows for cell in row.cells)
    text = '\n'.join(page.extract_text() for page in PdfReader(tmp_path / 'revision/report.pdf').pages)
    assert '1234.5600' in text and '-234.56' in text
    assert 'data-report-md-source' not in text


def test_html_business_table_keeps_registry_identity_and_trace_editor_grids():
    import hashlib

    from smart_reporting.report_editor.table_ai import _parse_table_grid, _table_body_for_id
    from smart_reporting.reporting.delivery.artifacts_v1 import _markdown_table_artifacts
    from smart_reporting.reporting.trace.table_quality import _grid, uncovered_table_lines

    source = '[[table:registered]]\n' + TABLE + '\n[[/table:registered]]\n'
    changed = apply_markdown_preferences(source, prefs('html'))
    body = _table_body_for_id(changed, 'registered')
    assert body and 'data-report-md-source=' in body
    assert _grid(body) == _grid(TABLE)
    assert _parse_table_grid(body) == _parse_table_grid(TABLE)
    artifact = _markdown_table_artifacts(changed)[0]
    assert artifact.sha256 == hashlib.sha256(body.encode()).hexdigest()
    assert uncovered_table_lines(changed, {'registered'}) == ()
    assert len(uncovered_table_lines(changed, set())) == 1
    drifted = changed.replace('>1234.5600<', '>9999<')
    assert _grid(_table_body_for_id(drifted, 'registered')) == []
    assert len(uncovered_table_lines(drifted, set())) == 1


def test_semantic_review_keeps_explicit_numeric_reference_table_context():
    from smart_reporting.reporting.trace.claim_semantics import _section_narrative

    source = '## 说明\n\n' + TABLE.replace('**收入**', '【当前数值引用】')
    changed = apply_markdown_preferences(source, prefs('html'))
    assert _section_narrative(changed) == _section_narrative(source)
