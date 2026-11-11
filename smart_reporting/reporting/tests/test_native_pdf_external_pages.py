from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.report_editor.native_pdf_external_pages import external_pages
from smart_reporting.reporting.models import ReportingError

def fixture():
    source, external=b'%PDF-parent', b'%PDF-external'
    context=SimpleNamespace(format='pdf',source_file=SimpleNamespace(sha256=hashlib.sha256(source).hexdigest()))
    result={'revision':5,'revisionRegistered':False,'artifacts':{'pdf':{'downloadUrl':'/download/real'}},'validation':{'ok':False,'issues':[{'code':'registration_failed'}]}}
    editor=SimpleNamespace(require_enabled=lambda _:None,read_file=AsyncMock(return_value=source),save=AsyncMock(return_value=result))
    payload=dict(request_id='external-1',expected_sha256=context.source_file.sha256,external_sha256=hashlib.sha256(external).hexdigest(),bytes_base64=base64.b64encode(external).decode())
    return editor,context,payload,result

@pytest.mark.anyio
@pytest.mark.parametrize('action,options,expected',[('insert',{'after_page':0},{'afterPageIndex':-1}),('replace',{'pages':[3,1]},{'pages':[2,0]})])
async def test_external_service_reuses_revision_save_and_retains_failed_validation_links(action,options,expected):
    editor,context,payload,result=fixture()
    assert await external_pages(editor,context,action=action,**payload,**options)==result
    args=editor.save.call_args.kwargs
    assert args['request_id']=='external-1'
    assert args['expected_sha256']==context.source_file.sha256
    assert args['operations']==[{'kind':'externalPages','action':action,'sourceSha256':payload['expected_sha256'],'externalSha256':payload['external_sha256'],'bytesBase64':payload['bytes_base64'],**expected}]

@pytest.mark.anyio
@pytest.mark.parametrize('patch',[{'expected_sha256':'f'*64},{'external_sha256':'f'*64},{'bytes_base64':'Zm9v '},{'bytes_base64':'Zm9v'},{'request_id':''},{'after_page':True},{'after_page':-1},{'after_page':0.5},{'pages':[1]},{'action':'replace','after_page':None,'pages':[1,1]},{'action':'replace','after_page':None,'pages':[True]}])
async def test_external_service_rejects_unbound_or_ambiguous_uploads_before_save(patch):
    editor,context,payload,_=fixture()
    options={**payload,'action':'insert','after_page':1,**patch}
    with pytest.raises(ReportingError):await external_pages(editor,context,**options)
    editor.save.assert_not_awaited()

@pytest.mark.anyio
async def test_external_service_rechecks_actual_parent_bytes_before_saving():
    editor,context,payload,_=fixture();editor.read_file.return_value=b'%PDF-changed'
    with pytest.raises(ReportingError):await external_pages(editor,context,action='insert',after_page=0,**payload)
    editor.save.assert_not_awaited()
