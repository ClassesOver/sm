"""PDF 表单 AI 专项：真实 HTTP/授权/引擎/Agno；默认 ScriptedModel。"""
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
from agno.models.response import ModelResponse
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeEditorContext, NativeScope
from smart_reporting.report_editor.native_pdf_form_ai import AgnoNativePDFFormPlanner
from smart_reporting.report_editor.native_pdf_form_ai_api import create_native_pdf_form_ai_router
from smart_reporting.report_editor.native_pdf_form_ai_tasks import NativePDFFormService
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel


def fixture() -> bytes:
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(600, 600))
    canvas.drawString(35, 550, 'Application: fill only explicitly selected fields.')
    canvas.acroForm.textfield(name='contact.name', value='Original', x=40, y=460, width=180, height=24)
    canvas.acroForm.checkbox(name='consent', checked=False, x=40, y=400)
    canvas.acroForm.choice(name='region', options=['north', 'south'], value='north', x=40, y=340, width=180, height=24)
    for value, y in [('basic', 280), ('pro', 240)]:
        canvas.acroForm.radio(name='plan', value=value, selected=value == 'basic', x=40, y=y)
    canvas.acroForm.textfield(name='secret', value='UNSELECTED_SECRET_729463', x=40, y=160, width=220, height=24)
    canvas.showPage()
    canvas.save()
    return stream.getvalue()


async def create_app(directory: Path, port: int) -> FastAPI:
    directory.mkdir(parents=True, exist_ok=True)
    content = fixture()
    (directory / 'source.pdf').write_bytes(content)
    model = await asyncio.to_thread(inspect_pdf, content, include_text=True)
    scope = NativeScope(database='smoke', companyId='company', userId='editor', threadId='pdf-ai-forms')
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(directory / 'workspace', secret='w' * 32))
    await workspace.awrite_bytes(bind_native_workspace(workspace, scope), 'native/source.pdf', content)
    context = NativeEditorContext(documentId='pdf-ai-forms', revision=1, format='pdf', origin='upload', scope=scope,
        sourceFile=ArtifactFile(path='native/source.pdf', size=len(content), sha256=hashlib.sha256(content).hexdigest(), mediaType='application/pdf'))

    class Repository:
        async def get_revision(self, document_id, revision, *, scope):
            if (document_id, revision, scope) == (context.document_id, 1, context.scope):
                return SimpleNamespace(status='saved', context=context)

    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='g' * 32)
    editor = NativeEditorService(workspace, Repository(), grants, report_editor=None, pdf_enabled=True, pdf_text_enabled=False)
    gate = {'mode': 'normal', 'calls': 0, 'blockedEntered': False, 'blockedCancelled': False, 'readPayloads': []}

    async def planner(**kwargs):
        gate['calls'] += 1
        if gate['mode'] == 'cancel':
            gate['blockedEntered'] = True
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                gate['blockedCancelled'] = True
                return {'answer': '迟到结果不得复活', 'operations': []}
        selected = kwargs['selected']
        assert 'UNSELECTED_SECRET_729463' not in json.dumps(selected)
        gate['readPayloads'].append(selected)
        values = {'contact.name': 'Lin', 'consent': True, 'region': 'south', 'plan': 'pro'}
        ops = [{'kind': 'setFormValue', 'fieldId': field['fieldId'],
                ('checked' if field['kind'] == 'checkbox' else 'value'): values[field['name']]} for field in selected]

        def call(name, args, identity):
            return ModelResponse(tool_calls=[{'id': identity, 'type': 'function', 'function': {
                'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}])

        return await AgnoNativePDFFormPlanner(ScriptedModel(id='pdf-form-browser', responses=[
            call('list_form_fields', {}, 'forms-read'),
            call('apply_ops', {'operations': ops, 'summary': '仅填写明确授权字段，等待采纳'}, 'forms-propose'),
            ModelResponse(content=json.dumps({'answer': '字段填写候选已生成，请核对实际预览后采纳。'}, ensure_ascii=False)),
        ]))(**kwargs)

    forms = NativePDFFormService(editor, planner=planner, enabled=True)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await forms.aclose()
        await workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    origin = f'http://127.0.0.1:{port}'
    static_root = Path(os.environ['PDF_AI_FORMS_STATIC_ROOT'])
    app.include_router(create_native_editor_router(grants, editor=editor, cookie_secure=False,
        allowed_origin=origin, ai_enabled=True, static_dir=static_root))
    app.include_router(create_native_pdf_form_ai_router(grants, editor=editor, forms=forms, allowed_origin=origin))
    app.mount('/reports/v1/editor/assets', StaticFiles(directory=static_root))
    requests = []

    @app.middleware('http')
    async def record(request: Request, call_next):
        body = await request.body() if request.method == 'POST' else b''
        response = await call_next(request)
        requests.append({'method': request.method, 'path': request.url.path, 'status': response.status_code,
            **({'body': json.loads(body)} if body and 'application/json' in request.headers.get('content-type', '') else {})})
        (directory / 'http-evidence.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2))
        return response

    @app.post('/__smoke__/mode/{mode}')
    async def mode(mode: str):
        assert mode in {'normal', 'cancel'}
        gate.update(mode=mode, blockedEntered=False, blockedCancelled=False)
        return {'ok': True}

    @app.get('/__smoke__/state')
    async def state():
        jobs = []
        for job in forms._jobs.values():
            value = forms._serialize(job)
            value['events'] = job.event_log.history
            if job.status == 'succeeded' and job.result:
                proposal = value['result']['proposal']
                receipt = await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=proposal['operations'])
                edited = receipt['content']
                digest = hashlib.sha256(edited).hexdigest()
                path = directory / (job.task_id + '-' + digest + '.pdf')
                path.write_bytes(edited)
                value.update(actualPatchedPath=str(path), actualPatchedSha256=digest,
                    independentReadback={name: {'value': str(field.get('/V', '')), 'kind': str(field.get('/FT', ''))}
                        for name, field in (PdfReader(BytesIO(edited)).get_fields() or {}).items()})
            jobs.append(value)
        return {**gate, 'jobs': jobs, 'requests': requests,
            'sourceSha256': hashlib.sha256(await editor.read_file(context)).hexdigest()}

    raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
    _, session = await grants.exchange(raw)
    app.state.smoke = {'editor': editor, 'context': context, 'forms': forms,
        'workspace': workspace, 'session': session, 'model': model}
    raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
    (directory / 'server-info.json').write_text(json.dumps({'openPath': f'/reports/v1/native/open/{raw}',
        'context': context.model_dump(mode='json', by_alias=True), 'sourceSha256': context.source_file.sha256, 'model': model}, ensure_ascii=False, indent=2))
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4302)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port, log_level='warning')
