"""总标题复用模板声明位置，正文和内部链接保持独立可核验。"""

from io import BytesIO

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from smart_reporting.reporting.delivery.template_body_readback import read_template_body
from smart_reporting.reporting.delivery.templates import fill_report_template

TITLE = '月度核对'
BODY = ('# 月度核对\n\n## 收支分析\n\n业务原值 1234.56，业务名称月度核对保持。\n\n'
    '[返回总标题](#月度核对)，[前往业务节](#收支分析)。\n\n'
    '# 月度核对\n\n后续同名业务标题保持。\n\n[前往后续同名标题](#月度核对-1)')


def packed(document):
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def source_template(*, title_text='{{report_title}}', title_after=False):
    document = Document()
    document.add_paragraph('模板业务引用：月度核对，不删除。')
    if title_after:
        document.add_paragraph('{{report_content}}')
    title = document.add_paragraph()
    title.paragraph_format.space_after = Pt(14)
    title.add_run(title_text[:10]).bold = True
    title.add_run(title_text[10:]).bold = True
    for run in title.runs:
        run.font.size = Pt(23)
    if not title_after:
        document.add_paragraph('{{report_content}}')
    control, properties, tag, content = [OxmlElement(name) for name in (
        'w:sdt', 'w:sdtPr', 'w:tag', 'w:sdtContent')]
    tag.set(qn('w:val'), 'report_signature')
    properties.append(tag)
    control.extend((properties, content))
    for sample in ('样例署名', '2000-01-01'):
        p, r, t = [OxmlElement(name) for name in ('w:p', 'w:r', 'w:t')]
        t.text = sample
        r.append(t)
        p.append(r)
        content.append(p)
    document.element.body.insert(len(document.element.body) - 1, control)
    document.add_paragraph('末尾模板业务不变。')
    return packed(document)


@pytest.fixture(scope='module')
def actual_title_reuse():
    original = source_template()
    result = fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_title': TITLE, 'report_content': BODY},
        signature={'signer': '标题复用验收编制', 'date': '2026-11-13'})
    assert result.body_binding['status'] == 'projected' and not result.issues
    return original, result


def title_paragraphs(content):
    document = Document(BytesIO(content))
    return [p for p in document.element.body.xpath('.//w:p')
        if ''.join(p.xpath('.//w:t/text()')) == TITLE]


def test_declared_title_reuses_first_h1_and_preserves_later_same_title(actual_title_reuse):
    _, filled = actual_title_reuse
    titles = title_paragraphs(filled.content)
    assert len(titles) == 2
    document = Document(BytesIO(filled.content))
    title = document.paragraphs[1]
    assert title.text == TITLE and title.runs[0].bold is True
    assert title.runs[0].font.size.pt == 23 and title.paragraph_format.space_after.pt == 14
    assert '模板业务引用：月度核对，不删除。' == document.paragraphs[0].text
    assert '末尾模板业务不变。' == document.paragraphs[-1].text


def test_title_links_and_full_source_are_independently_verified(actual_title_reuse):
    original, filled = actual_title_reuse
    receipt = read_template_body(filled.content, BODY, {}, original=original, report_title=TITLE)
    assert receipt['status'] == 'passed' and receipt['coverage'] == 'complete'
    assert receipt['scope']['titleReused'] is True
    targets = receipt['scope']['internalLinkTargets']
    assert [item['targetText'] for item in targets] == [TITLE, '收支分析', TITLE]
    assert len({item['actualBookmark'] for item in targets}) == 3
    assert targets[0]['targetBlock'] == 0


def test_management_reader_preserves_all_outside_parts_and_declared_signature(actual_title_reuse):
    from smart_reporting.management.preference_template_readback import read_template_document
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences

    original, filled = actual_title_reuse
    resolved = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '标题复用验收编制', 'dateFormat': 'iso'}}), 'word')
    receipt = read_template_document(filled.content, 'word', resolved,
        {'markdown': BODY, 'state': {'_documentContext': {'title': TITLE, 'generatedDate': '2026-11-13'}}}, original)
    assert receipt['templateReadback']['body']['status'] == 'passed'
    assert receipt['templateReadback']['outsideDeclaredTargets']['status'] == 'passed'
    assert receipt['templateReadback']['signature']['status'] == 'passed'


