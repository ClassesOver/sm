"""Independent Word files retain the source and use real editable DOCX bytes."""
import hashlib
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest
from docx import Document
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.native import NativeEditorService
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_editor_api import Repository as BaseRepository
from smart_reporting.report_editor.native_models import NativeEditorContext
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication, Repository as PublicationRepository

class Repository(BaseRepository, PublicationRepository):
    def __init__(self):
        BaseRepository.__init__(self)
        PublicationRepository.__init__(self)
    async def create_from_source(self, source, *, scope, request_id):
        document=await super().create_from_source(source,scope=scope,request_id=request_id)
        row=self.revisions[(document.document_id,1)]
        self.revisions[(document.document_id,1)]=row.model_copy(update={'context':NativeEditorContext(
            documentId=document.document_id,format=source.format,revision=1,scope=scope,
            sourceFile=source.source_file,origin=source.origin,displayName=source.display_name)})
        return document
    async def get_revision(self, document_id, revision, *, scope):
        found=await super().get_revision(document_id,revision,scope=scope)
        if found:return found
        return next((row for row in self.rows.values() if row.document_id==document_id and row.revision==revision and row.scope==scope),None)

@pytest.fixture
def anyio_backend(): return 'asyncio'

@pytest.fixture
def source_runtime(tmp_path, monkeypatch):
    engine=Path(__file__).resolve().parents[1]/'doc_engine';runtime=tmp_path/'engine';runtime.mkdir()
    for name in ('bridge','packages','node_modules'):(runtime/name).symlink_to(engine/name,target_is_directory=True)
    monkeypatch.setenv('AGENT_REPORTING_DOC_ENGINE_DIR',str(runtime))


def test_source_blank_is_deterministic_and_first_text_edit_has_trusted_anchor(source_runtime):
    from smart_reporting.report_editor.native_word_file_actions import render_blank_word
    raw=render_blank_word();assert raw==render_blank_word()
    with ZipFile(BytesIO(raw)) as archive:
        assert 'word/styles.xml' in archive.namelist()
        assert b'<w:p></w:p>' in archive.read('word/document.xml')
    model=inspect_docx(raw)
    assert len(model['blocks'])==1
    block=model['blocks'][0]
    edited=patch_docx(raw,[{'kind':'replaceParagraph','blockId':block['blockId'],'expectedObjectSha256':block['expectedObjectSha256'],'text':'First trusted edit'}])
    assert Document(BytesIO(edited)).paragraphs[0].text=='First trusted edit'

async def runtime(tmp_path):
    publication,context,_=await create_publication(tmp_path)
    editor=NativeEditorService(publication.workspace,Repository(),publication.editor_grants,report_editor=None,docx_enabled=True)
    editor.context_for_session=AsyncMock(return_value=context)
    raw,_=await editor.grants.issue(context,capabilities=editor.capabilities(context));token,_=await editor.grants.exchange(raw)
    app=FastAPI();app.include_router(create_native_editor_router(editor.grants,editor=editor,cookie_secure=False,allowed_origin='http://test'))
    return editor,context,app,f'/reports/v1/native/{context.document_id}/{context.revision}/api/word',token

@pytest.mark.anyio
async def test_new_and_save_as_are_independent_authorized_idempotent_files(tmp_path,source_runtime):
    editor,context,app,url,token=await runtime(tmp_path)
    original=await editor.read_file(context)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',cookies={NATIVE_SESSION_COOKIE:token}) as client:
        headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)}
        for action in ('new','save-as'):
            payload={'requestId':action,'expectedSha256':context.source_file.sha256,'filename':'Independent.docx'}
            first=await client.post(url+'/'+action,json=payload,headers=headers)
            assert first.status_code==200,first.text
            result=first.json();assert result['documentId']!=context.document_id and result['revision']==1
            assert result['editor']['openUrl'].startswith('/reports/v1/native/open/')
            repeated=await client.post(url+'/'+action,json=payload,headers=headers)
            assert repeated.status_code==200 and repeated.json()['documentId']==result['documentId']
            revision=await editor.repository.get_revision(result['documentId'],1,scope=context.scope)
            assert revision.context.source_file.path.endswith('/original.docx')
            assert revision.context.display_name=='Independent.docx'
            content=await editor.read_file(revision.context)
            assert Document(BytesIO(content)).paragraphs[0].text==('' if action=='new' else '原始段落')
            _,session=await editor.grants.exchange(result['editor']['openUrl'].split('/')[-1])
            assert session.report_id==result['documentId']
        assert await editor.read_file(context)==original

