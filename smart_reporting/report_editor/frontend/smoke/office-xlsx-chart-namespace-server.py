"""真实Native导入/保存/签名下载宿主；持久化仓储复用显式内存夹具。"""
import argparse
import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from runpy import run_path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from smart_reporting.report_editor.native import NativeEditorService
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_import import NativeImportService
from smart_reporting.report_editor.native_models import NativeScope
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication


async def create_app(directory, port, static_root, selected_cases=('default', 'arbitrary', 'mixed')):
    scripts = Path(__file__).parent
    sources = run_path(str(scripts / 'office-xlsx-chart-namespace-verify.py'))['create_sources'](directory, selected_cases)
    repository = run_path(str(scripts / 'pdf-form-design-server.py'))['SaveRepository']()
    publication, _, downloads = await create_publication(directory / 'runtime')
    publication.repository = repository; publication.public_base_url = f'http://127.0.0.1:{port}'
    editor = NativeEditorService(publication.workspace, repository, publication.editor_grants, report_editor=None, office_enabled=True, publication=publication)
    importer = NativeImportService(publication.workspace, repository, publication.editor_grants)
    cases = {}
    for case, identity in sources.items():
        scope = NativeScope(database='smoke', companyId='fixture-company', userId='fixture-editor', threadId=f'xlsx-chart-namespace-{case}')
        opened = await importer.import_file(scope, Path(identity['source']).read_bytes(), request_id=f'upload-{case}')
        cases[case] = {**identity, **opened}
    requests = []

    @asynccontextmanager
    async def lifespan(_):
        yield
        await publication.workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(create_native_editor_router(publication.editor_grants, editor=editor, download_service=downloads, cookie_secure=False, allowed_origin=publication.public_base_url, static_dir=static_root, ai_enabled=True))
    app.mount('/reports/v1/editor/assets', StaticFiles(directory=static_root))

    @app.get('/favicon.ico')
    async def favicon():
        return Response(status_code=204)

    @app.middleware('http')
    async def record(request: Request, call_next):
        body = await request.body() if request.method == 'POST' else b''
        response = await call_next(request)
        requests.append({'method': request.method, 'path': request.url.path, 'status': response.status_code,
                         **({'body': json.loads(body)} if body and 'application/json' in request.headers.get('content-type', '') else {})})
        (directory / 'http-evidence.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2))
        return response

    @app.get('/__smoke__/state')
    async def state():
        rows = []
        for (document, revision), saved in repository.saved.items():
            content = await editor.read_file(saved.context)
            case = next(name for name, info in cases.items() if info['documentId'] == document)
            (directory / case / f'revision-{revision}.xlsx').write_bytes(content)
            rows.append({'case': case, 'documentId': document, 'revision': revision, 'parentRevision': saved.parent_revision, 'sha256': hashlib.sha256(content).hexdigest(), 'context': saved.context.model_dump(mode='json', by_alias=True)})
        return {'saved': rows, 'requests': requests, 'fixtureBoundary': '内存修订仓储；真实NativeService/Node/签名下载，AI候选另由浏览器HTTP夹具提供'}

    (directory / 'server-info.json').write_text(json.dumps({'cases': cases, 'origin': publication.public_base_url}, ensure_ascii=False, indent=2))
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--directory', type=Path, required=True); parser.add_argument('--port', type=int, required=True); parser.add_argument('--static-root', type=Path, required=True)
    parser.add_argument('--cases', default='default,arbitrary,mixed')
    args = parser.parse_args(); args.directory.mkdir(parents=True, exist_ok=True)
    uvicorn.run(asyncio.run(create_app(args.directory, args.port, args.static_root, args.cases.split(','))), host='127.0.0.1', port=args.port, log_level='warning')
