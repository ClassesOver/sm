"""Mixed-UserUnit measurement browser fixture using the existing scoped host."""
from __future__ import annotations

import argparse
import asyncio
from io import BytesIO
from pathlib import Path
from runpy import run_path

import uvicorn
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, RectangleObject
from reportlab.pdfgen import canvas


def source_pdf() -> bytes:
    stream = BytesIO()
    document = canvas.Canvas(stream, pagesize=(500, 600), invariant=1, pageCompression=0)
    for label in ('UNIT2 CONTROL', 'UNIT1 CONTROL'):
        document.drawString(60, 350, label)
        document.showPage()
    document.save()
    writer = PdfWriter()
    for original, unit in zip(PdfReader(BytesIO(stream.getvalue())).pages, (2, 1), strict=True):
        page = writer.add_page(original)
        page.cropbox = RectangleObject([30, 40, 430, 440])
        page[NameObject('/UserUnit')] = NumberObject(unit)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4361)
    args = parser.parse_args()
    create_app = run_path(str(Path(__file__).with_name('pdf-static-text-server.py')))['create_app']
    app = asyncio.run(create_app(args.directory, args.port, source=source_pdf()))
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
