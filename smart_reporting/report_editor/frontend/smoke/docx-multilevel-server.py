"""Word 多级列表真实 HTTP 保存与授权下载；仓储复用既有内存验收宿主。"""
import argparse
import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from runpy import run_path

import uvicorn
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeArtifacts
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.tests.test_native_pdf_extract import extract_fixture


async def create_app(directory: Path, port: int, *, source: bytes | None = None):
    directory.mkdir(parents=True, exist_ok=True)
    f = await extract_fixture(directory / 'runtime')
    if source is None:
        document = Document()
        first = document.add_paragraph('多级列表第一段')
        first.alignment = WD_ALIGN_PARAGRAPH.CENTER
        first.runs[0].bold = True
        document.add_paragraph('多级列表第二段')
        document.add_heading('保留标题', level=1)
        document.add_paragraph('保留既有编号', style='List Number')
        document.sections[0].header.paragraphs[0].text = '保留页眉'
        stream = BytesIO(); document.save(stream); source = stream.getvalue()
    identity = ArtifactFile(path='native/source.docx', size=len(source), sha256=hashlib.sha256(source).hexdigest(), mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    await f.workspace.awrite_bytes(f.thread, identity.path, source)
    f.parent = f.parent.model_copy(update={'format': 'docx', 'source_file': identity})
    repository = run_path(str(Path(__file__).with_name('pdf-form-design-server.py')))['SaveRepository']()
    row = f.repository.revisions[f.parent.document_id]
    repository.revisions[f.parent.document_id] = row.model_copy(update={'context': f.parent, 'artifacts': NativeArtifacts(word=identity)})
    f.editor.repository = repository; f.editor.docx_enabled = True
    f.publication.repository = repository
    f.publication.public_base_url = origin = f'http://127.0.0.1:{port}'
    (directory / 'source.docx').write_bytes(source)
    requests = []

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await f.workspace.registry.aclose()

    static = run_path(str(Path(__file__).with_name('pdf_smoke_static.py')))['pdf_smoke_static_directory']()
    app = FastAPI(lifespan=lifespan)
    app.include_router(create_native_editor_router(f.publication.editor_grants, editor=f.editor, download_service=f.downloads, cookie_secure=False, allowed_origin=origin, static_dir=static))
    app.mount('/reports/v1/editor/assets', StaticFiles(directory=static))

    @app.middleware('http')
    async def record(request: Request, call_next):
        response = await call_next(request)
        requests.append({'method': request.method, 'path': request.url.path, 'status': response.status_code})
        (directory / 'http-evidence.json').write_text(json.dumps(requests, indent=2))
        return response

    @app.get('/__smoke__/state')
    async def state():
        actual = await f.editor.read_file(f.parent)
        return {'sourceSha256': hashlib.sha256(actual).hexdigest(), 'savedRevisions': len(repository.saved), 'requests': requests}

    raw, _ = await f.publication.editor_grants.issue(f.parent, capabilities=f.editor.capabilities(f.parent))
    (directory / 'server-info.json').write_text(json.dumps({'openPath': f'/reports/v1/native/open/{raw}', 'sourceSha256': identity.sha256, 'context': f.parent.model_dump(mode='json', by_alias=True)}, indent=2))
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4402)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port,
        source=args.source.read_bytes() if args.source else None)), host='127.0.0.1', port=args.port, log_level='warning')
