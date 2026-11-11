"""真实文件解析与定位；不以模拟reader代替中文、表格或物理页验收。"""

from io import BytesIO

import pytest
from docx import Document
from pypdf import PdfWriter
from reportlab.pdfgen.canvas import Canvas

from smart_reporting.reporting.business_knowledge.ingestion import parse_document


def test_utf8_chinese_markdown_retains_line_coordinates_and_original_hash():
    content = "# 预算口径\n\n执行率＝实际合计÷预算合计。\n退款保持负值。\n".encode()
    parsed = parse_document(content, filename="制度.md")
    assert parsed.status == "parsed"
    assert len(parsed.original_hash) == 64
    snippet = next(x for x in parsed.fragments if "执行率" in x.text)
    assert snippet.locator.kind == "text_lines"
    assert snippet.locator.line_start == 3
    assert "执行率＝实际合计÷预算合计。" in snippet.text


def test_docx_table_and_paragraph_have_coordinates_without_invented_pages():
    document = Document()
    document.add_paragraph("正式统计口径")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "指标"
    table.cell(0, 1).text = "公式"
    table.cell(1, 0).text = "执行率"
    table.cell(1, 1).text = "执行额合计÷预算额合计"
    stream = BytesIO()
    document.save(stream)
    parsed = parse_document(stream.getvalue(), filename="制度.docx")
    assert any(x.text == "正式统计口径" and x.locator.kind == "docx_paragraph" for x in parsed.fragments)
    cell = next(x for x in parsed.fragments if x.text == "执行额合计÷预算额合计")
    assert (cell.locator.table, cell.locator.row, cell.locator.column) == (1, 2, 2)
    assert all(x.locator.page is None for x in parsed.fragments)


def test_pdf_uses_physical_pages_instead_of_guessed_printed_numbers():
    stream = BytesIO()
    canvas = Canvas(stream)
    for number, text in ((10, "Budget definition"), (11, "Actual definition")):
        canvas.drawString(80, 760, str(number))
        canvas.drawString(80, 730, text)
        canvas.showPage()
    canvas.save()
    parsed = parse_document(stream.getvalue(), filename="policy.pdf")
    assert [x.locator.page for x in parsed.fragments] == [1, 2]
    assert "Budget definition" in parsed.fragments[0].text


def test_scan_or_blank_pdf_never_becomes_ready_empty_knowledge():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    parsed = parse_document(stream.getvalue(), filename="scan.pdf")
    assert parsed.status == "needs_transcription"
    assert "page_without_extractable_text" in parsed.issue_codes
    assert parsed.fragments == ()


@pytest.mark.parametrize("filename,content", [
    ("../outside.txt", b"text"), ("folder/file.txt", b"text"),
    ("C:\\file.txt", b"text"), ("fake.pdf", b"not a PDF"),
    ("fake.docx", b"not a ZIP"), ("binary.txt", b"\x00binary"),
    ("unknown.exe", b"text"), ("empty.txt", b""),
])
def test_invalid_upload_is_rejected_without_silent_empty_success(filename, content):
    with pytest.raises(ValueError):
        parse_document(content, filename=filename)


def test_pdf_page_limit_is_checked_before_extraction():
    writer = PdfWriter()
    for _ in range(201):
        writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    with pytest.raises(ValueError, match="page_limit"):
        parse_document(stream.getvalue(), filename="too-many-pages.pdf")


def test_pdf_leading_business_numbers_are_not_removed_as_guessed_page_numbers():
    stream = BytesIO()
    canvas = Canvas(stream)
    for number in (1, 2):
        canvas.drawString(80, 760, str(number))
        canvas.drawString(80, 730, "Approved projects")
        canvas.showPage()
    canvas.save()
    parsed = parse_document(stream.getvalue(), filename="counts.pdf")
    assert parsed.fragments[0].text.lstrip().startswith("1\n")
    assert parsed.fragments[1].text.lstrip().startswith("2\n")


@pytest.mark.parametrize("story", ["header", "footer"])
def test_docx_non_body_rules_cannot_be_approved_as_complete_extraction(story):
    document = Document()
    document.add_paragraph("正文有计算说明")
    getattr(document.sections[0], story).paragraphs[0].text = "仅纳入已结账单据"
    stream = BytesIO()
    document.save(stream)
    parsed = parse_document(stream.getvalue(), filename="制度.docx")
    assert parsed.status == "needs_transcription"
    assert "docx_non_body_text_requires_transcription" in parsed.issue_codes
    assert any(fragment.text == "正文有计算说明" for fragment in parsed.fragments)


def test_docx_content_control_text_is_not_silently_skipped():
    from docx.oxml import OxmlElement

    document = Document()
    document.add_paragraph("正文")
    control, inner = OxmlElement("w:sdt"), OxmlElement("w:sdtContent")
    paragraph, run, text = OxmlElement("w:p"), OxmlElement("w:r"), OxmlElement("w:t")
    text.text = "仅纳入已结账单据"
    run.append(text)
    paragraph.append(run)
    inner.append(paragraph)
    control.append(inner)
    document.element.body.append(control)
    stream = BytesIO()
    document.save(stream)
    parsed = parse_document(stream.getvalue(), filename="制度.docx")
    assert parsed.status == "needs_transcription"
    assert "docx_body_content_requires_transcription" in parsed.issue_codes


def test_docx_footnote_rules_are_marked_as_incomplete_extraction():
    from zipfile import ZipFile

    document = Document()
    document.add_paragraph("正文")
    stream = BytesIO()
    document.save(stream)
    output = BytesIO()
    with ZipFile(stream) as source, ZipFile(output, "w") as target:
        for entry in source.infolist():
            target.writestr(entry, source.read(entry.filename))
        target.writestr("word/footnotes.xml", (
            '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:footnote w:id="1"><w:p><w:r><w:t>仅纳入已结账单据</w:t>'
            '</w:r></w:p></w:footnote></w:footnotes>'
        ).encode())
    parsed = parse_document(output.getvalue(), filename="制度.docx")
    assert parsed.status == "needs_transcription"
    assert "docx_non_body_text_requires_transcription" in parsed.issue_codes
