"""模板表格中的显式总标题保留原生结构和独立可核验的内链。"""

from io import BytesIO

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm
from docx.text.paragraph import Paragraph

from smart_reporting.management.preference_template_readback import read_template_document
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.template_body_readback import read_template_body
from smart_reporting.reporting.delivery.templates import fill_report_template
from smart_reporting.reporting.tests.test_template_title_reuse import (
    BODY,
    TITLE,
    packed,
    source_template,
    title_paragraphs,
)


def table_template(placement):
    document = Document(BytesIO(source_template()))
    title, content = document.paragraphs[1]._p, document.paragraphs[2]._p
    table = document.add_table(rows=2, cols=2)
    table.style = 'Table Grid'
    table.autofit = False
    table.columns[0].width = Cm(6)
    table.columns[1].width = Cm(8)
    table.cell(0, 0).text = '封面编号 A-001'
    table.cell(0, 1).text = '复核说明保留'
    cell = table.cell(1, 0)
    if placement == 'merged':
        cell = cell.merge(table.cell(1, 1))
    elif placement == 'nested':
        cell = cell.add_table(rows=1, cols=1).cell(0, 0)
    document.element.body.replace(title, table._tbl)
    for paragraph in list(cell.paragraphs):
        cell._tc.remove(paragraph._p)
    cell._tc.append(title)
    if placement == 'same_cell':
        cell._tc.append(content)
    return packed(document)


def generate(original):
    return fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_title': TITLE, 'report_content': BODY},
        signature={'signer': '表格标题验收编制', 'date': '2026-11-13', 'description': ''})


def management_read(original, actual):
    resolved = resolve_format_preferences(FormatPreferences(common={
        'signer': '表格标题验收编制', 'dateFormat': 'iso'}), 'word')
    return read_template_document(actual, 'word', resolved,
        {'markdown': BODY, 'state': {'_documentContext': {'title': TITLE, 'generatedDate': '2026-11-13'}}}, original)


@pytest.fixture(scope='module')
def merged_title():
    original = table_template('merged')
    return original, generate(original).content


@pytest.mark.parametrize('placement', ['cell', 'merged', 'nested', 'same_cell'])
def test_native_table_title_reuses_template_layout_and_all_source_targets(placement):
    original = table_template(placement)
    filled = generate(original)
    assert filled.body_binding['status'] == 'projected' and not filled.issues
    titles = title_paragraphs(filled.content)
    assert len(titles) == 2, '模板总标题一次，后续同名业务H1一次'
    document = Document(BytesIO(filled.content))
    title = Paragraph(titles[0], document)
    assert title.text == TITLE and title.paragraph_format.space_after.pt == 14
    assert all(run.bold and run.font.size.pt == 23 for run in title.runs)
    receipt = read_template_body(filled.content, BODY, {}, original=original, report_title=TITLE)
    assert receipt['status'] == 'passed' and receipt['scope']['titleReused'] is True
    assert len(receipt['scope']['titleParagraphPath']) > 1
    targets = receipt['scope']['internalLinkTargets']
    assert [item['targetText'] for item in targets] == [TITLE, '收支分析', TITLE]
    assert len({item['actualBookmark'] for item in targets}) == 3
    complete = management_read(original, filled.content)
    assert complete['status'] == 'passed'
    assert complete['templateReadback']['outsideDeclaredTargets']['status'] == 'passed'
    assert '封面编号 A-001' in ''.join(document.element.body.xpath('.//w:t/text()'))
    assert '复核说明保留' in ''.join(document.element.body.xpath('.//w:t/text()'))


