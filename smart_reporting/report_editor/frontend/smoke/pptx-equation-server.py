"""公式浏览器验收：复用真实原生 HTTP/工作区/发布/下载链，仓储为既有内存夹具。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pptx import Presentation
from pptx.util import Inches

from fastapi.responses import JSONResponse
from smart_reporting.http.identity import requires_workspace_capability, verified_report_request
from smart_reporting.http.security import CapabilityError, verify_capability
from smart_reporting.report_editor import slides, slides_render
from smart_reporting.report_editor.native import NativeEditorService
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_import import NativeImportService
from smart_reporting.report_editor.native_import_api import create_native_import_router
from smart_reporting.reporting.delivery.office_engine import engine_dir
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication
from smart_reporting.reporting.tests.test_native_editor_api import Repository as SourceRepository
from smart_reporting.reporting.tests.test_native_publication_nonblocking import Repository as PublicationRepository
from smart_reporting.tests.test_reporting_request_identity import SECRET, _capability


class Repository(SourceRepository, PublicationRepository):
    def __init__(self):
        SourceRepository.__init__(self)
        PublicationRepository.__init__(self)

    async def create_from_source(self, source, **kwargs):
        document = await SourceRepository.create_from_source(self, source, **kwargs)
        key = (document.document_id, 1)
        revision = self.revisions[key]
        self.revisions[key] = revision.model_copy(update={"context": revision.context.model_copy(update={"origin": source.origin})})
        return document

    async def complete_revision(self, reservation, **kwargs):
        result = await PublicationRepository.complete_revision(self, reservation, **kwargs)
        self.revisions[(result.document_id, result.revision)] = result
        return result


async def create_app(directory: Path, port: int) -> FastAPI:
    directory.mkdir(parents=True, exist_ok=True)
    deck = Presentation()
    for index in range(2):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        shape = slide.shapes.add_textbox(Inches(.5), Inches(.5), Inches(5), Inches(1))
        shape.text = f'公式验收保留正文 {index + 1} <&> 😀'
        shape.text_frame.paragraphs[0].runs[0].font.bold = True
        slide.notes_slide.notes_text_frame.text = f'保留讲稿 {index + 1}'
    stream = BytesIO(); deck.save(stream)
    (directory / 'source.pptx').write_bytes(stream.getvalue())
    publication, _, downloads = await create_publication(directory / 'workspace')
    publication.repository = Repository()
    publication.public_base_url = f'http://127.0.0.1:{port}'
    editor = NativeEditorService(publication.workspace, publication.repository, publication.editor_grants,
        office_enabled=True, publication=publication)
    importer = NativeImportService(publication.workspace, publication.repository, publication.editor_grants)
    requests, calls = [], []
    actual = slides.run_bridge

    def traced(engine, name, request, **kwargs):
        result = actual(engine, name, request, **kwargs)
        calls.append({'engine': engine, 'script': name, 'command': result.args[:2], 'returncode': result.returncode})
        (directory / 'bridge-calls.json').write_text(json.dumps(calls, indent=2))
        return result

    slides.run_bridge = traced
    slides_render.run_bridge = traced

    @asynccontextmanager
    async def lifespan(app):
        yield
        await publication.workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    app.state.agentos_context = SimpleNamespace(settings=SimpleNamespace(workspace_hmac_secret=SECRET))
    @app.middleware('http')
    async def authorize(request: Request, call_next):
        # 复用应用 capability 与身份绑定原语，避免导入 app 引发无关业务数据库启动。
        thread = request.headers.get('X-Workspace-Thread', '').strip()
        token = request.headers.get('X-Workspace-Capability', '').strip()
        if not requires_workspace_capability(request.url.path, has_thread=bool(thread), has_capability=bool(token)):
            return await call_next(request)
        if not thread:
            return JSONResponse({'error': 'thread_header_required'}, status_code=400)
        try:
            identity = verify_capability(token, SECRET, thread)
        except CapabilityError as error:
            return JSONResponse({'error': str(error)}, status_code=401)
        request.state.capability = identity
        with verified_report_request(request, user_id=str(identity.user), thread_id=thread,
                                     database=identity.database, company_id=str(identity.company)):
            return await call_next(request)
    app.include_router(create_native_import_router(importer, enabled=True))
    root = Path(os.environ['NATIVE_EDITOR_ASSET_ROOT'])
    app.include_router(create_native_editor_router(publication.editor_grants, editor=editor,
        download_service=downloads, cookie_secure=False, allowed_origin=publication.public_base_url, static_dir=root))
    app.mount('/reports/v1/editor/assets', StaticFiles(directory=root))

    @app.middleware('http')
    async def record(request: Request, call_next):
        body = await request.body() if request.method == 'POST' and 'application/json' in request.headers.get('content-type', '') else b''
        response = await call_next(request)
        requests.append({'method': request.method, 'path': request.url.path, 'status': response.status_code,
                         **({'body': json.loads(body)} if body else {})})
        (directory / 'http-evidence.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2))
        return response

    @app.get('/__smoke__/state')
    async def state():
        return {'requests': requests, 'bridgeCalls': calls, 'completedRevisions': publication.repository.completions}

    (directory / 'server-info.json').write_text(json.dumps({'capability': _capability(), 'thread': 'thread-1',
        'sourceSha256': hashlib.sha256(stream.getvalue()).hexdigest(), 'engineRoot': str(engine_dir('slides'))}, indent=2))
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
