"""彩色原文字与浅色底 PDF fixture，用于替换文字缩略图真实浏览器验收。"""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from reportlab.lib.colors import HexColor
from reportlab.pdfgen.canvas import Canvas


def source_pdf() -> bytes:
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(300, 400), invariant=1)
    colors = ("#FFF2CC", "#E2F0D9", "#DDEBF7", "#FCE4D6")
    for index, color in enumerate(colors, start=1):
        canvas.setFillColor(HexColor(color))
        canvas.rect(20, 30, 260, 340, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#123456"))
        canvas.setFont("Helvetica", 12)
        canvas.drawString(24, 347, f"source page {index}")
        canvas.showPage()
    canvas.save()
    reader = PdfReader(BytesIO(stream.getvalue()))
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        page.rotate((0, 90, 180, 270)[index])
        page.cropbox = RectangleObject((20, 30, 280, 370))
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


if __name__ == "__main__":
    import sys
    from pathlib import Path

    Path(sys.argv[1]).write_bytes(source_pdf())
