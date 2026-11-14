"""文档属性真实 HTTP 验收宿主，使用既有身份/仓储夹具。"""
import argparse
import asyncio
import os
from io import BytesIO
from pathlib import Path
from runpy import run_path

import uvicorn
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

create_app = run_path(str(Path(__file__).with_name('pdf-form-create-server.py')))['create_app']


def metadata_source():
    if supplied := os.environ.get('PDF_METADATA_SOURCE_PDF'):
        return Path(supplied).read_bytes()
    data = BytesIO()
    canvas = Canvas(data, pagesize=(300, 400))
    for index in range(2):
        canvas.drawString(35, 250, f'Original metadata page {index + 1}')
        canvas.showPage()
    canvas.save()
    writer = PdfWriter()
    for page in PdfReader(BytesIO(data.getvalue())).pages:
        writer.add_page(page)
    writer.add_metadata({'/Title': 'Original metadata title', '/Author': 'Original author',
                         '/Subject': 'Original subject', '/Keywords': 'original keywords',
                         '/Creator': 'Preserved source creator', '/Producer': 'Preserved source producer',
                         '/CreationDate': 'D:20200102030405Z', '/ModDate': 'D:20210102030405Z',
                         '/CustomAudit': 'Preserved custom info'})
    writer.add_outline_item('Preserved source bookmark', 0)
    writer.add_attachment('evidence.txt', b'Preserved source attachment')
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4432)
    args = parser.parse_args()
    create_app.__globals__['source_pdf'] = metadata_source
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
