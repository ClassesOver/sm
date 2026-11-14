"""表格原生布尔、超链接文字、覆盖属性和来源展示变换的边界。"""

from copy import deepcopy
from io import BytesIO

import pytest
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.tests.test_preference_word_table_readback import (
    FIELDS,
    KIND,
    MARKDOWN,
    VALUES,
    native_case,
    read,
)


@pytest.mark.parametrize('alternate', [False, True])
def test_explicit_false_row_properties_are_read_as_false_not_presence(tmp_path, alternate):
    doc, prefs, frozen = native_case(tmp_path, alternate)
    for table in doc.tables:
        for row in table.rows:
            properties = row._tr.get_or_add_trPr()
            for key in ('tblHeader', 'cantSplit'):
                for node in properties.findall(qn('w:' + key)):
                    properties.remove(node)
                node = OxmlElement('w:' + key)
                node.set(qn('w:val'), 'false')
                properties.append(node)
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == ('failed' if alternate else 'passed')
    assert all(item['passed'] for item in checks) is (not alternate)


@pytest.mark.parametrize('fault', ['body_header', 'cell_border', 'row_border', 'missing_stripe',
    'duplicate_shade', 'theme_border', 'conditional_shade', 'missing_bold', 'extra_wrapped_row'])
def test_late_overrides_and_missing_direct_properties_prevent_complete_proof(tmp_path, fault):
    doc, prefs, frozen = native_case(tmp_path, alternate=True if fault == 'missing_bold' else False)
    table = doc.tables[0]
    cell = table.cell(4, 1)
    if fault == 'body_header':
        table.rows[-1]._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
    elif fault in ('cell_border', 'row_border'):
        if fault == 'cell_border':
            properties, name = cell._tc.get_or_add_tcPr(), 'tcBorders'
        else:
            properties = OxmlElement('w:tblPrEx')
            table.rows[-1]._tr.insert(0, properties)
            name = 'tblBorders'
        borders = OxmlElement('w:' + name)
        edge = OxmlElement('w:bottom')
        edge.set(qn('w:val'), 'double')
        borders.append(edge)
        properties.append(borders)
    elif fault == 'missing_stripe':
        properties = cell._tc.get_or_add_tcPr()
        properties.remove(properties.find(qn('w:shd')))
    elif fault == 'duplicate_shade':
        table.cell(0, 0)._tc.get_or_add_tcPr().append(OxmlElement('w:shd'))
    elif fault == 'theme_border':
        edge = table._tbl.tblPr.find(qn('w:tblBorders')).find(qn('w:bottom'))
        edge.set(qn('w:themeColor'), 'accent1')
    elif fault == 'conditional_shade':
        style = doc.styles['Table Grid']._element
        condition = OxmlElement('w:tblStylePr')
        condition.set(qn('w:type'), 'band1Horz')
        properties = OxmlElement('w:tcPr')
        shade = OxmlElement('w:shd')
        shade.set(qn('w:fill'), 'FF0000')
        properties.append(shade)
        condition.append(properties)
        style.append(condition)
    elif fault == 'missing_bold':
        run = cell.paragraphs[0].runs[0]
        run._r.rPr.remove(run._r.rPr.find(qn('w:b')))
        doc.styles['Normal'].font.bold = True
    else:
        wrapper = OxmlElement('w:sdt')
        content = OxmlElement('w:sdtContent')
        content.append(deepcopy(table.rows[-1]._tr))
        wrapper.append(content)
        table._tbl.append(wrapper)
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'failed'
    assert any(item['passed'] is False for item in checks)


def _wrap_run(paragraph):
    run = paragraph._p.findall(qn('w:r'))[-1]
    link = OxmlElement('w:hyperlink')
    link.set(qn('w:anchor'), 'existing-target')
    run.addprevious(link)
    link.append(run)
    return run


@pytest.mark.parametrize('fault', ['none', 'size', 'hidden'])
def test_all_hyperlink_runs_participate_in_reader_and_consumer(tmp_path, fault):
    def prepare(doc):
        run = _wrap_run(doc.tables[-1].cell(1, 1).paragraphs[0])
        run.get_or_add_rPr().get_or_add_sz().val = 16
    doc, prefs, frozen = native_case(tmp_path, prepare=prepare)
    run = doc.tables[-1].cell(1, 1)._tc.xpath('.//w:hyperlink/w:r')[0]
    if fault == 'size':
        run.rPr.get_or_add_sz().val = 16
    elif fault == 'hidden':
        run.rPr.append(OxmlElement('w:vanish'))
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == ('passed' if fault == 'none' else 'failed')
    assert all(item['passed'] for item in checks) is (fault == 'none')


