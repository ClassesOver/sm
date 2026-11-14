"""图注编号只作用于正式图文语义块，并按 PDF/Word 冻结配置分别执行。"""
import base64
import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

import pymupdf
import pytest
from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader

from smart_reporting.management.configuration_preview import MD_SAMPLE_PNG
from smart_reporting.preferences.document_adapter import document_design
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.report_design import ReportDesign
from smart_reporting.reporting.delivery.report_runtime.markdown import _semantic_documents
from smart_reporting.reporting.delivery.report_runtime.pdf import DEFAULT_PAGE_LAYOUT
from smart_reporting.reporting.delivery.report_runtime.runtime import ReportRuntime

from .test_report_runtime import _docx_postprocess_context
from .test_report_runtime_full_render import _build_workspace


def _preferences(pdf_numbered=True):
    return FormatPreferences.model_validate({'common': {'signer': '图注编号验证'}, **{
        format: {'cover': False, 'toc': False, 'sources': True,
            'headerFooter': {'enabled': False, 'pageNumbers': False}, 'watermark': {'enabled': False},
            'charts': {'captionNumbering': numbered}}
        for format, numbered in [('pdf', pdf_numbered), ('word', not pdf_numbered)]}})


def test_chart_caption_numbering_maps_frozen_format_values_without_mutation():
    preferences = _preferences()
    resolved = resolve_format_preferences(preferences, 'word')
    before = deepcopy(resolved)
    word = document_design(resolved)
    assert word.charts.caption_numbering is False
    assert document_design(resolve_format_preferences(preferences, 'pdf')).charts.caption_numbering is True
    assert document_design(resolved, overrides={'charts': {'captionNumbering': True}}).charts.caption_numbering is True
    assert resolved == before
    assert ReportDesign.model_validate(word.compact()) == word


@pytest.mark.parametrize('numbered', [True, False])
def test_only_adjacent_figure_captions_are_numbered_without_rewriting_source_or_aliases(numbered):
    preferences = _preferences(numbered)
    body = ('<p><em>图表：独立手写说明 1234.56</em></p>'
        '<p><img src="chart.png" alt="图片原文 1234.56"></p>'
        '<p><em>图表：收支 <strong>趋势</strong> [来源 001]</em></p>'
        '<p><img src="uncaptioned.png" alt="无图注图片"></p>'
        '<p>普通说明</p><p><img src="second.png" alt="第二图片"></p>'
        '<p><em>图表：第二图注 [来源 002]</em></p>')
    before = body
    pdf, word = _semantic_documents(body, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT,
        design=document_design(resolve_format_preferences(preferences, 'pdf')), include_cover=False, include_toc=False)
    for output in (pdf, word):
        parsed = BeautifulSoup(output, 'html.parser')
        captions = parsed.select('.report-figure-caption')
        assert [node.get_text() for node in captions] == ([
            '图 1：收支 趋势 [来源 001]', '图 2：第二图注 [来源 002]'] if numbered else [
            '图表：收支 趋势 [来源 001]', '图表：第二图注 [来源 002]'])
        assert parsed.find('img', src='chart.png')['alt'] == '图片原文 1234.56'
        assert '图表：独立手写说明 1234.56' in parsed.get_text()
        assert captions[0].find('strong').get_text() == '趋势'
    assert body == before


def test_legacy_chart_design_retains_unumbered_captions_and_recorded_identity():
    design = ReportDesign.model_validate({'charts': {'keepWithCaption': False}})
    assert design.digest() == '42b52eb2bdc0ae5d6eeb0eff792cfc91df0dac65791b9da70b8ea617b66186cf'
    assert design.compact() == {'charts': {'keepWithCaption': False}}
    pdf, _ = _semantic_documents('<p><img src="chart.png"></p><p><em>图表：旧图注</em></p>',
        context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT, design=design)
    assert BeautifulSoup(pdf, 'html.parser').select_one('.report-figure-caption').get_text() == '图表：旧图注'


@pytest.mark.parametrize('pdf_numbered', [True, False])
def test_real_report_keeps_opposite_pdf_word_caption_settings_and_source_identity(tmp_path, pdf_numbered):
    workspace = tmp_path / 'workspace'
    state = _build_workspace(workspace)
    state.pop('_editorExportSettings')
    image = workspace / 'chart.png'
    image.write_bytes(base64.b64decode(MD_SAMPLE_PNG))
    source = workspace / 'report.md'
    with source.open('a', encoding='utf-8') as output:
        output.write('\n![图像原文 1234.56](chart.png)\n\n*图表：收支趋势*\n\n'
            '图表：独立手写说明 1234.56\n\n![第二图片](chart.png)\n\n*图表：第二图注*\n')
    before = source.read_bytes(), image.read_bytes(), deepcopy(state['sources'])
    preferences = _preferences(pdf_numbered)
    resolved = {format: resolve_format_preferences(preferences, format) for format in ('pdf', 'word')}
    # 直接验证冻结设计也能分格式渲染，不能依赖另一个可选偏好字典才恢复 Word 独立性。
    state['_formatDesigns'] = {format: document_design(values).compact() for format, values in resolved.items()}
    design_before = deepcopy(state['_formatDesigns'])
    result = ReportRuntime(workspace).render_markdown(state, 'report.md', 'revision/report.pdf',
        '.reporting-tmp/workspace-report-caption-numbering-render/render.pdf')
    assert result['status'] == 'rendered'
    pdf_text = ''.join(''.join(page.extract_text().split()) for page in PdfReader(workspace / 'revision/report.pdf').pages)
    doc = Document(workspace / 'revision/report.docx')
    word_text = ''.join(''.join(paragraph.text.split()) for paragraph in doc.paragraphs)
    for text, numbered in ((pdf_text, pdf_numbered), (word_text, not pdf_numbered)):
        assert ('图1：收支趋势' in text) is numbered
        assert ('图2：第二图注' in text) is numbered
        assert ('图表：收支趋势' in text) is (not numbered)
        assert '第二图注' in text and '图表：独立手写说明1234.56' in text
        assert '128.50' in text and '[来源001]' in text
    assert len(doc.inline_shapes) == 2
    assert (source.read_bytes(), image.read_bytes(), state['sources']) == before
    assert state['_formatDesigns'] == design_before
    evidence = Path('output/system-config-preferences/document-caption-numbering') / ('pdf-numbered' if pdf_numbered else 'word-numbered')
    evidence.mkdir(parents=True, exist_ok=True)
    for name in ('report.pdf', 'report.docx'):
        shutil.copyfile(workspace / 'revision' / name, evidence / name)
    with pymupdf.open(evidence / 'report.pdf') as pdf:
        page = next(page for page in pdf if '收支趋势' in page.get_text())
        page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).save(evidence / 'pdf-caption-page.png')
    receipt = {'pdfNumbered': pdf_numbered, 'wordNumbered': not pdf_numbered,
        'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'imageSha256': hashlib.sha256(image.read_bytes()).hexdigest(),
        'formatDesigns': state['_formatDesigns'], 'render': result['render']}
    (evidence / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
