"""真实 PDF 字段设置宿主，仓储沿用已有内存夹具。"""
import argparse
import asyncio
import hashlib
from pathlib import Path
from runpy import run_path

import uvicorn
from smart_reporting.reporting.delivery.pdf_native import patch_pdf

server = run_path(str(Path(__file__).with_name('pdf-form-create-server.py')))
create_app = server['create_app']
original_source = create_app.__globals__['source_pdf']


def settings_source():
    content = original_source()
    for fields in [
        dict(fieldName='customer_detail_detail_detail_detail_detail_detail', fieldKind='text', rect=[30, 240, 180, 270], value='Alice'),
        dict(fieldName='status', fieldKind='choice', rect=[30, 190, 180, 214], options=['One', 'Two'], value='Two'),
        dict(fieldName='consent', fieldKind='radio', rect=[30, 130, 50, 150]),
    ]:
        digest = hashlib.sha256(content).hexdigest()
        page_id = f'sha256:{digest}:page:0'
        if fields['fieldKind'] == 'radio':
            fields['radioWidgets'] = [
                dict(pageId=page_id, rect=[30, 130, 50, 150], exportValue='Yes', checked=True),
                dict(pageId=page_id, rect=[80, 130, 100, 150], exportValue='No', checked=False),
            ]
        content = patch_pdf(content, [dict(kind='createFormField', sourceSha256=digest, pageId=page_id, required=False, **fields)])
    return content


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4382)
    args = parser.parse_args()
    create_app.__globals__['source_pdf'] = settings_source
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
