"""Word表格全部单元格与文字对象参与维护字段回读，末对象不能漏检。"""

from copy import deepcopy

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.preferences.document_adapter import document_design
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.report_runtime.docx import _postprocess_docx
from smart_reporting.reporting.delivery.report_runtime.pdf import DEFAULT_PAGE_LAYOUT
from smart_reporting.reporting.tests.test_report_runtime import (
    _docx_postprocess_context,
    _docx_postprocess_fixture,
)

KIND = 'word_native_table_fields_v1'
FIELDS = {'tables.' + key for key in ('repeatHeader', 'splitRows', 'borders', 'striped')} | {
    'typography.table.' + key for key in ('font', 'size', 'color', 'bold', 'lineHeight', 'spaceBefore', 'spaceAfter', 'indent')}
MARKDOWN = '''| 业务（单位） | 数值 |
| --- | ---: |
| 单位甲 | 1234.5600 |
| 单位乙 | -234.56 |
| 单位丙 | 0 |
| 空值 |  |

| 第二表 | 数值 |
| --- | ---: |
| 尾项 | 1234.5600 |
'''
VALUES = [
    [['业务（单位）', '数值'], ['单位甲', '1234.5600'], ['单位乙', '-234.56'], ['单位丙', '0'], ['空值', '']],
    [['第二表', '数值'], ['尾项', '1234.5600']],
]


def native_case(tmp_path, alternate=False, *, prepare=None, values=VALUES, markdown=MARKDOWN):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '表格验证'}, 'word': {
        'cover': False, 'toc': False, 'tables': {'repeatHeader': alternate, 'splitRows': not alternate,
            'borders': 'all' if alternate else 'light', 'striped': not alternate},
        'typography': {'table': {'font': 'sans' if alternate else 'serif', 'size': 12, 'color': '#123456',
            'bold': not alternate, 'lineHeight': 1.25, 'spaceBefore': 2, 'spaceAfter': 3, 'indent': 6}}}}), 'word')
    document = _docx_postprocess_fixture(__import__('docx'))
    for grid in values:
        table = document.add_table(rows=len(grid), cols=len(grid[0]))
        for row, source in zip(table.rows, grid, strict=True):
            for cell, value in zip(row.cells, source, strict=True):
                cell.text = value
    if prepare:
        prepare(document)
    path = tmp_path / 'native.docx'
    document.save(path)
    _postprocess_docx(path, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT,
        include_cover=False, include_toc=False, design=document_design(prefs))
    return Document(path), prefs, {'markdown': markdown}


def read(document, prefs, frozen):
    from smart_reporting.management.preference_word_table_readback import read_word_tables

    checks = []

    def check(path, actual, expected, message='', **kwargs):
        checks.append({'path': path, 'actual': actual, 'expected': expected,
            'passed': actual == expected, 'message': message, **kwargs})

    summary = read_word_tables(document, prefs, frozen, check)
    return checks, summary


@pytest.mark.parametrize('alternate', [False, True])
def test_all_twelve_word_table_fields_cover_both_tables_and_empty_cells(tmp_path, alternate):
    doc, prefs, frozen = native_case(tmp_path, alternate)
    before = deepcopy(frozen)
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'passed' and summary['sourceTables'] == summary['nativeTables'] == 2
    assert summary['sourceCells'] == summary['checkedNativeCells'] == 14
    assert all(item['passed'] and item['coverage'] == 'complete' for item in checks)
    assert {item['path'] for item in checks if item['path'] in FIELDS} == FIELDS
    assert all(item['evidence_kind'] == KIND for item in checks)
    fonts = next(item for item in checks if item['path'] == 'typography.table.font')
    assert all(value == ['Noto Sans CJK SC' if alternate else 'Noto Serif CJK SC'] * 4 for value in fonts['actual'])
    assert frozen == before


@pytest.mark.parametrize('fault', [
    'late_size', 'late_font_cjk', 'late_color', 'late_bold', 'late_line', 'late_before', 'late_after',
    'late_indent', 'late_header', 'late_split', 'late_border', 'late_stripe', 'late_value',
    'missing_table', 'extra_table', 'hidden_character', 'revision', 'protected', 'nested_table', 'merged_cell',
])
def test_last_word_table_object_damage_cannot_be_masked_by_first_table(tmp_path, fault):
    from docx.enum.style import WD_STYLE_TYPE
    from docx.shared import Pt, RGBColor

    doc, prefs, frozen = native_case(tmp_path)
    table = doc.tables[-1]
    paragraph = table.cell(1, 1).paragraphs[-1]
    run = paragraph.runs[-1]
    if fault == 'late_size':
        run.font.size = Pt(9)
    elif fault == 'late_font_cjk':
        run._r.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), 'foreign')
    elif fault == 'late_color':
        run.font.color.rgb = RGBColor.from_string('ABCDEF')
    elif fault == 'late_bold':
        run.font.bold = False
    elif fault == 'late_line':
        paragraph.paragraph_format.line_spacing = 2
    elif fault == 'late_before':
        paragraph.paragraph_format.space_before = Pt(10)
    elif fault == 'late_after':
        paragraph.paragraph_format.space_after = Pt(10)
    elif fault == 'late_indent':
        paragraph.paragraph_format.first_line_indent = Pt(10)
    elif fault == 'late_header':
        table.rows[0]._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
    elif fault == 'late_split':
        table.rows[-1]._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
    elif fault == 'late_border':
        table._tbl.tblPr.find(qn('w:tblBorders')).find(qn('w:bottom')).set(qn('w:val'), 'nil')
    elif fault == 'late_stripe':
        shade = OxmlElement('w:shd')
        shade.set(qn('w:fill'), 'FF0000')
        table.cell(1, 1)._tc.get_or_add_tcPr().append(shade)
    elif fault == 'late_value':
        run.text = '1234.56'
    elif fault == 'missing_table':
        table._tbl.getparent().remove(table._tbl)
    elif fault == 'extra_table':
        doc.add_table(rows=1, cols=1).cell(0, 0).text = '未绑定'
    elif fault == 'hidden_character':
        style = doc.styles.add_style('隐藏末格', WD_STYLE_TYPE.CHARACTER)
        style.font.hidden = True
        run.style = style
    elif fault == 'revision':
        paragraph._p.get_or_add_pPr().append(OxmlElement('w:pPrChange'))
    elif fault == 'protected':
        protection = OxmlElement('w:documentProtection')
        protection.set(qn('w:enforcement'), 'true')
        doc.settings.element.append(protection)
    elif fault == 'nested_table':
        table.cell(1, 1).add_table(rows=1, cols=1)
    else:
        table.cell(1, 0).merge(table.cell(1, 1))
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'failed'
    assert any(not item['passed'] for item in checks)


def test_word_native_table_reader_accepts_controlled_html_but_not_changed_hidden_source(tmp_path):
    from smart_reporting.preferences.markdown_adapter import _tables

    doc, prefs, frozen = native_case(tmp_path)
    frozen['markdown'] = _tables(MARKDOWN, {'tableStyle': 'html'})
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'passed' and all(item['passed'] for item in checks)
    frozen['markdown'] = frozen['markdown'].replace('1234.5600', '9999.0000', 1)
    checks, summary = read(doc, prefs, frozen)
    assert summary['status'] == 'unverified'
    assert all(item.get('evidence_kind') is None for item in checks)


def test_empty_word_table_source_never_produces_complete_field_evidence():
    checks, summary = read(Document(), {}, {'markdown': '没有表格'})
    assert checks == [] and summary['status'] == 'not_exercised'
