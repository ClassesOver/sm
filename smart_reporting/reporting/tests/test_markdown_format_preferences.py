"""正式 Markdown 落款与跨格式重用不能产生重复署名。"""
from markdown_it import MarkdownIt

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.draft_v1 import (
    ReportDraft,
    ReportDraftBlock,
    ReportDraftSection,
    ReportSectionDefinition,
    assemble_report_markdown,
)
from smart_reporting.reporting.delivery.report_runtime.projection import (
    build_render_projection,
    verify_render_projection,
)


def assemble(preferences=None):
    return assemble_report_markdown(ReportDraft(sections=(ReportDraftSection(sectionCode='overview',
        blocks=(ReportDraftBlock(blockId='body', markdown='保留正文。'),)),)),
        expected_title='报告', markdown_path='reports/report.md',
        sections=(ReportSectionDefinition(code='overview', sectionNumber='1', title='概览'),),
        citation_ids=(), markdown_preferences=preferences, generated_date='2026-11-12')


def test_actual_markdown_assembly_freezes_literal_signature_and_keeps_business_content():
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {
        'signer': '编制人 *复核* <审阅>', 'dateFormat': 'chinese'},
        'md': {'signature': {'description': '内部使用\n复核后发布'}}}), 'md')
    result = assemble(prefs)
    html = MarkdownIt('commonmark', {'html': True}).render(result.markdown)
    assert '保留正文。' in result.markdown
    assert '编制人 *复核* &lt;审阅&gt;' in html
    assert '<em>复核</em>' not in html
    assert '2026年11月12日' in html and '内部使用' in html and '复核后发布' in html
    assert result.markdown.count('<!-- report-signature:v1 -->') == 1
    assert result == assemble(prefs)
    assert 'report-signature' not in assemble().markdown


def test_pdf_word_projection_excludes_md_signature_and_authenticates_the_transformation():
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': 'MD专用署名'}}), 'md')
    source = assemble(prefs).markdown.encode()
    sections = [{'code': 'overview', 'title': '概览'}]
    projection = build_render_projection(source, sections)
    assert 'MD专用署名' not in projection.markdown
    assert '保留正文。' in projection.markdown
    assert any(stage.name == 'format_signature/1' for stage in projection.stages)
    assert verify_render_projection(projection.receipt, source, sections)['status'] == 'verified'


def test_signature_cleanup_does_not_remove_unmarked_body_or_unclosed_comments():
    from smart_reporting.preferences.markdown_adapter import strip_signature

    text = '正文中的署名与日期应当保留。\n<!-- report-signature:v1 -->\n未结束标记'
    assert strip_signature(text) == text


def test_syntax_preferences_preserve_rendered_content_and_code():
    from smart_reporting.preferences.markdown_adapter import apply_markdown_preferences

    fence = chr(96) * 3
    source = '- 收入 1234.56\n  - 子项\n\n> - 引用\n\n' + fence + 'python\n- 代码\nprint("~~~")\n' + fence + '\n'
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'},
        'md': {'listMarker': '*', 'codeFence': 'tildes'}}), 'md')
    changed = apply_markdown_preferences(source, prefs)
    assert '* 收入 1234.56\n  * 子项' in changed
    assert '> * 引用' in changed
    assert '~~~~python\n- 代码\nprint("~~~")\n~~~~' in changed
    parser = MarkdownIt('commonmark')
    assert parser.render(changed) == parser.render(source)
    assert apply_markdown_preferences(changed, prefs) == changed


def test_actual_assembly_applies_syntax_and_retains_one_frozen_signature():
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'},
        'md': {'listMarker': '*', 'codeFence': 'tildes'}}), 'md')
    fence = chr(96) * 3
    draft = ReportDraft(sections=(ReportDraftSection(sectionCode='overview', blocks=(
        ReportDraftBlock(blockId='body', markdown='- 原始内容\n\n' + fence + 'text\n固定代码\n' + fence),)),))
    result = assemble_report_markdown(draft, expected_title='报告', markdown_path='reports/report.md',
        sections=(ReportSectionDefinition(code='overview', sectionNumber='1', title='概览'),),
        citation_ids=(), markdown_preferences=prefs, generated_date='2026-11-12')
    assert '* 原始内容' in result.markdown
    assert '~~~text\n固定代码\n~~~' in result.markdown
    assert result.markdown.count('<!-- report-signature:v1 -->') == 1


def test_nested_fences_unclosed_code_and_non_list_markers_keep_rendering():
    from smart_reporting.preferences.markdown_adapter import apply_markdown_preferences

    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'}}), 'md')
    samples = [
        '> ~~~python\n> - 代码\n> ~~~\n',
        '- 条目\n\n  ~~~text\n  * 代码\n  ~~~\n',
        '~~~text\n未闭合代码\n* 原样\n',
        '~~~info' + chr(96) + '\n正文\n~~~\n',
        '1. 有序列表\n\n---\n\n    * 缩进代码\n\n文字 * 行内\n',
        '* 独立列表甲\n- 独立列表乙\n',
        '- 外层\n  * 子层\n',
    ]
    parser = MarkdownIt('commonmark')
    for sample in samples:
        changed = apply_markdown_preferences(sample, prefs)
        assert parser.render(changed) == parser.render(sample)
        assert apply_markdown_preferences(changed, prefs) == changed


