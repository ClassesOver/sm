"""链接窗口闭环：真实授权与 PDF 路由，隔离内存修订仓储。"""
import argparse
import asyncio
import base64
from pathlib import Path
from runpy import run_path

import pymupdf
import uvicorn

server = run_path(str(Path(__file__).with_name('pdf-static-text-server.py')))


def source_pdf():
    document = pymupdf.open(stream=server['source_pdf'](), filetype='pdf')
    document.set_metadata({**document.metadata, 'title': 'Link fidelity fixture', 'subject': 'PC link UI'})
    document.set_toc([[1, 'Second page', 2], [1, 'Third page', 3]])
    document[1].insert_link({'kind': pymupdf.LINK_URI, 'from': pymupdf.Rect(20, 70, 100, 90), 'uri': 'https://existing.example.com/keep'})
    document[1].add_text_annot((200, 200), 'Keep this original note')
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
    document[2].insert_image(pymupdf.Rect(60, 230, 160, 310), stream=png, keep_proportion=False)
    result = document.tobytes()
    document.close()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4393)
    args = parser.parse_args()
    app = asyncio.run(server['create_app'](args.directory, args.port, source=source_pdf()))
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