@pytest.mark.parametrize('fault', [
    'table_style_hidden', 'conditional_table_style_hidden', 'deleted_row', 'revised_cell',
    'cellDel', 'cellIns', 'cellMerge', 'pPrChange', 'paragraph_mark_deleted',
    'vMerge_continue', 'vMerge_default', 'hMerge_continue', 'tblGridChange',
    'tblPrExChange',
    'locked_ancestor', 'dynamic_field', 'protected', 'after_body',
])
def test_unsafe_table_title_preserves_visible_source_h1(fault):
    document = Document(BytesIO(table_template('merged')))
    table = document.tables[0]
    title = table.cell(1, 0).paragraphs[0]._p
    if fault in {'table_style_hidden', 'conditional_table_style_hidden'}:
        style = document.styles['Table Grid'].element
        parent = style
        if fault == 'conditional_table_style_hidden':
            parent = OxmlElement('w:tblStylePr')
            parent.set(qn('w:type'), 'lastRow')
            style.append(parent)
        properties = OxmlElement('w:rPr')
        properties.append(OxmlElement('w:vanish'))
        parent.append(properties)
    elif fault == 'deleted_row':
        table.rows[1]._tr.get_or_add_trPr().append(OxmlElement('w:del'))
    elif fault == 'revised_cell':
        table.cell(1, 0)._tc.get_or_add_tcPr().append(OxmlElement('w:tcPrChange'))
    elif fault in {'cellDel', 'cellIns', 'cellMerge'}:
        table.cell(1, 0)._tc.get_or_add_tcPr().append(OxmlElement('w:' + fault))
    elif fault == 'pPrChange':
        change = OxmlElement('w:pPrChange')
        change.append(OxmlElement('w:pPr'))
        title.get_or_add_pPr().append(change)
    elif fault == 'paragraph_mark_deleted':
        properties = OxmlElement('w:rPr')
        properties.append(OxmlElement('w:del'))
        title.get_or_add_pPr().append(properties)
    elif fault == 'tblGridChange':
        table._tbl.tblGrid.append(OxmlElement('w:tblGridChange'))
    elif fault == 'tblPrExChange':
        properties, change = OxmlElement('w:tblPrEx'), OxmlElement('w:tblPrExChange')
        change.append(OxmlElement('w:tblPrEx'))
        properties.append(change)
        table.rows[1]._tr.insert(0, properties)
    elif fault in {'vMerge_continue', 'vMerge_default', 'hMerge_continue'}:
        merge = OxmlElement('w:' + fault.split('_')[0])
        if fault != 'vMerge_default':
            merge.set(qn('w:val'), 'continue')
        table.cell(1, 0)._tc.get_or_add_tcPr().append(merge)
    elif fault == 'locked_ancestor':
        control, props, lock, content = [OxmlElement(name) for name in (
            'w:sdt', 'w:sdtPr', 'w:lock', 'w:sdtContent')]
        lock.set(qn('w:val'), 'sdtContentLocked')
        props.append(lock)
        control.extend((props, content))
        table._tbl.getparent().replace(table._tbl, control)
        content.append(table._tbl)
    elif fault == 'dynamic_field':
        field = OxmlElement('w:fldSimple')
        field.set(qn('w:instr'), 'DATE')
        title.append(field)
    elif fault == 'protected':
        protection = OxmlElement('w:documentProtection')
        protection.set(qn('w:edit'), 'readOnly')
        protection.set(qn('w:enforcement'), '1')
        document.settings.element.append(protection)
    else:
        document.paragraphs[1]._p.addnext(table._tbl)
    original = packed(document)
    filled = generate(original)
    assert filled.body_binding['status'] == 'projected'
    assert filled.body_binding['titleReused'] is False
    actual = Document(BytesIO(filled.content))
    slot = actual.element.body.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]/w:sdtContent')[0]
    first = next(node for node in slot if node.tag == qn('w:p'))
    assert ''.join(node.text or '' for node in first.iter(qn('w:t'))) == TITLE


@pytest.mark.parametrize('fault', [
    'moved_title', 'removed_title', 'missing_endpoint', 'table_style_hidden', 'same_text_link_reroute',
])
def test_independent_reader_rejects_corrupted_table_title(merged_title, fault):
    original, actual = merged_title
    document = Document(BytesIO(actual))
    title = document.tables[0].cell(1, 0).paragraphs[0]._p
    if fault == 'moved_title':
        document.tables[0].cell(0, 0)._tc.append(title)
    elif fault == 'removed_title':
        title.getparent().remove(title)
    elif fault == 'missing_endpoint':
        title.remove(title.find(qn('w:bookmarkEnd')))
    elif fault == 'table_style_hidden':
        properties = OxmlElement('w:rPr')
        properties.append(OxmlElement('w:vanish'))
        document.styles['Table Grid'].element.append(properties)
    else:
        links = document.element.body.xpath('.//w:hyperlink')
        links[0].set(qn('w:anchor'), links[-1].get(qn('w:anchor')))
    actual = packed(document)
    assert read_template_body(actual, BODY, {}, original=original, report_title=TITLE)['status'] != 'passed'
    assert management_read(original, actual)['status'] != 'passed'


