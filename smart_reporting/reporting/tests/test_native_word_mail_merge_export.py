"""Real source-bound mail merge downloads; session/CSV authorization precedes bridge work."""
import base64
import hashlib
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
from smart_reporting.report_editor.native_word_mail_merge_export import export_word_mail_merge, render_word_mail_merge
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication

@pytest.fixture
def anyio_backend():return 'asyncio'

def template():
    document=Document();paragraph=document.add_paragraph('Dear ')
    for kind,value in [('fldChar','begin'),('instrText',' MERGEFIELD "Name" '),('fldChar','separate'),('t','OLD'),('fldChar','end')]:
        node=OxmlElement('w:'+kind)
        if kind=='fldChar':node.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType',value)
        else:node.text=value
        run=OxmlElement('w:r');run.append(node);paragraph._p.append(run)
    document.sections[0].header.paragraphs[0].text='Preserved header'
    out=BytesIO();document.save(out);return out.getvalue()

@pytest.fixture
def source_runtime(tmp_path,monkeypatch):
    engine=Path(__file__).resolve().parents[1]/'doc_engine';runtime=tmp_path/'engine';runtime.mkdir()
    for name in ('bridge','packages','node_modules'):(runtime/name).symlink_to(engine/name,target_is_directory=True)
    monkeypatch.setenv('AGENT_REPORTING_DOC_ENGINE_DIR',str(runtime))

def operation(source,**patch):
    return {'kind':'mailMergeOutput','documentSha256':hashlib.sha256(source).hexdigest(),'mode':'perRecord','namePattern':'Name','fields':['Name'],'records':[{'Name':'Ada'},{'Name':'Grace'}],**patch}

def test_real_bridge_zip_and_label_docx_roundtrip(source_runtime):
    source=template();result=render_word_mail_merge(source,operation(source))
    assert result['filename']=='mail-merge.zip' and result['sha256']==hashlib.sha256(result['content']).hexdigest()
    with ZipFile(BytesIO(result['content'])) as archive:
        assert archive.namelist()==['Ada.docx','Grace.docx']
        for name in ('Ada','Grace'):
            letter=Document(BytesIO(archive.read(name+'.docx')))
            assert letter.paragraphs[0].text=='Dear '+name
            assert letter.sections[0].header.paragraphs[0].text=='Preserved header'
    labels=render_word_mail_merge(source,operation(source,mode='labels',layout={'stock':'avery5160'}))
    assert labels['filename']=='mail-merge-labels.docx'
    document=Document(BytesIO(labels['content']));assert [cell.text for cell in document.tables[0].rows[0].cells]==['Dear Ada','','Dear Grace','','']
    assert int(document.sections[0].page_width.twips)==12240

@pytest.mark.parametrize('settings',[
    b'<x:settings xmlns:x="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><x:documentProtection x:enforcement="&#49;"/></x:settings>',
    b'<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:documentProtection w:enforcement="true"/></w:settings>',
])
def test_export_bridge_refuses_native_alias_protection(source_runtime,settings):
    out=BytesIO()
    with ZipFile(BytesIO(template())) as original,ZipFile(out,'w') as target:
        for name in original.namelist():target.writestr(name,settings if name=='word/settings.xml' else original.read(name))
    source=out.getvalue()
    with pytest.raises(ReportingError):render_word_mail_merge(source,operation(source))

async def client_fixture(tmp_path):
    publication,context,_=await create_publication(tmp_path)
    source=template();key=bind_native_workspace(publication.workspace,context.scope)
    await publication.workspace.awrite_bytes(key,context.source_file.path,source,overwrite=True)
    context=context.model_copy(update={'source_file':context.source_file.model_copy(update={'size':len(source),'sha256':hashlib.sha256(source).hexdigest()})})
    editor=NativeEditorService(publication.workspace,publication.repository,publication.editor_grants,report_editor=None,docx_enabled=True)
    editor.context_for_session=AsyncMock(return_value=context)
    raw,_=await editor.grants.issue(context,capabilities=editor.capabilities(context));token,_=await editor.grants.exchange(raw)
    app=FastAPI();app.include_router(create_native_editor_router(editor.grants,editor=editor,cookie_secure=False,allowed_origin='http://test'))
    return editor,context,source,app,f'/reports/v1/native/{context.document_id}/{context.revision}',token

@pytest.mark.anyio
async def test_export_http_authenticates_csv_and_returns_ephemeral_verified_binary(tmp_path,source_runtime):
    editor,context,source,app,base,token=await client_fixture(tmp_path/'workspace')
    csv=b'Name\nAda\nGrace\n';payload={'documentSha256':context.source_file.sha256,'sourceSha256':hashlib.sha256(csv).hexdigest(),'sourceBase64':base64.b64encode(csv).decode(),'mode':'perRecord','namePattern':'Name'}
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)}
            client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
            assert (await client.post(base+'/api/mail-merge/export',json=payload)).status_code==403
            assert (await client.post(base+'/api/mail-merge/export',json=payload,headers=headers)).status_code==403 # self-reported foreign CSV
            upload=await client.post(base+'/api/mail-merge/source',headers=headers,json={'requestId':'upload','filename':'recipients.csv','bytesBase64':payload['sourceBase64']});assert upload.status_code==200,upload.text
            stale=await client.post(base+'/api/mail-merge/export',json={**payload,'documentSha256':'0'*64},headers=headers);assert stale.status_code==409,stale.text
            injected=await client.post(base+'/api/mail-merge/export',json={**payload,'records':[{'Name':'Forged'}]},headers=headers);assert injected.status_code==422
            response=await client.post(base+'/api/mail-merge/export',json=payload,headers=headers);assert response.status_code==200,response.text
            assert response.headers['x-native-export-sha256']==hashlib.sha256(response.content).hexdigest();assert response.headers['x-native-source-sha256']==context.source_file.sha256
            assert response.headers['cache-control']=='no-store';assert '/tmp/' not in str(response.headers)
            with ZipFile(BytesIO(response.content)) as archive:assert archive.namelist()==['Ada.docx','Grace.docx']
            key=bind_native_workspace(editor.workspace,context.scope);await editor.workspace.awrite_bytes(key,f'native/mailmerge/{payload["sourceSha256"]}.csv',b'Name\nTampered\n',overwrite=True)
            assert (await client.post(base+'/api/mail-merge/export',json=payload,headers=headers)).status_code==403
            assert not editor.repository.rows;assert await editor.read_file(context)==source
    finally:await editor.workspace.registry.aclose()
