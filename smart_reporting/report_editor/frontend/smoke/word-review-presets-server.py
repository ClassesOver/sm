"""Real HTTP/Agno/OOXML save probe; deterministic model and in-memory repositories."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from agno.models.response import ModelResponse
from docx import Document
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_ai import NativeAIService
from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_models import NativeEditorContext, NativeScope, NativeRevision
from smart_reporting.report_editor.native_publication import NativePublicationService
from smart_reporting.report_editor.native_word_ai import AgnoNativeWordProposalPlanner
from smart_reporting.report_editor.service import InMemoryReportEditorRepository, ReportEditorGrantService
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.docx_native import inspect_docx
from smart_reporting.reporting.delivery.publishing import ReportArtifactPersistenceService, ReportDownloadGrantService, ReportDownloadHttpService
from smart_reporting.reporting.host_workspace import ReportingWorkspaceRegistry, ReportingWorkspaceRouter
from smart_reporting.reporting.tests.delivery_fakes import InMemoryDownloadGrantRepository, InMemoryReportArtifactRepository
from smart_reporting.reporting.tests.test_native_publication_nonblocking import Repository
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel

async def create_app(directory: Path, static: Path, port: int):
    directory.mkdir(parents=True, exist_ok=True)
    resume_directory = Path(os.environ['WORD_FAMILIES_RESUME_DIRECTORY']) if os.environ.get('WORD_FAMILIES_RESUME_DIRECTORY') else None
    document = Document()
    document.add_paragraph('本季度收入42，费用12。')
    document.add_paragraph('现金流稳定。')
    document.sections[0].header.paragraphs[0].text = 'HEADER KEEP'
    document.sections[0].footer.paragraphs[0].text = 'FOOTER KEEP'
    stream = BytesIO(); document.save(stream); content = stream.getvalue()
    if os.environ.get('WORD_PRESETS_REOPEN_FILE'):
        content = Path(os.environ['WORD_PRESETS_REOPEN_FILE']).read_bytes()
    if resume_directory:
        content = (resume_directory / 'source.docx').read_bytes()
    (directory / 'source.docx').write_bytes(content)
    scope = NativeScope(database='smoke', companyId='company', userId='reviewer', threadId='word-presets')
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(directory / 'workspace', secret='w' * 32))
    await workspace.awrite_bytes(bind_native_workspace(workspace, scope), 'native/source.docx', content)
    context = NativeEditorContext(documentId='word-presets', revision=1, format='docx', origin='upload', scope=scope, sourceFile=ArtifactFile(path='native/source.docx', size=len(content), sha256=hashlib.sha256(content).hexdigest(), mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'))
    class ScopedRepository(Repository):
        async def get_revision(self, document_id, revision, *, scope):
            if document_id != context.document_id or scope != context.scope:
                return None
            if revision == 1:
                return SimpleNamespace(status='saved', context=context)
            return next((row for row in self.rows.values() if row.revision == revision), None)
    repository = ScopedRepository()
    open_context = context
    if resume_directory:
        for name in ('content-r2','protected-r3'):
            receipt=json.loads((resume_directory/(name+'-saved.json')).read_text())
            raw=(resume_directory/(name+'.docx')).read_bytes()
            artifact=ArtifactFile.model_validate({k:v for k,v in receipt['artifacts']['word'].items() if k!='downloadUrl'})
            assert hashlib.sha256(raw).hexdigest()==artifact.sha256
            await workspace.awrite_bytes(bind_native_workspace(workspace,scope),artifact.path,raw)
            restored=context.model_copy(update={'revision':receipt['revision'],'parent_revision':receipt['parentRevision'],'source_file':artifact})
            rid='restored-'+str(receipt['revision'])
            repository.rows[rid]=NativeRevision(documentId=context.document_id,revision=receipt['revision'],scope=scope,parentRevision=receipt['parentRevision'],requestId=rid,requestSha256='a'*64,status='saved',createdAt=datetime.now(UTC),context=restored)
            (directory/(name+'.docx')).write_bytes(raw)
            (directory/(name+'-saved.json')).write_text(json.dumps(receipt))
            open_context=restored
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='g' * 32)
    download_grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    artifacts = InMemoryReportArtifactRepository()
    origin = f'http://127.0.0.1:{port}'
    publication = NativePublicationService(repository, workspace, download_grants, grants, artifact_persistence=ReportArtifactPersistenceService(artifacts, workspace), public_base_url=origin)
    downloads = ReportDownloadHttpService(download_grants, artifacts, workspace_service=workspace)
    editor = NativeEditorService(workspace, repository, grants, report_editor=None, publication=publication, docx_enabled=True)
    calls = []
    class Planner:
        async def plan_word(self, prompt, *, selected, session_id, user_id):
            calls.append({'prompt': prompt, 'selected': selected})
            operations = [{'kind':'replaceParagraph','blockId':item['blockId'],'text':'Translated paragraph '+str(index+1)} for index,item in enumerate(selected)]
            def call(identity, name, arguments):
                return ModelResponse(tool_calls=[{'id':identity,'type':'function','function':{'name':name,'arguments':json.dumps(arguments, ensure_ascii=False)}}])
            model = ScriptedModel(id='word-presets-smoke', responses=[call('context','get_document_context',{}),call('read','read_blocks',{'block_ids':[item['blockId'] for item in selected]}),call('propose','propose_operations',{'summary':'翻译候选，等待采纳','operations':operations}),ModelResponse(content=json.dumps({'summary':'翻译候选，等待采纳','operations':[{'kind':op['kind'],'arguments':{k:v for k,v in op.items() if k!='kind'}} for op in operations]}, ensure_ascii=False))])
            return await AgnoNativeWordProposalPlanner(model).plan_word(prompt,selected=selected,session_id=session_id,user_id=user_id)
    ai = NativeAIService(editor, planner=Planner(), enabled=True)
    @asynccontextmanager
    async def lifespan(app):
        yield
        await ai.aclose(); await workspace.registry.aclose()
    app = FastAPI(lifespan=lifespan)
    app.include_router(create_native_editor_router(grants,editor=editor,download_service=downloads,cookie_secure=False,allowed_origin=origin,ai_enabled=True,static_dir=static))
    app.include_router(create_native_ai_router(grants,editor=editor,ai=ai,allowed_origin=origin))
    app.mount('/reports/v1/editor/assets',StaticFiles(directory=static))
    requests=[]
    @app.middleware('http')
    async def record(request:Request,call_next):
        body=await request.body() if request.method=='POST' else b''
        response=await call_next(request)
        requests.append({'method':request.method,'path':request.url.path,'status':response.status_code,**({'body':json.loads(body)} if body and 'application/json' in request.headers.get('content-type','') else {})})
        (directory/'http-evidence.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2))
        return response
    @app.get('/__smoke__/state')
    async def state():
        return {'requests':requests,'calls':calls,'revisions':[row.model_dump(mode='json',by_alias=True) for row in repository.rows.values()]}
    token,_=await grants.issue(open_context,capabilities=editor.capabilities(open_context))
    (directory/'server-info.json').write_text(json.dumps({'openPath':'/reports/v1/native/open/'+token,'model':inspect_docx(content)},ensure_ascii=False,indent=2))
    return app
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--static',type=Path,required=True);parser.add_argument('--port',type=int,default=4298);args=parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory,args.static,args.port)),host='127.0.0.1',port=args.port,log_level='warning')
