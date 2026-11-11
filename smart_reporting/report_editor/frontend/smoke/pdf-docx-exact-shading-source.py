"""Deterministic PDF with two custom RGB highlights and legacy palette/plain text."""
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.pdfgen.canvas import Canvas


def source_pdf():
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(400, 300), invariant=1)
    canvas.setFont('Helvetica', 12)
    canvas.setFillColor(HexColor('#123456'))
    canvas.drawString(40, 260, 'Exact source shading')
    for x, label, color in [(40, 'Peach text', 'FFF2CC'), (150, 'Green text', 'E2F0D9'), (260, 'Yellow text', 'FFFF00')]:
        canvas.setFillColor(HexColor('#' + color))
        canvas.rect(x - 1, 217, 89, 16, fill=1, stroke=0)
        canvas.setFillColor(HexColor('#123456'))
        canvas.drawString(x, 220, label)
    canvas.drawString(40, 180, 'Plain text')
    canvas.setFillColor(HexColor('#FFFFFF'))
    canvas.rect(149, 177, 89, 16, fill=1, stroke=0)
    canvas.setFillColor(HexColor('#123456'))
    canvas.drawString(150, 180, 'White text')
    canvas.showPage()
    canvas.save()
    return stream.getvalue()


if __name__ == '__main__':
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_bytes(source_pdf())
