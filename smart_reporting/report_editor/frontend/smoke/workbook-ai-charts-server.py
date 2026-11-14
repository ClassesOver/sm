"""Real XLSX AI routes/Agno/writer/save/download; scoped memory repository."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from runpy import run_path

import uvicorn
from agno.agent import Agent
from agno.models.response import ModelResponse
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeArtifacts
from smart_reporting.report_editor.workbook_ai import AgnoWorkbookProposalPlanner
from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
from smart_reporting.report_editor.workbook_native_ai_api import create_native_workbook_ai_router
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
from smart_reporting.reporting.tests.test_native_pdf_extract import extract_fixture
from smart_reporting.reporting.tests.test_workbook_ai_charts import (
    call,
    deletion,
    edit,
    source_with_two_charts,
)


async def create_app(directory: Path, port: int, *, source: bytes | None = None):
    f = await extract_fixture(directory / 'runtime')
    source = await asyncio.to_thread(source_with_two_charts) if source is None else source
    if os.environ.get('WORKBOOK_AI_CHARTS_SOURCE_LABEL_STYLE') == '1':
        source = run_path(str(Path(__file__).with_name('workbook-chart-label-style-fixture.py')))['styled_ai_source'](source)
    identity = ArtifactFile(path='native/source.xlsx', size=len(source), sha256=hashlib.sha256(source).hexdigest(),
        mediaType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    await f.workspace.awrite_bytes(f.thread, identity.path, source)
    f.parent = f.parent.model_copy(update={'format': 'xlsx', 'source_file': identity})
    repository = run_path(str(Path(__file__).with_name('pdf-form-design-server.py')))['SaveRepository']()
    row = f.repository.revisions[f.parent.document_id]
    repository.revisions[f.parent.document_id] = row.model_copy(update={
        'context': f.parent, 'artifacts': NativeArtifacts(xlsx=identity)})
    f.editor.repository = repository
    f.editor.office_enabled = True
    f.publication.repository = repository
    f.publication.public_base_url = origin = f'http://127.0.0.1:{port}'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'source.xlsx').write_bytes(source)
    planner_calls = []

    class Planner:
        async def plan_workbook(self, prompt, **kwargs):
            # The scripted model substitutes only for the provider, not the tools,
            # authorization, real writer, candidate service or publication chain.
            instruction = prompt.split('用户要求：', 1)[1].split('\n', 1)[0]
            operation = deletion() if '删除' in instruction else edit(title='Updated', chartType='bar', legend='bottom')
            if os.environ.get('WORKBOOK_AI_CHARTS_SOURCE_DATA') == '1':
                operation = ({'op': 'add_chart', 'sheetId': 'Sheet', 'chartType': 'line', 'dataRange': 'A1:B3',
                              'title': '实际来源收入', 'anchorCell': 'E20'} if '新增' in instruction else {
                    'op': 'edit_chart', 'chartPath': 'xl/charts/chart3.xml', 'title': '第二季度收入',
                    'seriesData': [{'index': 0, 'name': '收入', 'valuesRange': 'B3', 'categoriesRange': 'A3'}],
                })
            if '轴标题' in instruction and operation.get('kind') == 'applyChartEdits':
                operation['arguments']['edits'][0]['axisTitles'] = {'category': 'Quarter', 'value': 'Amount (USD)'}
            if '数值范围' in instruction and operation.get('kind') == 'applyChartEdits':
                operation['arguments']['edits'][0]['valueAxis'] = {'min': 5, 'max': 25}
            if '恢复自动范围' in instruction and operation.get('kind') == 'applyChartEdits':
                operation['arguments']['edits'][0]['valueAxis'] = {'min': None, 'max': None}
            if '数据标签' in instruction and operation.get('kind') == 'applyChartEdits':
                operation['arguments']['edits'][0].update(dataLabels='value', dataLabelPosition='center', dataLabelFormat='0.0')
            scripted = ScriptedModel(id='chart-browser', responses=[
                call('read_sheet_features', {'sheetId': 'Sheet'}, 'features'),
                call('load_guide', {'guides': ['charts']}, 'guide'),
                *([call('read_range', {'sheetId': 'Sheet', 'range': 'A1:B3'}, 'data')] if os.environ.get('WORKBOOK_AI_CHARTS_SOURCE_DATA') == '1' else []),
                call('propose_operations', {'operations': [operation], 'summary': instruction}, 'proposal'),
                ModelResponse(content='候选等待明确采纳和保存。'),
            ])
            proposal = await AgnoWorkbookProposalPlanner(Agent(model=scripted)).plan_workbook(prompt, **kwargs)
            planner_calls.append({'instruction': instruction, 'operations': proposal.engine_operations(),
                                  'toolMessages': [str(m.content) for turn in scripted.seen for m in turn if m.role == 'tool']})
            (directory / 'planner-evidence.json').write_text(json.dumps(planner_calls, ensure_ascii=False, indent=2))
            return proposal

    ai = NativeWorkbookAIService(f.editor, planner=Planner(), enabled=True)
    static = run_path(str(Path(__file__).with_name('pdf_smoke_static.py')))['pdf_smoke_static_directory']()
    requests = []

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await ai.aclose()
        await f.workspace.registry.aclose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(create_native_editor_router(f.publication.editor_grants, editor=f.editor,
        download_service=f.downloads, cookie_secure=False, allowed_origin=origin, static_dir=static, ai_enabled=True))
    app.include_router(create_native_workbook_ai_router(f.publication.editor_grants, editor=f.editor, ai=ai, allowed_origin=origin))
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
        return {'sourceSha256': hashlib.sha256(actual).hexdigest(), 'savedRevisions': len(repository.saved),
                'plannerCalls': len(planner_calls), 'requests': requests}

    raw, _ = await f.publication.editor_grants.issue(f.parent, capabilities=f.editor.capabilities(f.parent))
    (directory / 'server-info.json').write_text(json.dumps({'openPath': f'/reports/v1/native/open/{raw}',
        'sourceSha256': identity.sha256, 'context': f.parent.model_dump(mode='json', by_alias=True)}, indent=2))
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4353)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory, args.port,
        source=args.source.read_bytes() if args.source else None)), host='127.0.0.1', port=args.port, log_level='warning')
