"""Stable rich source plus authored plain/grouped decimal precision."""
from io import BytesIO
from pathlib import Path
from runpy import run_path
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

DECIMALS = ['12345.6789', '-31.10', '12,345.678', '1.25e3']

def source_pdf():
    source = run_path(str(Path(__file__).with_name('pdf-xlsx-rich-text-source.py')))['source_pdf']()
    overlay = BytesIO()
    canvas = Canvas(overlay, pagesize=(600, 800), invariant=1)
    canvas.setFont('Helvetica', 14)
    for index, text in enumerate(DECIMALS):
        canvas.drawString(60, 500 - index * 50, text)
    canvas.save()
    reader = PdfReader(BytesIO(source))
    reader.pages[1].merge_page(PdfReader(overlay).pages[0])
    writer = PdfWriter()
    writer.append(reader)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_bytes(source_pdf())
