"""PDF 页边测量提示浏览器夹具：复用真实路由/授权，限定内存修订仓储。"""
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
    document.drawString(60, 350, 'CONTROL CONTENT')
    document.showPage()
    document.save()
    writer = PdfWriter()
    page = writer.add_page(PdfReader(BytesIO(stream.getvalue())).pages[0])
    page.cropbox = RectangleObject([30, 40, 430, 440])
    page[NameObject('/UserUnit')] = NumberObject(2)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4359)
    args = parser.parse_args()
    create_app = run_path(str(Path(__file__).with_name('pdf-static-text-server.py')))['create_app']
    app = asyncio.run(create_app(args.directory, args.port, source=source_pdf()))
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
