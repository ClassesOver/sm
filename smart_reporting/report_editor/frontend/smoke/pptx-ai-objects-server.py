"""PPTX 表格/图表 AI 候选验收：真实授权、引擎和 Agno，模型回合使用 ScriptedModel。"""
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
from lxml import etree
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Inches

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import (
    NATIVE_MEDIA,
    NativeEditorContext,
    NativeScope,
)
from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.report_editor.slides_ai import AgnoSlidesProposalPlanner
from smart_reporting.report_editor.slides_ai_native_operations import NativeSlidesAIProposal
from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
from smart_reporting.report_editor.slides_native_ai_api import create_native_slides_ai_router
from smart_reporting.reporting.agent import create_reporting_generator_agent
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel


async def create_app(directory: Path, port: int) -> FastAPI:
    directory.mkdir(parents=True, exist_ok=True)
    presets = os.environ.get('PPTX_AI_PRESETS_SMOKE') == '1'
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(Inches(.4), Inches(.2), Inches(6), Inches(.5)).text = '经营数据：收入42，费用17。'
    table = slide.shapes.add_table(2, 2, Inches(.5), Inches(1), Inches(3), Inches(1.2))
    table.name = '经营表'
    for (row, col), value in {(0, 0): '项目', (0, 1): '金额', (1, 0): '收入', (1, 1): '42'}.items():
        table.table.cell(row, col).text = value
    if presets:
        other = deck.slides.add_slide(deck.slide_layouts[6])
        other.shapes.add_textbox(Inches(.4), Inches(.2), Inches(6), Inches(.5)).text = '第二页错别自：收入42。'
    if os.environ.get('PPTX_AI_NOTES_SMOKE') == '1':
        slide.notes_slide.notes_text_frame.text = '原演讲者备注：收入42，费用17。'
        other = deck.slides.add_slide(deck.slide_layouts[6])
        other.shapes.add_textbox(Inches(.4), Inches(.2), Inches(6), Inches(.5)).text = '未授权页秘密：保留不变'
        other.notes_slide.notes_text_frame.text = '未授权备注秘密：不可读取或修改'
        master_rel = next(rel for rel in deck.part.rels.values() if rel.reltype == RT.NOTES_MASTER)
        master_ids = etree.Element(qn('p:notesMasterIdLst'))
        etree.SubElement(master_ids, qn('p:notesMasterId')).set(qn('r:id'), master_rel.rId)
        deck._element.insert(deck._element.index(deck._element.find(qn('p:sldMasterIdLst'))) + 1, master_ids)
    stream = BytesIO()
    deck.save(stream)
    content = await asyncio.to_thread(patch_office, 'pptx', stream.getvalue(), [{'kind': 'editSlides',
        'charts': [{'slideIndex': 0, 'kind': 'bar', 'categories': ['收入', '费用'],
                    'series': [{'name': '本期', 'values': [42, 17]}]}]}])
    (directory / 'source.pptx').write_bytes(content)
    source_model = await asyncio.to_thread(inspect_office, 'pptx', content)
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(directory / 'workspace', secret='w' * 32))
    scope = NativeScope(database='smoke', companyId='company', userId='editor', threadId='pptx-ai-objects')
    await workspace.awrite_bytes(bind_native_workspace(workspace, scope), 'native/source.pptx', content)
    context = NativeEditorContext(documentId='pptx-ai-objects', revision=1, format='pptx', origin='upload',
        scope=scope, sourceFile=ArtifactFile(path='native/source.pptx', size=len(content),
            sha256=hashlib.sha256(content).hexdigest(), mediaType=NATIVE_MEDIA['pptx']))

    class Repository:
        async def get_revision(self, document_id, revision, *, scope):
            if (document_id, revision, scope) == (context.document_id, 1, context.scope):
                return SimpleNamespace(status='saved', context=context)

    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='g' * 32)
    editor = NativeEditorService(workspace, Repository(), grants, report_editor=None, office_enabled=True)

    class Planner:
        async def plan_slides(self, prompt, *, deck, scope, current_order, preview, session_id, user_id):
            authorized = [element for slide in deck['slides'] for element in slide['elements']
                          if element.get('editable') is True]
            table = next((element for element in authorized if element['type'] == 'table'), None)
            chart = next((element for element in authorized if element['type'] == 'chart'), None)
            proposal = {'summary': '仅修改授权经营数据，等待采纳', 'edits': [], 'order': current_order}
            if scope == 'notes':
                proposal['notesEdits'] = [{'slideIndex': 0, 'text': '演讲稿候选：本期收入42，费用17；请重点说明收入与费用结构。'}]
            if table:
                proposal['tableCells'] = [{'slideIndex': 0, 'elementId': table['id'],
                                           'row': 1, 'col': 1, 'text': '84'}]
            if chart:
                proposal['chartEdits'] = [{'slideIndex': 0, 'elementId': chart['id'],
                    'categories': ['收入', '费用'], 'series': [{'name': '本期', 'values': [84, 17]}]}]
            if presets:
                # 测试模型只产生冻结文字候选；仍经真实 Agno 工具及引擎独立预览。
                proposal = {'summary': '整稿校对候选' if scope == 'deck' else '当前页英语翻译候选',
                            'edits': [], 'order': current_order}
                for source_slide in deck['slides']:
                    for element in source_slide['elements']:
                        if element.get('editable') is not True or element['type'] not in ('text', 'shape'):
                            continue
                        text = element.get('text', '')
                        replacement = text.replace('错别自', '错别字') if scope == 'deck' else 'Draft revenue 42, expenses 17.'
                        if replacement != text:
                            proposal['edits'].append({'slideIndex': source_slide['slideIndex'],
                                'elementId': element['id'], 'text': replacement})
                with (directory / 'planner-calls.jsonl').open('a') as output:
                    output.write(json.dumps({'scope': scope, 'prompt': prompt, 'deck': deck}, ensure_ascii=False) + '\n')

            def call(identity, name, arguments):
                return ModelResponse(tool_calls=[{'id': identity, 'type': 'function', 'function': {
                    'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}])

            model = ScriptedModel(id='pptx-ai-objects-browser', responses=[
                call('objects-context', 'get_presentation_context', {}),
                *(call('objects-read' + ('-' + str(index) if presets else ''), 'read_slide', {'slide_index': index})
                  for index in (sorted({0, *(edit['slideIndex'] for edit in proposal['edits'])}) if presets else [0])),
                call('objects-propose', 'propose_operations', {'proposal': proposal}),
                ModelResponse(content='候选已预览，等待用户采纳。'),
            ])
            agent = create_reporting_generator_agent(model=model, name='pptx-ai-objects-browser',
                output_schema=NativeSlidesAIProposal,
                role='仅编辑授权对象，先读取并提交候选。')
            return await AgnoSlidesProposalPlanner(agent).plan_slides(prompt, deck=deck, scope=scope,
                current_order=current_order, preview=preview, session_id=session_id, user_id=user_id)

    ai = NativeSlidesAIService(editor, planner=Planner(), enabled=True)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await ai.aclose()
        await workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    origin = f'http://127.0.0.1:{port}'
    static_root = Path(os.environ['PPTX_AI_OBJECTS_STATIC_ROOT'])
    app.include_router(create_native_editor_router(grants, editor=editor, cookie_secure=False,
        allowed_origin=origin, ai_enabled=True, static_dir=static_root))
    app.include_router(create_native_slides_ai_router(grants, editor=editor, ai=ai, allowed_origin=origin))
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

    @app.get('/__smoke__/state')
    async def state():
        current = await editor.read_file(context)
        jobs = []
        for job in ai._jobs.values():
            value = ai._serialize(job)
            value['events'] = job.event_log.history
            if job.accepted and job.proposal:
                start = next(item['body'] for item in requests if item['path'].endswith('/slides-ai/start')
                    and item.get('body', {}).get('clientRequestId') == job.client_request_id)
                operations = ai._combined_operations(context, start['operations'], job.proposal['operations'])
                edited = await asyncio.to_thread(patch_office, 'pptx', content, operations)
                digest = hashlib.sha256(edited).hexdigest()
                path = directory / (job.edit_id + '-' + digest + '.pptx')
                path.write_bytes(edited)
                actual = Presentation(BytesIO(edited))
                value['independentReadback'] = {
                    'notes': [slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else '' for slide in actual.slides],
                    'texts': [[shape.text for shape in slide.shapes if shape.has_text_frame] for slide in actual.slides],
                    'tables': [[[cell.text for cell in row.cells] for row in shape.table.rows]
                        for shape in actual.slides[0].shapes if shape.has_table],
                    'charts': [{'categories': [item.label for item in shape.chart.plots[0].categories],
                        'series': [{'name': series.name, 'values': list(series.values)} for series in shape.chart.series]}
                        for shape in actual.slides[0].shapes if shape.has_chart]}
                value.update(actualPatchedPath=str(path), actualPatchedSha256=digest)
            jobs.append(value)
        return {'sourceSha256': hashlib.sha256(current).hexdigest(), 'jobs': jobs, 'requests': requests}

    paths = {}
    for name in (('presets',) if presets else ('notes',) if os.environ.get('PPTX_AI_NOTES_SMOKE') == '1' else ('table', 'chart')):
        raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
        paths[name] = f'/reports/v1/native/open/{raw}'
    (directory / 'server-info.json').write_text(json.dumps({'openPaths': paths,
        'sourceSha256': context.source_file.sha256, 'model': source_model}, ensure_ascii=False, indent=2))
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4290)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port)), host='127.0.0.1', port=args.port,
                log_level='warning')
