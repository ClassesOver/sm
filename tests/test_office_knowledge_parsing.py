from io import BytesIO

import pytest

from smart_reporting.office.knowledge import parse_knowledge_file


def make_knowledge_sample(format, text):
    stream = BytesIO()
    if format == 'docx':
        from docx import Document
        document = Document()
        document.add_paragraph(text)
        document.save(stream)
    elif format == 'xlsx':
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(['Metric', 'Value'])
        workbook.active.append([text, 42])
        workbook.save(stream)
    elif format == 'pptx':
        from pptx import Presentation
        from pptx.util import Inches
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = text
        deck.save(stream)
    else:
        from reportlab.pdfgen.canvas import Canvas
        canvas = Canvas(stream)
        canvas.drawString(40, 700, text)
        canvas.save()
    return stream.getvalue()


@pytest.mark.parametrize('format', ['docx', 'xlsx', 'pptx', 'pdf'])
def test_knowledge_reads_actual_four_format_bytes(format):
    parsed = parse_knowledge_file(make_knowledge_sample(format, 'Office revenue 42'), format)
    assert 'Office revenue' in parsed['text'] and '42' in parsed['text']
    if format in {'xlsx', 'pptx'}:
        assert parsed['limitations']
