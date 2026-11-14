"""PDF 书签专项真实 HTTP 宿主；仅仓储/身份采用既有测试夹具。"""
import argparse
import asyncio
from io import BytesIO
from pathlib import Path
from runpy import run_path

import uvicorn
from pypdf import PdfWriter
from pypdf.generic import Fit

create_app = run_path(str(Path(__file__).with_name('pdf-form-create-server.py')))['create_app']


def outline_source():
    writer = PdfWriter()
    for width, height in [(300, 400), (350, 450), (400, 500)]:
        writer.add_blank_page(width=width, height=height)
    writer.add_metadata({'/Title': 'Preserved outline source'})
    first = writer.add_outline_item('First', 0, fit=Fit.fit_horizontally(320))
    writer.add_outline_item('Child', 1, parent=first)
    writer.add_outline_item('Last', 2)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4396)
    args = parser.parse_args()
    create_app.__globals__['source_pdf'] = outline_source
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
