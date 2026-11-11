"""本地 Word 只读验收：真实 DOCX/HTTP/授权/Agno；ScriptedModel 非真实 provider。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from agno.models.response import ModelResponse
from docx import Document
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeEditorContext, NativeScope
from smart_reporting.report_editor.native_word_read_ai import AgnoNativeWordReadPlanner
from smart_reporting.report_editor.native_word_read_tasks import NativeWordReadService
from smart_reporting.report_editor.service import InMemoryReportEditorRepository, ReportEditorGrantService
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.docx_native import inspect_docx
from smart_reporting.reporting.host_workspace import ReportingWorkspaceRegistry, ReportingWorkspaceRouter
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel


async def create_app(directory: Path, port: int) -> FastAPI:
    directory.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_paragraph('本季度收入为42，费用为12。')
    document.add_paragraph('经营说明：现金流稳定，下一季度继续控制费用。 Cash flow stable.')
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = '净收益'
    table.cell(0, 1).text = '30'
    stream = BytesIO()
    document.save(stream)
    content = stream.getvalue()
    (directory / 'source.docx').write_bytes(content)
    source_model = inspect_docx(content)
    all_ids = [block['blockId'] for block in source_model['blocks']]
    selection_id = all_ids[1]
    scope = NativeScope(database='smoke', companyId='company', userId='reader', threadId='word-ai-read')
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(directory / 'workspace', secret='w' * 32))
    await workspace.awrite_bytes(bind_native_workspace(workspace, scope), 'native/source.docx', content)
    context = NativeEditorContext(documentId='word-ai-smoke', revision=1, format='docx', origin='upload', scope=scope,
        sourceFile=ArtifactFile(path='native/source.docx', size=len(content), sha256=hashlib.sha256(content).hexdigest(),
            mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'))

    class ScopedRepository:
        async def get_revision(self, document_id, revision, *, scope):
            if document_id == context.document_id and revision == context.revision and scope == context.scope:
                return SimpleNamespace(status='saved', context=context)
            return None

    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='g' * 32)
    editor = NativeEditorService(workspace, ScopedRepository(), grants, report_editor=None, docx_enabled=False)

    async def planner(**kwargs):
        selected = kwargs['reader'].scope == 'selection'
        ids = [selection_id] if selected else all_ids
        expected = 'Cash flow stable.' if selected else '42'
        answer = ('选中段落说明现金流稳定，下一季度继续控制费用。' if selected else
            '整篇正文：本季度收入为42，费用为12，表格净收益为30；现金流稳定，下季度继续控制费用。')
        def tool(identity, name, arguments):
            return ModelResponse(tool_calls=[{'id': identity, 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}])
        model = ScriptedModel(id='scripted-word-read-smoke', expected_tool_text=expected, responses=[
            tool('context', 'get_document_context', {}),
            tool('blocks', 'read_blocks', {'block_ids': ids}),
            ModelResponse(content=json.dumps({'answer': answer, 'citations': ids}, ensure_ascii=False)),
        ])
        return await AgnoNativeWordReadPlanner(model)(**kwargs)

    ai = NativeWordReadService(editor, planner=planner, enabled=True)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await ai.aclose()
        await workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    origin = f'http://127.0.0.1:{port}'
    app.include_router(create_native_editor_router(grants, editor=editor, cookie_secure=False, allowed_origin=origin, ai_enabled=True))
    app.include_router(create_native_ai_router(grants, editor=editor, ai=None, word_read=ai, allowed_origin=origin))
    app.mount('/reports/v1/editor/assets', StaticFiles(directory=Path(__file__).resolve().parents[2] / 'static'))
    requests = []

    @app.middleware('http')
    async def record(request: Request, call_next):
        body = await request.body() if request.method == 'POST' else b''
        response = await call_next(request)
        requests.append({'method': request.method, 'path': request.url.path, 'status': response.status_code,
            **({'body': json.loads(body)} if body and request.headers.get('content-type', '').startswith('application/json') else {})})
        (directory / 'http-evidence.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2))
        return response

    @app.get('/__smoke__/state')
    async def state():
        current = await editor.read_file(context)
        return {'sourceSha256': hashlib.sha256(current).hexdigest(), 'originalSha256': context.source_file.sha256,
            'editingEnabled': editor.docx_enabled, 'provider': 'ScriptedModel through actual Agno; not a real provider',
            'requests': requests, 'jobs': [ai._serialize(job) for job in ai._jobs.values()]}

    raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
    (directory / 'server-info.json').write_text(json.dumps({'openPath': f'/reports/v1/native/open/{raw}',
        'sourceSha256': context.source_file.sha256, 'allBlockIds': all_ids, 'selectionBlockId': selection_id,
        'selectionText': '经营说明：现金流稳定，下一季度继续控制费用。 Cash flow stable.',
        'context': context.model_dump(mode='json', by_alias=True)}, ensure_ascii=False, indent=2))
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', '--directory', dest='directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4287)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
