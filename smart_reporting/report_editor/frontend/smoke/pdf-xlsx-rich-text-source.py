"""Stable complex source with mixed fonts/decorations and a typed numeric cell."""
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

LABELS = ['Plain Bold Italic Under Strike Serif', 'Dominant decorated words plain']

def source_pdf():
    fixture = Path(__file__).resolve().parents[3] / 'reporting/pdf_engine/bridge/fixtures/complex-layout.pdf'
    extra = BytesIO()
    canvas = Canvas(extra, pagesize=(600, 800), invariant=1)
    canvas.setLineWidth(.7)
    lines = [(650, [('Plain ', 'Helvetica', False, False), ('Bold ', 'Helvetica-Bold', False, False), ('Italic ', 'Helvetica-Oblique', False, False), ('Under ', 'Helvetica', True, False), ('Strike ', 'Helvetica', False, True), ('Serif', 'Times-Roman', False, False)]), (600, [('Dominant decorated words ', 'Helvetica-BoldOblique', True, True), ('plain', 'Helvetica', False, False)])]
    for y, runs in lines:
        x = 60
        for text, font, underline, strike in runs:
            canvas.setFont(font, 14)
            canvas.drawString(x, y, text)
            width = stringWidth(text, font, 14)
            for delta in ([-1.5] if underline else []) + ([4.2] if strike else []):
                canvas.line(x, y + delta, x + width, y + delta)
            x += width
    canvas.setFont('Helvetica-Bold', 14)
    canvas.drawString(60, 550, '12345')
    canvas.setFont('Helvetica', 14)
    canvas.drawString(60 + stringWidth('12345', 'Helvetica-Bold', 14), 550, '.67')
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
