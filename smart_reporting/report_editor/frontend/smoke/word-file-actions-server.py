"""Real native HTTP/import/publication routes with scoped in-memory smoke repositories."""
from __future__ import annotations
import argparse,asyncio,hashlib,json
from contextlib import asynccontextmanager
from datetime import UTC,datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import uvicorn
from docx import Document
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from smart_reporting.report_editor.native import NativeEditorService
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_import import NativeImportService
from smart_reporting.report_editor.native_models import NativeArtifacts,NativeDocument,NativeEditorContext,NativeRevision,NativeScope,NativeSource,NativeValidation,native_digest
from smart_reporting.report_editor.native_publication import NativePublicationService
from smart_reporting.report_editor.native_repository import NativeRepositoryConflict
from smart_reporting.report_editor.service import InMemoryReportEditorRepository,ReportEditorGrantService
from smart_reporting.reporting.delivery.publishing import ReportArtifactPersistenceService,ReportDownloadGrantService,ReportDownloadHttpService
from smart_reporting.reporting.host_workspace import ReportingWorkspaceRegistry,ReportingWorkspaceRouter
from smart_reporting.reporting.tests.delivery_fakes import InMemoryDownloadGrantRepository,InMemoryReportArtifactRepository

class Repository:
    def __init__(self):self.documents={};self.revisions={};self.keys={};self.rows={}
    async def create_from_source(self,source,*,scope,request_id):
        key=native_digest([source.model_dump(mode='json'),scope.model_dump(),request_id])
        if key in self.keys:return self.documents[self.keys[key]]
        document=NativeDocument(documentId=uuid4().hex,scope=scope,ownerId=scope.user_id,source=source,createdAt=datetime.now(UTC),nextRevision=2)
        context=NativeEditorContext(documentId=document.document_id,format=source.format,revision=1,scope=scope,sourceFile=source.source_file,origin=source.origin,displayName=source.display_name)
        self.documents[document.document_id]=document;self.keys[key]=document.document_id
        self.revisions[(document.document_id,1)]=NativeRevision(documentId=document.document_id,revision=1,scope=scope,requestId=request_id,requestSha256=key,status='saved',context=context,artifacts=NativeArtifacts(word=source.source_file),validation=NativeValidation(ok=False),createdAt=datetime.now(UTC))
        return document
    async def get_revision(self,document_id,revision,*,scope):
        row=self.revisions.get((document_id,revision));return row if row and row.scope==scope else None
    async def reserve_revision(self,document_id,*,parent_revision,request_id,request_sha256,scope,note=''):
        key=(document_id,request_id)
        if key in self.rows:
            row=self.rows[key]
            if row.request_sha256!=request_sha256 or row.parent_revision!=parent_revision or row.scope!=scope:raise NativeRepositoryConflict()
            return row
        parent=await self.get_revision(document_id,parent_revision,scope=scope)
        if not parent or parent.status!='saved':raise NativeRepositoryConflict()
        number=max(revision for doc,revision in self.revisions if doc==document_id)+1
        row=NativeRevision(documentId=document_id,revision=number,scope=scope,parentRevision=parent_revision,requestId=request_id,requestSha256=request_sha256,note=note,status='reserved',createdAt=datetime.now(UTC))
        self.rows[key]=row;self.revisions[(document_id,number)]=row;return row
    async def complete_revision(self,reservation,*,context,artifacts,validation):
        row=reservation.model_copy(update={'context':context,'artifacts':artifacts,'validation':validation,'status':'saved'})
        self.rows[(row.document_id,row.request_id)]=row;self.revisions[(row.document_id,row.revision)]=row;return row
    async def fail_revision(self,reservation,*,code):
        row=reservation.model_copy(update={'status':'failed','failure_code':code});self.rows[(row.document_id,row.request_id)]=row;self.revisions[(row.document_id,row.revision)]=row

