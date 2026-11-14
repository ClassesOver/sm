"""Pandoc样式显示名大小写不同仍须复用原生Caption，避免重复styleId。"""

from docx import Document
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.report_runtime.docx import _postprocess_docx
from smart_reporting.reporting.delivery.report_runtime.pdf import DEFAULT_PAGE_LAYOUT

from .test_report_runtime import _docx_postprocess_context, _docx_postprocess_fixture


def test_imported_caption_style_is_reused_without_duplicate_native_identity(tmp_path):
    native = _docx_postprocess_fixture(__import__('docx'))
    original = native.styles['Caption']
    original.element.find(qn('w:name')).set(qn('w:val'), 'Caption')
    base = original.element.find(qn('w:basedOn')).get(qn('w:val'))
    native.add_paragraph('测试图注')
    path = tmp_path / 'caption-style.docx'
    native.save(path)
    _postprocess_docx(path, context=_docx_postprocess_context(), layout=DEFAULT_PAGE_LAYOUT,
        caption_texts={'测试图注'})
    actual = Document(path)
    definitions = actual.styles.element.xpath('./w:style[@w:styleId="Caption"]')
    assert len(definitions) == 1
    assert definitions[0].find(qn('w:basedOn')).get(qn('w:val')) == base
    paragraph = next(p for p in actual.paragraphs if p.text == '测试图注')
    assert paragraph.style.style_id == 'Caption'