def test_markdown_toc_uses_unique_explicit_anchors_and_is_idempotent():
    from bs4 import BeautifulSoup

    from smart_reporting.preferences.markdown_adapter import append_signature

    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'}, 'md': {'toc': True}}), 'md')
    source = '# 报告\n\n## 收入 *概览*\n\n原值 1234.56。\n\n### 子项 [说明](https://example.invalid)\n\n## 收入 *概览*\n\n> ## 引用不进目录\n\n~~~text\n## 代码不进目录\n~~~\n'
    result = append_signature(source, prefs, '2026-11-12')
    soup = BeautifulSoup(MarkdownIt('commonmark', {'html': True}).render(result), 'html.parser')
    assert '<!-- report-md-toc:v1 -->' in result
    assert result.count('<!-- report-signature:v1 -->') == 1
    links = [link for link in soup.find_all('a') if link.get('href', '').startswith('#report-md-heading-')]
    assert len(links) == 3
    assert [link.get_text() for link in links] == ['收入 概览', '子项 说明', '收入 概览']
    targets = [link['href'][1:] for link in links]
    assert len(set(targets)) == 3
    assert all(len(soup.find_all(id=target)) == 1 for target in targets)
    assert '原值 1234.56。' in result and '## 代码不进目录' in result
    assert append_signature(result, prefs, '2026-11-12') == result
    prefs['toc'] = False
    without = append_signature(result, prefs, '2026-11-12')
    assert 'report-md-heading-' not in without and 'report-md-toc' not in without
    assert without == append_signature(source, prefs, '2026-11-12')


def test_pdf_word_projection_excludes_md_navigation_and_preserves_original_headings():
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'}, 'md': {'toc': True}}), 'md')
    result = assemble(prefs)
    assert 'report-md-toc:v1' in result.markdown
    projection = build_render_projection(result.markdown, [{'code': 'overview', 'title': '概览'}])
    assert 'report-md-toc' not in projection.markdown
    assert 'report-md-heading-' not in projection.markdown
    assert projection.markdown.count('概览') == build_render_projection(assemble().markdown, [{'code': 'overview', 'title': '概览'}]).markdown.count('概览')
    assert any(stage.name == 'format_navigation/1' for stage in projection.stages)
    assert verify_render_projection(projection.receipt, result.markdown.encode(), [{'code': 'overview', 'title': '概览'}])['status'] == 'verified'


def test_navigation_preserves_marker_examples_code_and_non_generated_html():
    from smart_reporting.preferences.markdown_adapter import append_signature, strip_navigation

    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'}, 'md': {'toc': True, 'codeFence': 'tildes'}}), 'md')
    example = '~~~text\n<!-- report-md-toc:v1 -->\n## 代码\n<!-- /report-md-toc:v1 -->\n~~~\n'
    source = '# 报告\n\n## 正文\n\n' + example + '\n<a id="report-md-heading-1"></a>\n'
    changed = append_signature(source, prefs, '2026-11-12')
    assert example in changed
    assert '<a id="report-md-heading-1"></a>' in changed
    assert '[正文](#report-md-heading-10)' in changed
    assert strip_navigation(changed).count('## 代码') == 1
    assert append_signature(changed, prefs, '2026-11-12') == changed
    unclosed = '<!-- report-md-toc:v1 -->\n用户未闭合内容\n'
    assert strip_navigation(unclosed) == unclosed
    assert strip_navigation('<!-- report-md-toc:v1 -->\n\n用户段落\n') == '<!-- report-md-toc:v1 -->\n\n用户段落\n'


def test_toc_without_title_and_empty_report_keep_original_body():
    from smart_reporting.preferences.markdown_adapter import append_signature

    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'}, 'md': {'toc': True}}), 'md')
    source = '开篇文字\n\n## 第一节\n\n正文。\n'
    result = append_signature(source, prefs, '2026-11-12')
    assert result.index('**目录**') < result.index('开篇文字')
    assert append_signature(result, prefs, '2026-11-12') == result
    assert 'report-md-toc' not in append_signature('只有正文。', prefs, '2026-11-12')


def test_toc_skipped_heading_levels_and_existing_anchor_names_remain_navigable():
    from bs4 import BeautifulSoup

    from smart_reporting.preferences.markdown_adapter import append_signature

    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'}, 'md': {'toc': True}}), 'md')
    source = '# 报告\n\n<a id="report-md-heading-1"></a>\n\n' + '\n\n'.join('###### 标题' + str(index) for index in range(12))
    result = append_signature(source, prefs, '2026-11-12')
    soup = BeautifulSoup(MarkdownIt('commonmark', {'html': True}).render(result), 'html.parser')
    links = [link for link in soup.find_all('a') if link.get('href', '').startswith('#report-md-heading-')]
    assert len(links) == 12
    assert all(len(soup.find_all(id=link['href'][1:])) == 1 for link in links)
    assert len({link['href'] for link in links}) == 12
    assert result == append_signature(result, prefs, '2026-11-12')
