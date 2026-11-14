"""审阅候选浏览器验收：真实引擎、授权、HTTP、Agno；模型回合使用 ScriptedModel。"""
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
from zipfile import ZipFile

import uvicorn
from agno.models.response import ModelResponse
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_ai import NativeAIService
from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeEditorContext, NativeScope
from smart_reporting.report_editor.native_word_ai import (
    AgnoNativeWordProposalPlanner,
    word_candidate,
)
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.tests.test_docx_comment_reply import modern_source
from smart_reporting.reporting.tests.test_docx_text_revision_host import PARA, rewrite
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel


async def create_app(directory: Path, port: int) -> FastAPI:
    directory.mkdir(parents=True, exist_ok=True)
    content = rewrite(modern_source(), lambda name, data: data.replace(
        b'<w:sectPr', PARA.encode() + b'<w:sectPr', 1) if name == 'word/document.xml' else data)
    (directory / 'source.docx').write_bytes(content)
    source_model = inspect_docx(content)
    scope = NativeScope(database='smoke', companyId='company', userId='reviewer', threadId='word-ai-review')
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(directory / 'workspace', secret='w' * 32))
    await workspace.awrite_bytes(bind_native_workspace(workspace, scope), 'native/source.docx', content)
    context = NativeEditorContext(documentId='word-ai-review-smoke', revision=1, format='docx', origin='upload',
        scope=scope, sourceFile=ArtifactFile(path='native/source.docx', size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'))

    class ScopedRepository:
        async def get_revision(self, document_id, revision, *, scope):
            if (document_id, revision, scope) == (context.document_id, context.revision, context.scope):
                return SimpleNamespace(status='saved', context=context)

    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='g' * 32)
    editor = NativeEditorService(workspace, ScopedRepository(), grants, docx_enabled=True)
    planner_calls = []

    class Planner:
        async def plan_word(self, prompt, *, selected, session_id, user_id):
            planner_calls.append(session_id)
            target = selected[0]
            if target['selectionKind'] == 'revision':
                operation = {'kind': 'resolveTextRevision', 'blockId': target['blockId'],
                    'revisionId': target['revisionId'], 'action': 'accept'}
            elif '回复' in prompt.split('用户要求：', 1)[-1].split('\n', 1)[0]:
                operation = {'kind': 'replyComment', 'sourceId': target['sourceId'],
                    'targetId': target['targetId'], 'text': 'AI 审阅回复：已核实收入42。'}
            else:
                operation = {'kind': 'resolveComment', 'sourceId': target['sourceId'],
                    'targetId': target['targetId'], 'done': False}
            checked = word_candidate([operation], selected)

            def call(identity, name, arguments):
                return ModelResponse(tool_calls=[{'id': identity, 'type': 'function', 'function': {
                    'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}])

            scripted = ScriptedModel(id='word-review-browser', responses=[
                call('review-context', 'get_document_context', {}),
                call('review-read', 'read_review_targets', {'review_ids': [target['reviewId']]}),
                call('review-propose', 'propose_operations', {'summary': '审阅候选已生成，等待采纳',
                                                           'operations': [operation]}),
                ModelResponse(content=json.dumps({'summary': '审阅候选已生成，等待采纳', 'operations': [
                    {'kind': op['kind'], 'arguments': {key: value for key, value in op.items() if key != 'kind'}}
                    for op in checked]}, ensure_ascii=False)),
            ])
            return await AgnoNativeWordProposalPlanner(scripted).plan_word(
                prompt, selected=selected, session_id=session_id, user_id=user_id)

    ai = NativeAIService(editor, planner=Planner(), enabled=True)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await ai.aclose()
        await workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    origin = f'http://127.0.0.1:{port}'
    static_root = Path(os.environ.get('WORD_AI_REVIEW_STATIC_ROOT',
        str(Path(__file__).resolve().parents[2] / 'static')))
    app.include_router(create_native_editor_router(grants, editor=editor, cookie_secure=False,
                                                  allowed_origin=origin, ai_enabled=True, static_dir=static_root))
    app.include_router(create_native_ai_router(grants, editor=editor, ai=ai, allowed_origin=origin))
    app.mount('/reports/v1/editor/assets', StaticFiles(directory=static_root))
    requests = []
    hold_start = os.environ.get('WORD_AI_REVIEW_HOLD_START') == '1'
    held_starts = 0
    release_start = asyncio.Event()

    @app.middleware('http')
    async def record(request: Request, call_next):
        nonlocal held_starts
        body = await request.body() if request.method == 'POST' else b''
        if hold_start and request.url.path.endswith('/api/ai/start'):
            held_starts += 1
            await release_start.wait()
            release_start.clear()
        response = await call_next(request)
        requests.append({'method': request.method, 'path': request.url.path, 'status': response.status_code,
            **({'body': json.loads(body)} if body and 'application/json' in request.headers.get('content-type', '') else {})})
        (directory / 'http-evidence.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2))
        return response

    @app.get('/__smoke__/state')
    async def state():
        current = await editor.read_file(context)
        jobs = []
        for job in ai._jobs.values():
            value = ai._serialize(job)
            value['events'] = job.event_log.history
            if job.accepted and job.proposal:
                operations = job.proposal['operations']
                patched = await asyncio.to_thread(patch_docx, content, operations)
                path = directory / (job.edit_id + '-' + hashlib.sha256(patched).hexdigest() + '.docx')
                path.write_bytes(patched)
                model = await asyncio.to_thread(inspect_docx, patched)
                with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(patched)) as after:
                    value['changedParts'] = [name for name in after.namelist()
                        if not name.endswith('/') and
                        (name not in before.namelist() or before.read(name) != after.read(name))]
                value['actualPatchedModel'] = model
                value['actualPatchedPath'] = str(path)
                value['actualPatchedSha256'] = hashlib.sha256(patched).hexdigest()
            jobs.append(value)
        return {'sourceSha256': hashlib.sha256(current).hexdigest(), 'jobs': jobs, 'requests': requests,
                'heldStarts': held_starts, 'plannerCalls': planner_calls}

    @app.post('/__smoke__/release-start')
    async def release_held_start():
        release_start.set()
        return {'released': True}

    paths = {}
    for name in ('reply', 'resolve', 'revision'):
        raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
        paths[name] = f'/reports/v1/native/open/{raw}'
    (directory / 'server-info.json').write_text(json.dumps({'openPaths': paths,
        'sourceSha256': context.source_file.sha256, 'model': source_model}, ensure_ascii=False, indent=2))
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4289)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port,
                log_level='warning')