def test_empty_paragraph_receives_explicit_table_font_for_future_input(tmp_path):
    def prepare(doc):
        paragraph = doc.tables[0].cell(4, 1).paragraphs[0]
        for run in paragraph._p.findall(qn('w:r')):
            paragraph._p.remove(run)
    doc, prefs, frozen = native_case(tmp_path, prepare=prepare)
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'passed' and all(item['passed'] for item in checks)


def test_linked_header_unit_break_preserves_text_and_hyperlink(tmp_path):
    def prepare(doc):
        paragraph = doc.tables[0].cell(0, 0).paragraphs[0]
        paragraph.text = '业务'
        paragraph.add_run('（单位）')
        _wrap_run(paragraph)
    doc, prefs, frozen = native_case(tmp_path, prepare=prepare)
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'passed' and all(item['passed'] for item in checks)
    paragraph = doc.tables[0].cell(0, 0).paragraphs[0]
    assert paragraph.text == '业务\n（单位）'
    assert paragraph._p.xpath('.//w:hyperlink/w:r/w:t')[0].text == '（单位）'


def test_numeric_header_units_preserve_precision_and_only_remove_matching_unit(tmp_path):
    values = deepcopy(VALUES)
    values[-1] = [['收入（元）', '余值'], ['1234.5600', '-234.56元']]
    markdown = MARKDOWN[:MARKDOWN.index('| 第二表')] + '| 收入（元） | 余值 |\n| ---: | --- |\n| 1234.5600元 | -234.56元 |\n'
    doc, prefs, frozen = native_case(tmp_path, values=values, markdown=markdown)
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'passed' and all(item['passed'] for item in checks)


def test_registered_eight_month_table_is_independently_transposed_in_six_period_groups(tmp_path):
    markdown = '[[table:monthly]]\n| | 收入（元） |\n| --- | ---: |\n' + ''.join(
        f'| 2026年{month}月 | {month}.5600 |\n' for month in range(1, 9)) + '[[/table:monthly]]\n'
    values = [[['2026年', '1月', '2月', '3月', '4月', '5月', '6月'],
        ['收入（元）', '1.5600', '2.5600', '3.5600', '4.5600', '5.5600', '6.5600']],
        [['2026年', '7月', '8月'], ['收入（元）', '7.5600', '8.5600']]]
    doc, prefs, frozen = native_case(tmp_path, values=values, markdown=markdown)
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'passed' and all(item['passed'] for item in checks)
    assert summary['sourceTables'] == 1 and summary['nativeTables'] == 2
    assert summary['sourceCells'] == 18 and summary['checkedNativeCells'] == 20


def test_public_word_readback_wires_all_fields_and_preserves_caption_summary(tmp_path):
    from smart_reporting.management.preference_preflight_readback import readback
    from smart_reporting.reporting.tests.test_report_runtime import _docx_postprocess_context

    doc, prefs, frozen = native_case(tmp_path)
    frozen['state'] = {'_documentContext': _docx_postprocess_context()}
    frozen['markdownPath'] = 'report.md'
    stream = BytesIO()
    doc.save(stream)
    result = readback(stream.getvalue(), 'word', prefs, frozen)
    checks = [item for item in result['checks'] if item['path'] in {'word.' + path for path in FIELDS}]
    assert len(checks) == 12
    assert all(item['evidenceKind'] == KIND and item['coverage'] == 'complete' for item in checks)
    assert result['tableReadback']['status'] == 'passed'
    assert result['tableCaptionReadback']['status'] == 'not_exercised'


@pytest.mark.parametrize('fault', ['default_table_shade', 'table_shade', 'inherited_complex_script',
    'wrapped_dynamic_field', 'run_shade', 'empty_unknown_style', 'table_complex_script',
    'inherited_auto_spacing', 'empty_hidden_style'])
