"""Reproducible complex PDF plus four vector-decorated editable text samples."""
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

LABELS = ['Underlined amount', 'Struck adjustment', 'Regular label', 'Both decorations']

def source_pdf():
    fixture = Path(__file__).resolve().parents[3] / 'reporting/pdf_engine/bridge/fixtures/complex-layout.pdf'
    extra = BytesIO()
    canvas = Canvas(extra, pagesize=(600, 800), invariant=1)
    canvas.setFont('Helvetica', 14)
    canvas.setLineWidth(.7)
    for index, text in enumerate(LABELS):
        y = 650 - index * 50
        canvas.drawString(60, y, text)
        for delta in ([-1.5] if index == 0 else [4.2] if index == 1 else [-1.5, 4.2] if index == 3 else []):
            canvas.line(60, y + delta, 60 + stringWidth(text, 'Helvetica', 14), y + delta)
    canvas.save()
    writer = PdfWriter()
    writer.append(PdfReader(fixture))
    writer.append(PdfReader(extra))
    output = BytesIO()
    writer.write(output)
    return output.getvalue()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_bytes(source_pdf())