@pytest.mark.parametrize('markdown', ['# 月度核对', '# **月度**`核对`\n\n保留正文。'])
def test_title_only_and_formatted_leading_h1_keep_one_template_title(markdown):
    original = source_template()
    filled = fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_title': TITLE, 'report_content': markdown})
    assert filled.body_binding['status'] == 'projected'
    assert len(title_paragraphs(filled.content)) == 1
    receipt = read_template_body(filled.content, markdown, {}, original=original, report_title=TITLE)
    assert receipt['status'] == 'passed' and receipt['scope']['titleReused'] is True


@pytest.fixture(scope='module')
def unlinked_title_reuse():
    original = source_template()
    markdown = '# 月度核对\n\n保留正文。'
    filled = fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_title': TITLE, 'report_content': markdown},
        signature={'signer': '标题复用验收编制', 'date': '2026-11-13', 'description': ''})
    assert filled.body_binding['titleReused'] is True
    return original, filled.content, markdown


@pytest.mark.parametrize('fault', ['missing_bookmarks', 'spec_hidden', 'protected_original',
    'empty_bookmark_identity', 'pair_before_text'])
def test_unlinked_reused_title_requires_visible_unprotected_original_and_native_pair(unlinked_title_reuse, fault):
    from smart_reporting.management.preference_template_readback import read_template_document
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences

    original, actual, markdown = unlinked_title_reuse
    resolved = resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '标题复用验收编制', 'dateFormat': 'iso'}}), 'word')
    frozen = {'markdown': markdown,
        'state': {'_documentContext': {'title': TITLE, 'generatedDate': '2026-11-13'}}}
    assert read_template_document(actual, 'word', resolved, frozen, original)['status'] == 'passed'
    document = Document(BytesIO(actual))
    title = document.paragraphs[1]
    if fault == 'missing_bookmarks':
        for node in title._p.xpath('./w:bookmarkStart|./w:bookmarkEnd'):
            title._p.remove(node)
    elif fault in ('empty_bookmark_identity', 'pair_before_text'):
        start = title._p.xpath('./w:bookmarkStart')[0]
        end = title._p.xpath('./w:bookmarkEnd')[0]
        if fault == 'empty_bookmark_identity':
            for node in (start, end):
                node.set(qn('w:id'), '')
            start.set(qn('w:name'), '')
        else:
            title._p.remove(end)
            start.addnext(end)
    elif fault == 'spec_hidden':
        template = Document(BytesIO(original))
        for candidate in (template.paragraphs[1], title):
            for run in candidate.runs:
                run._r.get_or_add_rPr().append(OxmlElement('w:specVanish'))
        original = packed(template)
    else:
        template = Document(BytesIO(original))
        for candidate in (template, document):
            protected = OxmlElement('w:documentProtection')
            protected.set(qn('w:edit'), 'readOnly')
            protected.set(qn('w:enforcement'), '1')
            candidate.settings.element.append(protected)
        original = packed(template)
    actual = packed(document)
    receipt = read_template_body(actual, markdown, {}, original=original, report_title=TITLE)
    assert receipt['status'] != 'passed'
    assert read_template_document(actual, 'word', resolved, frozen, original)['status'] != 'passed'


