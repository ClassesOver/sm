"""Bates 真实 HTTP 保存验收宿主；仅身份/仓储采用现有内存夹具。"""
import argparse
import asyncio
from io import BytesIO
from pathlib import Path
from runpy import run_path

import uvicorn
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

create_app = run_path(str(Path(__file__).with_name('pdf-form-create-server.py')))['create_app']


def bates_source():
    data = BytesIO()
    canvas = Canvas(data, pagesize=(300, 400))
    for index in range(3):
        canvas.drawString(35, 250, f'Original page {index + 1}')
        canvas.showPage()
    canvas.save()
    writer = PdfWriter()
    for page in PdfReader(BytesIO(data.getvalue())).pages:
        writer.add_page(page)
    writer.pages[1].cropbox.lower_left = (10, 20)
    writer.pages[1].cropbox.upper_right = (290, 380)
    writer.pages[1].rotate(90)
    writer.add_metadata({'/Title': 'Preserved Bates source'})
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4412)
    args = parser.parse_args()
    create_app.__globals__['source_pdf'] = bates_source
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
