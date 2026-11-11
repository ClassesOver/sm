"""沿用真实授权路由，转换验收来源额外包含一张无 OCR 文字的扫描页。"""
from __future__ import annotations

import argparse
import asyncio
from io import BytesIO
from pathlib import Path
from runpy import run_path

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
import uvicorn

_original = run_path(str(Path(__file__).with_name('pdf-delivery-batch-server.py')))
create_app = _original['create_app']
_original_source = create_app.__globals__['source_pdf']


def source_with_scan():
    image = Image.new('RGB', (300, 400), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 260, 150), fill='#2358a5')
    draw.ellipse((60, 210, 230, 370), fill='#b52b41')
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(300, 400))
    canvas.drawImage(ImageReader(image), 0, 0, width=300, height=400)
    canvas.showPage()
    canvas.save()
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(_original_source())))
    writer.append(PdfReader(BytesIO(buffer.getvalue())))
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


create_app.__globals__['source_pdf'] = source_with_scan

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4313)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