@pytest.mark.parametrize('fault', ['missing_title', 'title_text', 'wrong_title_target', 'title_hidden', 'bookmark_end'])
def test_corrupted_reused_title_never_passes_native_readback(actual_title_reuse, fault):
    original, filled = actual_title_reuse
    document = Document(BytesIO(filled.content))
    title = document.paragraphs[1]
    if fault == 'missing_title':
        title._p.getparent().remove(title._p)
    elif fault == 'title_text':
        title.runs[0].text = '被篡改的标题'
    elif fault == 'title_hidden':
        title.runs[0].font.hidden = True
    elif fault == 'bookmark_end':
        end = title._p.xpath('./w:bookmarkEnd')[0]
        title._p.remove(end)
        title._p.insert(0, end)
    else:
        anchor = document.element.body.xpath('.//w:hyperlink')[-1].get(qn('w:anchor'))
        document.element.body.xpath('.//w:hyperlink')[0].set(qn('w:anchor'), anchor)
    result = read_template_body(packed(document), BODY, {}, original=original, report_title=TITLE)
    assert result['status'] != 'passed'


@pytest.mark.parametrize('case', ['different', 'no_declaration', 'after_body', 'not_first', 'h2'])
def test_only_matching_first_h1_and_preceding_explicit_title_are_reused(case):
    original = source_template(title_text='固定业务标题' if case == 'no_declaration' else '{{report_title}}',
        title_after=case == 'after_body')
    markdown = BODY
    if case == 'different':
        markdown = markdown.replace('# 月度核对', '# 不同业务标题', 1)
        markdown = markdown.replace('](#月度核对)', '](#不同业务标题)').replace('](#月度核对-1)', '](#月度核对)')
    elif case == 'not_first':
        markdown = '业务引言保持。\n\n' + markdown
    elif case == 'h2':
        markdown = '#' + markdown
    filled = fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_title': TITLE, 'report_content': markdown})
    assert filled.body_binding['status'] == 'projected'
    receipt = read_template_body(filled.content, markdown, {}, original=original, report_title=TITLE)
    assert receipt['status'] == 'passed'
    assert receipt['scope'].get('titleReused') is not True


@pytest.mark.parametrize('kind', ['direct', 'paragraph_style', 'character_style', 'default_style'])
def test_hidden_title_declaration_does_not_remove_visible_source_title(kind):
    from docx.enum.style import WD_STYLE_TYPE

    document = Document(BytesIO(source_template()))
    title = document.paragraphs[1]
    if kind == 'direct':
        for run in title.runs:
            run.font.hidden = True
    elif kind == 'default_style':
        document.styles['Normal'].font.hidden = True
        # 明确可见的正文样式不受这个模板缺陷影响。
        document.styles['Heading 1'].font.hidden = False
        document.styles['Heading 2'].font.hidden = False
    else:
        style = document.styles.add_style('隐形标题', WD_STYLE_TYPE.PARAGRAPH if kind == 'paragraph_style'
            else WD_STYLE_TYPE.CHARACTER)
        style.font.hidden = True
        if kind == 'paragraph_style':
            title.style = style
        else:
            for run in title.runs:
                run.style = style
    original = packed(document)
    filled = fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_title': TITLE, 'report_content': BODY})
    assert filled.body_binding['status'] == 'projected'
    assert filled.body_binding['titleReused'] is False
    actual = Document(BytesIO(filled.content))
    body = actual.element.body.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]/w:sdtContent')[0]
    assert ''.join(body.xpath('./w:p[1]//w:t/text()', namespaces={
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})) == TITLE


@pytest.mark.parametrize('placement', ['sdt', 'table'])
def test_reused_title_supports_existing_native_body_slot_types(placement):
    document = Document(BytesIO(source_template()))
    target = document.paragraphs[2]._p
    if placement == 'table':
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).paragraphs[0]._p.addnext(target)
        document.element.body.insert(2, table._tbl)
    else:
        control, properties, tag, content = [OxmlElement(name) for name in (
            'w:sdt', 'w:sdtPr', 'w:tag', 'w:sdtContent')]
        tag.set(qn('w:val'), 'report_content')
        properties.append(tag)
        control.extend((properties, content))
        target.addprevious(control)
        content.append(target)
    original = packed(document)
    filled = fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_title': TITLE, 'report_content': BODY})
    assert filled.body_binding['titleReused'] is True
    assert len(title_paragraphs(filled.content)) == 2
    assert read_template_body(filled.content, BODY, {}, original=original, report_title=TITLE)['status'] == 'passed'