def test_default_styles_inherited_script_and_nested_dynamic_content_do_not_self_certify(tmp_path, fault):
    from docx.enum.style import WD_STYLE_TYPE

    doc, prefs, frozen = native_case(tmp_path)
    table = doc.tables[-1]
    paragraph = table.cell(1, 1).paragraphs[0]
    run = paragraph.runs[0]
    if fault in ('default_table_shade', 'table_shade', 'run_shade'):
        shade = OxmlElement('w:shd')
        shade.set(qn('w:fill'), 'FF0000')
        if fault == 'default_table_shade':
            for item in doc.tables:
                item._tbl.tblPr.remove(item._tbl.tblPr.find(qn('w:tblStyle')))
            properties = OxmlElement('w:tcPr')
            doc.styles['Normal Table']._element.append(properties)
        elif fault == 'table_shade':
            properties = table._tbl.tblPr
        else:
            properties = run._r.get_or_add_rPr()
        properties.append(shade)
    elif fault == 'inherited_complex_script':
        style = doc.styles.add_style('末格复杂脚本', WD_STYLE_TYPE.CHARACTER)
        properties = style._element.get_or_add_rPr()
        properties.append(OxmlElement('w:cs'))
        size = OxmlElement('w:szCs')
        size.set(qn('w:val'), '60')
        properties.append(size)
        run.style = style
    elif fault in ('table_complex_script', 'inherited_auto_spacing', 'empty_hidden_style'):
        if fault == 'table_complex_script':
            properties = doc.styles['Table Grid']._element.get_or_add_rPr()
            properties.append(OxmlElement('w:cs'))
            size = OxmlElement('w:szCs')
            size.set(qn('w:val'), '60')
            properties.append(size)
        elif fault == 'inherited_auto_spacing':
            style = doc.styles.add_style('末格自动间距', WD_STYLE_TYPE.PARAGRAPH)
            spacing = OxmlElement('w:spacing')
            spacing.set(qn('w:beforeAutospacing'), '1')
            style._element.get_or_add_pPr().append(spacing)
            paragraph.style = style
        else:
            style = doc.styles.add_style('隐藏空格', WD_STYLE_TYPE.CHARACTER)
            style.font.hidden = True
            doc.tables[0].cell(4, 1).paragraphs[0].runs[0].style = style
    elif fault == 'empty_unknown_style':
        empty = doc.tables[0].cell(4, 1).paragraphs[0].runs[0]
        style = OxmlElement('w:rStyle')
        style.set(qn('w:val'), 'missing-empty-style')
        empty._r.get_or_add_rPr().append(style)
    else:
        native_run = _wrap_run(paragraph)
        field = OxmlElement('w:fldSimple')
        field.set(qn('w:instr'), 'DATE')
        native_run.addprevious(field)
        field.append(native_run)
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'failed'
    assert any(item['passed'] is False for item in checks)


def test_header_unit_break_counts_native_tabs_without_moving_parentheses():
    from docx import Document

    from smart_reporting.reporting.delivery.report_runtime.docx import _break_before_header_unit

    cell = Document().add_table(rows=1, cols=1).cell(0, 0)
    cell.text = '业务\t名称（单位）'
    _break_before_header_unit(cell)
    assert cell.text == '业务\t名称\n（单位）'


def test_pandoc_table_style_with_missing_base_and_conditional_border_gets_safe_native_style(tmp_path):
    from docx.enum.style import WD_STYLE_TYPE

    def prepare(doc):
        for name in ('Table Grid', 'Normal Table'):
            element = doc.styles[name]._element
            element.getparent().remove(element)
        style = doc.styles.add_style('Pandoc Table', WD_STYLE_TYPE.TABLE)
        base = OxmlElement('w:basedOn')
        base.set(qn('w:val'), 'TableNormal')
        style._element.append(base)
        condition = OxmlElement('w:tblStylePr')
        condition.set(qn('w:type'), 'firstRow')
        properties = OxmlElement('w:tcPr')
        borders = OxmlElement('w:tcBorders')
        border = OxmlElement('w:bottom')
        border.set(qn('w:val'), 'single')
        borders.append(border)
        properties.append(borders)
        condition.append(properties)
        style._element.append(condition)
        for table in doc.tables:
            table.style = style
    doc, prefs, frozen = native_case(tmp_path, prepare=prepare)
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'passed' and all(item['passed'] for item in checks)
    assert all(table.style.base_style is None for table in doc.tables)


def test_blank_table_style_base_is_not_treated_as_a_valid_end_of_inheritance(tmp_path):
    doc, prefs, frozen = native_case(tmp_path)
    base = doc.styles['Table Grid']._element.find(qn('w:basedOn'))
    base.attrib.pop(qn('w:val'))
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'failed' and any(item['passed'] is False for item in checks)