@pytest.mark.parametrize('fault', ['business_text', 'grid', 'merge', 'cell_width'])
def test_outside_comparison_preserves_every_table_property(merged_title, fault):
    original, actual = merged_title
    document = Document(BytesIO(actual))
    table = document.tables[0]
    if fault == 'business_text':
        table.cell(0, 0).text = '封面编号被篡改'
    elif fault == 'grid':
        table._tbl.tblGrid[0].set(qn('w:w'), '200')
    elif fault == 'merge':
        properties = table.cell(1, 0)._tc.tcPr
        properties.remove(properties.find(qn('w:gridSpan')))
    else:
        table.cell(0, 0)._tc.tcPr.find(qn('w:tcW')).set(qn('w:w'), '200')
    receipt = management_read(original, packed(document))
    assert receipt['status'] != 'passed'
    assert receipt['templateReadback']['outsideDeclaredTargets']['status'] != 'passed'


@pytest.mark.parametrize('revision', [
    'cellDel', 'cellIns', 'cellMerge', 'pPrChange', 'paragraph_mark_deleted', 'tblGridChange', 'tblPrExChange',
])
def test_independent_reader_rejects_matching_revised_original_and_actual(merged_title, revision):
    original, actual = merged_title
    revised = []
    for raw in (original, actual):
        document = Document(BytesIO(raw))
        cell = document.tables[0].cell(1, 0)
        if revision in {'cellDel', 'cellIns', 'cellMerge'}:
            cell._tc.get_or_add_tcPr().append(OxmlElement('w:' + revision))
        elif revision == 'tblGridChange':
            document.tables[0]._tbl.tblGrid.append(OxmlElement('w:tblGridChange'))
        elif revision == 'tblPrExChange':
            properties, change = OxmlElement('w:tblPrEx'), OxmlElement('w:tblPrExChange')
            change.append(OxmlElement('w:tblPrEx'))
            properties.append(change)
            cell._tc.getparent().insert(0, properties)
        elif revision == 'pPrChange':
            change = OxmlElement('w:pPrChange')
            change.append(OxmlElement('w:pPr'))
            cell.paragraphs[0]._p.get_or_add_pPr().append(change)
        else:
            properties = OxmlElement('w:rPr')
            properties.append(OxmlElement('w:del'))
            cell.paragraphs[0]._p.get_or_add_pPr().append(properties)
        revised.append(packed(document))
    assert read_template_body(revised[1], BODY, {}, original=revised[0], report_title=TITLE)['status'] != 'passed'
    assert management_read(*revised)['status'] != 'passed'


@pytest.mark.parametrize('merge', ['vMerge', 'hMerge'])
def test_visible_merge_restart_title_remains_supported(merge):
    document = Document(BytesIO(table_template('merged')))
    marker = OxmlElement('w:' + merge)
    marker.set(qn('w:val'), 'restart')
    document.tables[0].cell(1, 0)._tc.get_or_add_tcPr().append(marker)
    original = packed(document)
    filled = generate(original)
    assert filled.body_binding['titleReused'] is True
    assert management_read(original, filled.content)['status'] == 'passed'


@pytest.mark.parametrize('placement', ['merged', 'nested', 'same_cell'])
def test_table_title_pdf_keeps_three_distinct_source_heading_links(placement):
    import pymupdf as fitz

    from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf

    filled = generate(table_template(placement))
    pdf = libreoffice_to_pdf(filled.content, suffix='.docx', timeout=120)
    with fitz.open(stream=pdf, filetype='pdf') as document:
        links = [(page.get_textbox(link['from']).strip(' ，。\n'), link) for page in document for link in page.get_links()]
        assert {label for label, _ in links} == {'返回总标题', '前往业务节', '前往后续同名标题'}
        assert all(link['kind'] == fitz.LINK_GOTO for _, link in links)
        assert len({(link['page'], link['to'].x, link['to'].y) for _, link in links}) == 3


@pytest.mark.parametrize('merge', ['vMerge', 'hMerge'])
def test_independent_reader_rejects_hidden_merge_continuation_in_original_and_actual(merged_title, merge):
    original, actual = merged_title
    revised = []
    for raw in (original, actual):
        document = Document(BytesIO(raw))
        cell = document.tables[0].cell(1, 0)
        cell._tc.get_or_add_tcPr().append(OxmlElement('w:' + merge))
        revised.append(packed(document))
    assert read_template_body(revised[1], BODY, {}, original=revised[0], report_title=TITLE)['status'] != 'passed'
    assert management_read(*revised)['status'] != 'passed'