async def create_app(directory,static,port,resume=False):
    directory.mkdir(parents=True,exist_ok=True)
    if list(directory.glob('saved-*.json')) and not resume:raise RuntimeError('Saved receipts already exist: preserve this evidence; do not repeat saves on harness restart')
    workspace=ReportingWorkspaceRouter(ReportingWorkspaceRegistry(directory/'workspace',secret='w'*32));repository=Repository()
    grants=ReportEditorGrantService(InMemoryReportEditorRepository(),secret='g'*32)
    download_grants=ReportDownloadGrantService(InMemoryDownloadGrantRepository());artifacts=InMemoryReportArtifactRepository()
    origin=f'http://127.0.0.1:{port}'
    class Publication(NativePublicationService):
        async def save_revision(self,*args,**kwargs):
            result=await super().save_revision(*args,**kwargs)
            stem=f"saved-{result['documentId']}-r{result['revision']}"
            (directory/(stem+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
            context=(await repository.get_revision(result['documentId'],result['revision'],scope=args[0].scope)).context
            if context:(directory/(stem+'.docx')).write_bytes(await editor.read_file(context))
            return result
    publication=Publication(repository,workspace,download_grants,grants,artifact_persistence=ReportArtifactPersistenceService(artifacts,workspace),public_base_url=origin)
    downloads=ReportDownloadHttpService(download_grants,artifacts,workspace_service=workspace)
    editor=NativeEditorService(workspace,repository,grants,report_editor=None,publication=publication,docx_enabled=True)
    if resume:
        checkpoint=json.loads((directory/'browser-checkpoint.json').read_text())
        paths={}
        for encoded in checkpoint['contexts']:
            context=NativeEditorContext.model_validate(encoded)
            await editor.read_file(context)
            if context.document_id not in repository.documents:
                source=NativeSource(format='docx',origin='upload',sourceFile=context.source_file,displayName=context.display_name)
                repository.documents[context.document_id]=NativeDocument(documentId=context.document_id,scope=context.scope,ownerId=context.scope.user_id,source=source,createdAt=datetime.now(UTC),nextRevision=context.revision+1)
            repository.revisions[(context.document_id,context.revision)]=NativeRevision(documentId=context.document_id,revision=context.revision,scope=context.scope,requestId='restore-'+str(context.revision),requestSha256=context.digest(),status='saved',context=context,artifacts=NativeArtifacts(word=context.source_file),validation=NativeValidation(ok=False),createdAt=datetime.now(UTC))
            grant,_=await grants.issue(context,capabilities=editor.capabilities(context))
            paths[context.document_id+':'+str(context.revision)]='/reports/v1/native/open/'+grant
        (directory/'resume-info.json').write_text(json.dumps({'paths':paths},ensure_ascii=False,indent=2))
    else:
        document=Document();document.add_paragraph('Original saved source must remain unchanged');stream=BytesIO();document.save(stream);source=stream.getvalue()
        scope=NativeScope(database='smoke',companyId='company',userId='reviewer',threadId='word-file-actions')
        initial=await NativeImportService(workspace,repository,grants).import_file(scope,source,request_id='initial-source',filename='original.docx',display_name='Original.docx')
        (directory/'original.docx').write_bytes(source)
        (directory/'server-info.json').write_text(json.dumps({'openPath':initial['editor']['url'],'sourceDocumentId':initial['documentId'],'sourceSha256':hashlib.sha256(source).hexdigest()},indent=2))
    @asynccontextmanager
    async def lifespan(app):
        yield
        await workspace.registry.aclose()
    app=FastAPI(lifespan=lifespan)
    app.include_router(create_native_editor_router(grants,editor=editor,download_service=downloads,cookie_secure=False,allowed_origin=origin,static_dir=static))
    app.mount('/reports/v1/editor/assets',StaticFiles(directory=static))
    requests=json.loads((directory/'http-evidence.json').read_text()) if resume else []
    @app.middleware('http')
    async def record(request:Request,call_next):
        if resume and request.method=='POST' and request.url.path.endswith(('/api/save','/api/export','/word/new','/word/save-as')):
            return JSONResponse({'detail':{'code':'smoke_resume_readonly','message':'Successful save receipts retained; resume cannot repeat file mutations'}},status_code=409)
        body=await request.body() if request.method=='POST' else b''
        response=await call_next(request)
        requests.append({'method':request.method,'path':request.url.path,'status':response.status_code,**({'body':json.loads(body)} if body and 'application/json' in request.headers.get('content-type','') else {})})
        (directory/'http-evidence.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2))
        return response
    @app.get('/__smoke__/state')
    async def state():
        return {'requests':requests,'documents':[row.model_dump(mode='json',by_alias=True) for row in repository.documents.values()],'revisions':[row.model_dump(mode='json',by_alias=True) for row in repository.revisions.values()]}
    return app

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--static',type=Path,required=True);parser.add_argument('--port',type=int,default=4318);parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    uvicorn.run(asyncio.run(create_app(args.directory,args.static,args.port,args.resume)),host='127.0.0.1',port=args.port,log_level='warning')
