"""保护文件实际生成后，回执与复核异常不得丢弃其字节。"""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from smart_reporting.report_editor import native_pdf_protection
from smart_reporting.reporting.delivery import pdf_native
from smart_reporting.reporting.tests.test_native_pdf_extract import extract_fixture, source_pdf

def protected_bytes():
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source_pdf())))
    writer.encrypt(user_password='reader-secret',owner_password='owner-secret',algorithm='AES-256')
    stream=BytesIO();writer.write(stream);return stream.getvalue()

@pytest.mark.parametrize('fault',['receipt_error','receipt_identity'])
def test_protection_bridge_keeps_actual_encrypted_bytes_after_receipt_fault(monkeypatch,fault):
    content=protected_bytes()
    def invoke(payload,root,**kwargs):
        Path(payload['output']).write_bytes(content)
        if fault=='receipt_error':raise ValueError('receipt failed after actual encrypted write')
        return {'sourceSha256':'f'*64,'sha256':'f'*64,'size':1,'algorithm':'forged','revision':1,'reviewIssues':[]}
    monkeypatch.setattr(pdf_native,'_invoke',invoke)
    result=pdf_native.protect_pdf(source_pdf(),user_password='reader-secret',owner_password='owner-secret',permissions={'printing':True,'modifying':False,'annotating':True,'copying':False})
    assert result['content']==content;assert result['sha256']==hashlib.sha256(content).hexdigest();assert result['size']==len(content);assert result['reviewIssues']
    reader=PdfReader(BytesIO(result['content']));assert reader.decrypt('reader-secret')==1
    assert 'reader-secret' not in repr(result) and 'owner-secret' not in repr(result)

@pytest.mark.anyio
@pytest.mark.parametrize('fault',['postwrite','review'])
async def test_protection_service_keeps_download_when_actual_file_identity_can_be_recovered(tmp_path,monkeypatch,fault):
    from unittest.mock import AsyncMock
    f=await extract_fixture(tmp_path);content=protected_bytes()
    monkeypatch.setattr(native_pdf_protection,'protect_pdf_bytes',lambda *args,**kwargs:{'content':content,'sha256':hashlib.sha256(content).hexdigest(),'size':len(content),'reviewIssues':[]})
    if fault=='postwrite':
        original=f.workspace.awrite_bytes
        async def write_then_raise(*args,**kwargs):
            await original(*args,**kwargs);raise RuntimeError('actual write already complete')
        monkeypatch.setattr(f.workspace,'awrite_bytes',write_then_raise)
    else:monkeypatch.setattr(native_pdf_protection,'read_verified_file',AsyncMock(side_effect=RuntimeError('review unavailable')))
    result=await native_pdf_protection.protect_pdf(f.editor,f.parent,request_id='protect-late-fault',expected_sha256=f.original_identity.sha256,user_password='reader-secret',owner_password='owner-secret',permissions={'printing':True,'modifying':False,'annotating':True,'copying':False})
    artifact=result['artifacts']['pdf'];assert artifact['downloadUrl'];assert result['validation']['ok'] is False;assert result['revisionRegistered'] is False;assert 'editor' not in result
    actual,_=await f.workspace.afile_bytes(f.thread,artifact['path']);assert actual==content;assert artifact['sha256']==hashlib.sha256(actual).hexdigest()
    reader=PdfReader(BytesIO(actual));assert reader.decrypt('reader-secret')==1;assert len(reader.pages)==3
    assert any(fault in issue['code'] for issue in result['validation']['issues'])
    assert await f.editor.read_file(f.parent)==f.original
