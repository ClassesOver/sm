"""图文分页偏好控制实际分页和原生属性，不改变图片或图注正文。"""
import base64
from io import BytesIO

import fitz
import pytest
from docx import Document
from docx.shared import Mm
from weasyprint import HTML

from smart_reporting.management.configuration_preview import MD_SAMPLE_PNG
from smart_reporting.preferences.document_adapter import document_design
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.report_design import ReportDesign
from smart_reporting.reporting.delivery.report_runtime.docx import _postprocess_docx
from smart_reporting.reporting.delivery.report_runtime.markdown import _semantic_documents
from smart_reporting.reporting.delivery.report_runtime.pdf import DEFAULT_PAGE_LAYOUT

from .test_report_runtime import _docx_postprocess_context, _docx_postprocess_fixture


def chart_design(format, keep):
    return document_design(resolve_format_preferences(FormatPreferences.model_validate({
        'common': {'signer': '图文验证'}, format: {'charts': {'keepWithCaption': keep},
            'cover': False, 'toc': False, 'headerFooter': {'enabled': False}}}), format))


def test_chart_pagination_is_frozen_per_format_and_explicit_design_takes_priority():
    preferences = FormatPreferences.model_validate({'common': {'signer': '图文验证'},
        'word': {'charts': {'keepWithCaption': False}}})
    resolved = resolve_format_preferences(preferences, 'word')
    word = document_design(resolved)
    assert word.charts.keep_with_caption is False
    assert document_design(resolve_format_preferences(preferences, 'pdf')).charts.keep_with_caption is True
    override = document_design(resolved, overrides={'charts': {'keepWithCaption': True}})
    assert override.charts.keep_with_caption is True
    assert resolved['charts']['keepWithCaption'] is False
    assert ReportDesign.model_validate(word.compact()) == word


@pytest.mark.parametrize('document,digest', [
    ({}, '95617d8ac95e68990c2e53149a26744cd1fba7ced8cf3e0b445d69b4ca83988f'),
    ({'page': {'orientation': 'landscape'}, 'tables': {'borders': 'none'}},
        '0e876cfd32eff215297cf4d8268b670a17ad9172cc8d57149727137f2226323e'),
])
def test_legacy_design_without_chart_pagination_retains_recorded_digest(document, digest):
    assert ReportDesign.model_validate(document).digest() == digest


@pytest.mark.parametrize('keep', [True, False])
def test_native_word_keeps_only_adjacent_registered_image_and_caption(tmp_path, keep):
    document = _docx_postprocess_fixture(__import__('docx'))
    unrelated = document.add_paragraph('独立正文')
    unrelated.paragraph_format.keep_with_next = True
    image = document.add_paragraph()
    image.add_run().add_picture(BytesIO(base64.b64decode(MD_SAMPLE_PNG)), width=Mm(60))
    document.add_paragraph('图表：分页样例')
    document.add_paragraph('图表：没有相邻图片的普通说明')
    path = tmp_path / 'image-caption.docx'
    document.save(path)
    _postprocess_docx(path, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT,
        design=chart_design('word', keep), include_cover=False, include_toc=False,
        caption_texts={'图表：分页样例'})
    actual = Document(path)
    caption = next(item for item in actual.paragraphs if item.text == '图表：分页样例')
    picture = next(item for item in actual.paragraphs if item._p.xpath('.//w:drawing'))
    assert picture.paragraph_format.keep_with_next is keep
    assert caption.paragraph_format.keep_together is keep
    assert caption.paragraph_format.keep_with_next is False
    assert next(item for item in actual.paragraphs if item.text == '独立正文').paragraph_format.keep_with_next is True
    assert next(item for item in actual.paragraphs if item.text.endswith('普通说明')).paragraph_format.keep_together is None
    assert len(actual.inline_shapes) == 1
    assert actual.inline_shapes[0]._inline.graphic.graphicData.pic.blipFill.blip.embed


@pytest.mark.parametrize('keep', [True, False])
def test_pdf_actual_page_boundary_respects_image_caption_setting(keep):
    body = ('<style>.report-title{display:none}.spacer{height:210mm;margin:0}'
        '.report-figure{margin:0}.report-figure-caption{height:20mm;margin:0}</style>'
        '<div class="spacer">BEFORE_IMAGE</div><p><img alt="固定图片" '
        'src="data:image/png;base64,' + MD_SAMPLE_PNG + '" style="width:75mm;height:30mm"></p>'
        '<p><em>图表：CAPTION_SENTINEL</em></p><p>AFTER_CAPTION</p>')
    html, _ = _semantic_documents(body, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT,
        design=chart_design('pdf', keep), include_cover=False, include_toc=False)
    with fitz.open(stream=HTML(string=html).write_pdf(), filetype='pdf') as pdf:
        caption_page = next(index for index, page in enumerate(pdf) if 'CAPTION_SENTINEL' in page.get_text())
        image_page = next(index for index, page in enumerate(pdf) if page.get_image_info())
        assert (image_page == caption_page) is keep
        assert 'BEFORE_IMAGE' in ''.join(page.get_text() for page in pdf)
        assert 'AFTER_CAPTION' in ''.join(page.get_text() for page in pdf)
