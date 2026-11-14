"""Word 邮件合并真实授权 HTTP 夹具；复用原生保存、登记及下载服务。"""
import argparse
import asyncio
from io import BytesIO
from pathlib import Path
from runpy import run_path

import uvicorn
from docx import Document

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4497)
    args = parser.parse_args()
    document = Document()
    document.add_paragraph('Dear ,')
    document.add_paragraph('Retained body')
    document.sections[0].header.paragraphs[0].text = 'Retained header'
    stream = BytesIO()
    document.save(stream)
    create_app = run_path(str(Path(__file__).with_name('docx-multilevel-server.py')))['create_app']
    app = asyncio.run(create_app(args.directory, args.port, source=stream.getvalue()))
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
