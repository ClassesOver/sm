"""每 N 页多文件拆分验收；复用现有真实路由及内存身份/仓储夹具。"""
import argparse
import asyncio
from io import BytesIO
from pathlib import Path
from runpy import run_path

import uvicorn
from reportlab.pdfgen.canvas import Canvas

create_app = run_path(str(Path(__file__).with_name('pdf-form-create-server.py')))['create_app']


def split_source():
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(300, 400))
    for index in range(1, 6):
        canvas.drawString(30, 300, f'Split source page {index}')
        canvas.showPage()
    canvas.save()
    return stream.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4440)
    args = parser.parse_args()
    create_app.__globals__['source_pdf'] = split_source
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1',
        port=args.port, log_level='warning')
