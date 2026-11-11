"""保护下载的密码仅用于本次请求，不进入来源或修订操作记录。"""
import hashlib
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport,AsyncClient
from pypdf import PdfReader

from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE,create_native_editor_router
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture

@pytest.fixture
def anyio_backend():
    return 'asyncio'

async def protection_client(tmp_path):
    editor,context,source,downloads=await fixture(tmp_path)
    editor.context_for_session=AsyncMock(return_value=context)
    raw,_=await editor.grants.issue(context,capabilities=editor.capabilities(context))
    token,_=await editor.grants.exchange(raw)
    app=FastAPI()
    app.include_router(create_native_editor_router(editor.grants,editor=editor,download_service=downloads,cookie_secure=False,allowed_origin='http://test'))
    base=f'/reports/v1/native/{context.document_id}/{context.revision}'
    return editor,context,source,app,base,token

@pytest.mark.anyio
async def test_protection_issues_actual_password_download_without_persisting_credentials(tmp_path):
    editor,context,source,app,base,token=await protection_client(tmp_path)
    payload={'requestId':'protect-source','expectedSha256':context.source_file.sha256,'userPassword':'reader-secret','ownerPassword':'owner-secret','permissions':{'printing':True,'modifying':False,'annotating':True,'copying':False}}
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        response=await client.post(base+'/api/protect-pdf',json=payload,headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)})
        assert response.status_code==200,response.text
        saved=response.json()
        assert not saved['revisionRegistered'] and 'editor' not in saved
        assert saved['validation']['ok'] is False
        assert any(i['code']=='native_protected_pdf_download_only' for i in saved['validation']['issues'])
        actual=await client.get(saved['artifacts']['pdf']['downloadUrl'])
        assert actual.status_code==200
        assert hashlib.sha256(actual.content).hexdigest()==saved['artifacts']['pdf']['sha256']
        pdf=PdfReader(BytesIO(actual.content));assert pdf.is_encrypted
        assert pdf.decrypt('wrong-secret')==0 and pdf.decrypt('reader-secret')==1
        assert 'Amount due 500' in pdf.pages[0].extract_text()
        assert not int(pdf.trailer['/Encrypt']['/P']) & 16
        assert 'reader-secret' not in response.text and 'owner-secret' not in response.text
        assert 'reader-secret' not in repr(editor.repository.rows) and 'owner-secret' not in repr(editor.repository.rows)
        assert await editor.read_file(context)==source

@pytest.mark.anyio
async def test_protection_rejects_forged_source_and_missing_csrf(tmp_path):
    editor,context,_,app,base,token=await protection_client(tmp_path)
    payload={'requestId':'protect-source','expectedSha256':'0'*64,'userPassword':'reader-secret','ownerPassword':'owner-secret','permissions':{'printing':True,'modifying':True,'annotating':True,'copying':True}}
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)}
        assert (await client.post(base+'/api/protect-pdf',json=payload,headers=headers)).status_code==409
        assert (await client.post(base+'/api/protect-pdf',json=payload)).status_code==403
        assert not editor.repository.rows
