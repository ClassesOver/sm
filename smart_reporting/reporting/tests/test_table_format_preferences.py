"""表格偏好必须控制原生 Word 属性及 PDF 实际分页。"""
from io import BytesIO

import pytest
from docx import Document
from docx.oxml.ns import qn
from pypdf import PdfReader
from weasyprint import HTML

from smart_reporting.preferences.document_adapter import document_design
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.report_design import ReportDesign
from smart_reporting.reporting.delivery.report_runtime.design import design_css
from smart_reporting.reporting.delivery.report_runtime.docx import _postprocess_docx
from smart_reporting.reporting.delivery.report_runtime.markdown import _semantic_documents
from smart_reporting.reporting.delivery.report_runtime.pdf import DEFAULT_PAGE_LAYOUT

from .test_report_runtime import _docx_postprocess_context, _docx_postprocess_fixture


def table_design(format, **tables):
    return document_design(resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '表格验证'}, format: {'tables': tables, 'cover': False, 'toc': False}}), format))


@pytest.mark.parametrize('repeat,split,borders,striped', [(False, True, 'none', False), (True, False, 'light', True), (True, False, 'all', False)])
def test_native_word_table_preferences(tmp_path, repeat, split, borders, striped):
    document = _docx_postprocess_fixture(__import__('docx'))
    table = document.add_table(rows=5, cols=2)
    for index,row in enumerate(table.rows):
        row.cells[0].text = f'业务行{index}'
        row.cells[1].text = str(index)
    path = tmp_path / 'tables.docx'
    document.save(path)
    design = table_design('word', repeatHeader=repeat, splitRows=split, borders=borders, striped=striped)
    _postprocess_docx(path, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT, design=design)
    actual = Document(path).tables[0]
    assert bool(actual.rows[0]._tr.xpath('./w:trPr/w:tblHeader')) == repeat
    for row in actual.rows:
        assert bool(row._tr.xpath('./w:trPr/w:cantSplit')) == (not split)
    for edge in actual._tbl.tblPr.find(qn('w:tblBorders')):
        expected = 'nil' if borders == 'none' or borders == 'light' and edge.tag in {qn('w:left'),qn('w:right'),qn('w:insideV')} else 'single'
        assert edge.get(qn('w:val')) == expected
    shading = actual.rows[2].cells[0]._tc.xpath('./w:tcPr/w:shd')
    assert bool(shading) == striped
    assert actual.cell(4,0).text == '业务行4'


@pytest.mark.parametrize('repeat', [True, False])
def test_pdf_actual_multipage_table_repeats_header_only_when_enabled(repeat):
    rows = ''.join(f'<tr><td>Row {index:03}</td><td>{index}</td></tr>' for index in range(100))
    body = '<table><thead><tr><th>HEADER_SENTINEL</th><th>Value</th></tr></thead><tbody>' + rows + '</tbody></table>'
    design = table_design('pdf', repeatHeader=repeat, borders='none', striped=False)
    html, _ = _semantic_documents(body, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT, design=design)
    pdf = PdfReader(BytesIO(HTML(string=html).write_pdf()))
    pages = [page.extract_text() for page in pdf.pages if 'Row ' in page.extract_text()]
    assert len(pages) >= 2
    assert 'HEADER_SENTINEL' in pages[0]
    assert ('HEADER_SENTINEL' in pages[1]) == repeat
    assert 'Row 099' in pages[-1]
    css = design_css(design)
    assert '.report-body th,.report-body td{border:0}' in css
    assert '.report-body tr.report-row-even{background:transparent}' in css


def test_legacy_design_hash_is_unchanged_without_table_preferences():
    import hashlib
    import json
    design = ReportDesign()
    old = design.model_dump(mode='json', by_alias=True)
    for key in ('page','signature','headerFooter','tables','pdfOutput','charts'):
        old.pop(key, None)
    assert design.digest() == hashlib.sha256(json.dumps(old,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    assert ReportDesign.model_validate(design.compact()) == design


@pytest.mark.parametrize('repeat', [True, False])
def test_word_actual_multipage_table_respects_repeated_header(tmp_path, repeat):
    from smart_reporting.reporting.delivery.office_engine import libreoffice_to_pdf

    document = _docx_postprocess_fixture(__import__('docx'))
    table = document.add_table(rows=101, cols=2)
    table.cell(0, 0).text = 'WORD_HEADER_SENTINEL'
    for index in range(1, 101):
        table.cell(index, 0).text = f'BusinessRow {index:03}'
        table.cell(index, 1).text = str(index)
    path = tmp_path / 'multipage.docx'
    document.save(path)
    _postprocess_docx(path, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT,
        design=table_design('word', repeatHeader=repeat), include_cover=False, include_toc=False)
    pdf = PdfReader(BytesIO(libreoffice_to_pdf(path.read_bytes(), suffix='.docx', timeout=60)))
    pages = [page.extract_text() for page in pdf.pages if 'BusinessRow' in page.extract_text()]
    assert len(pages) >= 2
    assert 'WORD_HEADER_SENTINEL' in pages[0]
    assert ('WORD_HEADER_SENTINEL' in pages[1]) == repeat
    assert 'BusinessRow 100' in pages[-1]


def test_explicit_table_design_overrides_only_selected_defaults():
    preferences = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '表格验证'},
        'word': {'tables': {'repeatHeader': False, 'striped': True, 'borders': 'light'}}}), 'word')
    design = document_design(preferences, overrides={'tables': {'borders': 'all'}})
    assert design.tables.borders == 'all'
    assert design.tables.repeat_header is False and design.tables.striped is True
    assert ReportDesign.model_validate(design.compact()) == design
    assert preferences['tables']['borders'] == 'light'
