"""静态填写真实 HTTP 宿主：复用现有授权、修订仓储、发布与下载夹具。"""
import argparse
import asyncio
from io import BytesIO
from pathlib import Path
from runpy import run_path

import uvicorn
from reportlab.pdfgen.canvas import Canvas

create_app = run_path(str(Path(__file__).with_name('pdf-static-text-server.py')))['create_app']


def static_fill_source():
    output = BytesIO()
    canvas = Canvas(output, pagesize=(400, 500), invariant=True)
    canvas.drawString(30, 460, 'Static fill source page 1')
    canvas.rect(55, 350, 14, 14)
    canvas.acroForm.textfield(name='RequiredCustomer', x=30, y=400, width=150, height=24,
                            fieldFlags='required', forceBorder=True)
    canvas.acroForm.checkbox(name='NativeCheck', x=230, y=350, size=16, forceBorder=True)
    canvas.showPage()
    canvas.drawString(30, 460, 'Static fill source page 2')
    canvas.rect(55, 350, 14, 14)
    canvas.showPage()
    canvas.drawString(30, 460, 'Static fill source page 3')
    canvas.showPage()
    canvas.save()
    return output.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4468)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port, source=args.source.read_bytes() if args.source else static_fill_source())),
                host='127.0.0.1', port=args.port, log_level='warning')
