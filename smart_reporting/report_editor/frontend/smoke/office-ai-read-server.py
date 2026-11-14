"""本地 Office 阅读验收：真实源文件/授权/HTTP/Agno；ScriptedModel 非真实 provider。"""
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
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NATIVE_MEDIA, NativeEditorContext, NativeScope
from smart_reporting.report_editor.native_office_read_tasks import NativeOfficeReadService
from smart_reporting.report_editor.native_slides_read_ai import AgnoNativeSlidesReadPlanner
from smart_reporting.report_editor.native_workbook_read_ai import AgnoNativeWorkbookReadPlanner
from smart_reporting.report_editor.service import InMemoryReportEditorRepository, ReportEditorGrantService
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.host_workspace import ReportingWorkspaceRegistry, ReportingWorkspaceRouter
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel


async def create_app(directory: Path, port: int) -> FastAPI:
    directory.mkdir(parents=True, exist_ok=True)
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(directory / 'workspace', secret='w' * 32))
    scope = NativeScope(database='smoke', companyId='company', userId='reader', threadId='office-ai-read')
    contexts = {}
    for kind in ('xlsx', 'pptx'):
        stream = BytesIO()
        if kind == 'xlsx':
            workbook = Workbook()
            workbook.active.title = '经营'
            workbook.active['A1'] = '收入42'
            workbook.active['B1'] = '费用12'
            workbook.save(stream)
        else:
            deck = Presentation()
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            for index, text in enumerate(('本季度收入42。', '费用12，现金流稳定。')):
                slide.shapes.add_textbox(Inches(1), Inches(index + 1), Inches(4), Inches(1)).text = text
            slide.notes_slide.notes_text_frame.text = '备注：下季度目标59。'
            deck.save(stream)
        content = stream.getvalue()
        (directory / ('source.' + kind)).write_bytes(content)
        context = NativeEditorContext(documentId='office-' + kind + '-smoke', revision=1, format=kind,
            origin='upload', scope=scope, sourceFile=ArtifactFile(path='native/source.' + kind,
                size=len(content), sha256=hashlib.sha256(content).hexdigest(), mediaType=NATIVE_MEDIA[kind]))
        contexts[context.document_id] = context
        await workspace.awrite_bytes(bind_native_workspace(workspace, scope), context.source_file.path, content)

    class ScopedRepository:
        async def get_revision(self, document_id, revision, *, scope):
            context = contexts.get(document_id)
            if context and revision == context.revision and scope == context.scope:
                return SimpleNamespace(status='saved', context=context)
            return None

    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='g' * 32)
    editor = NativeEditorService(workspace, ScopedRepository(), grants, office_enabled=False)

    def tool(identity, name, arguments):
        return ModelResponse(tool_calls=[{'id': identity, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}])

    async def planner(**kwargs):
        is_workbook = hasattr(kwargs['reader'], 'get_workbook_context')
        if is_workbook:
            calls = [tool('context', 'get_workbook_context', {}),
                tool('cells', 'read_cells', {'addresses': ['A1', 'B1'], 'sheetId': '经营'})]
            citations = ['经营!A1', '经营!B1']
            answer = '工作簿经营表：收入42，费用12；收入减费用为30。'
            planner_type = AgnoNativeWorkbookReadPlanner
        else:
            calls = [tool('context', 'get_presentation_context', {}), tool('slide', 'read_slide', {'slide_index': 0})]
            citations = ['0']
            answer = '演示文稿已提取文字：本季度收入42，费用12，现金流稳定。演讲者备注：下季度目标59。未读取图片视觉内容。'
            planner_type = AgnoNativeSlidesReadPlanner
        model = ScriptedModel(id='scripted-office-read-smoke', expected_tool_text='42' if is_workbook else '下季度目标59',
            responses=[*calls, ModelResponse(content=json.dumps({'answer': answer, 'citations': citations}, ensure_ascii=False))])
        return await planner_type(model)(**kwargs)

    ai = NativeOfficeReadService(editor, planners={'xlsx': planner, 'pptx': planner}, enabled=True)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await ai.aclose()
        await workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    origin = f'http://127.0.0.1:{port}'
    app.include_router(create_native_editor_router(grants, editor=editor, cookie_secure=False, allowed_origin=origin, ai_enabled=True))
    app.include_router(create_native_ai_router(grants, editor=editor, ai=None, office_read=ai, allowed_origin=origin))
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
        identities = {}
        for context in contexts.values():
            current = await editor.read_file(context)
            identities[context.format] = {'sourceSha256': hashlib.sha256(current).hexdigest(),
                'originalSha256': context.source_file.sha256}
        return {'identities': identities, 'editingEnabled': editor.office_enabled,
            'provider': 'ScriptedModel through actual Agno; not a real provider',
            'requests': requests, 'jobs': [ai._serialize(job) for job in ai._jobs.values()]}

    documents = {}
    for context in contexts.values():
        raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
        documents[context.format] = {'openPath': f'/reports/v1/native/open/{raw}',
            'sourceSha256': context.source_file.sha256, 'context': context.model_dump(mode='json', by_alias=True)}
    (directory / 'server-info.json').write_text(json.dumps({'documents': documents}, ensure_ascii=False, indent=2))
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4288)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.output_dir, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