@pytest.mark.anyio
async def test_file_actions_reject_csrf_foreign_route_stale_source_and_path_names(tmp_path,source_runtime):
    editor,context,app,url,token=await runtime(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',cookies={NATIVE_SESSION_COOKIE:token}) as client:
        headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)}
        payload={'requestId':'new','expectedSha256':context.source_file.sha256}
        for action in ('new','save-as'):
            assert (await client.post(url+'/'+action,json=payload)).status_code==403
            assert (await client.post(url.replace('/document/','/foreign/')+'/'+action,json=payload,headers=headers)).status_code==403
            assert (await client.post(url+'/'+action,json={**payload,'expectedSha256':'0'*64},headers=headers)).status_code==409
            assert (await client.post(url+'/'+action,json={**payload,'filename':'../escape.docx'},headers=headers)).status_code==422
        assert not editor.repository.documents

@pytest.mark.anyio
async def test_saved_copy_name_survives_next_revision_and_download(tmp_path,source_runtime):
    from smart_reporting.report_editor.native_word_file_actions import create_word_file
    from smart_reporting.report_editor.native_api import _native_disposition
    publication,parent,downloads=await create_publication(tmp_path)
    repository=Repository();publication.repository=repository
    editor=NativeEditorService(publication.workspace,repository,publication.editor_grants,report_editor=None,docx_enabled=True)
    result=await create_word_file(editor,parent,action='save-as',expected_sha256=parent.source_file.sha256,
        request_id='copy',filename='独立副本.docx')
    initial=(await repository.get_revision(result['documentId'],1,scope=parent.scope)).context
    saved=await publication.save_revision(initial,operations=[],request_id='edit-copy',expected_sha256=initial.source_file.sha256)
    assert saved['revisionRegistered'] is True
    next_context=repository.rows['edit-copy'].context
    assert next_context.revision==2 and next_context.display_name=='独立副本.docx'
    assert next_context.document_id!=parent.document_id
    assert _native_disposition(next_context.display_name,'docx')=="attachment; filename*=UTF-8''%E7%8B%AC%E7%AB%8B%E5%89%AF%E6%9C%AC.docx"
    assert await editor.read_file(parent)==await editor.read_file(initial)
    app=FastAPI();app.include_router(create_native_editor_router(editor.grants,editor=editor,download_service=downloads,cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get(saved['artifacts']['word']['downloadUrl'])
        assert response.status_code==200,response.text
        assert response.headers['content-disposition']==_native_disposition('独立副本.docx','docx')
        assert response.content==await editor.read_file(next_context)


def test_old_context_and_source_digests_keep_omitting_absent_display_name():
    from smart_reporting.report_editor.native_models import NativeSource,NativeEditorContext,native_digest
    context=NativeEditorContext(documentId='old',format='docx',revision=1,scope={'database':'db','companyId':'c','userId':'u','threadId':'t'},
        sourceFile={'path':'old.docx','size':1,'sha256':'a'*64,'mediaType':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},origin='upload')
    encoded=context.model_dump(mode='json',by_alias=True)
    assert 'displayName' not in encoded and 'display_name' not in context.model_dump()
    assert context.digest()==native_digest({'kind':'native-editor-context:v1','context':encoded})
    source=NativeSource(format='docx',origin='upload',sourceFile=context.source_file)
    assert 'displayName' not in source.model_dump(by_alias=True) and 'display_name' not in source.model_dump()
