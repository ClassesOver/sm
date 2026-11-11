from __future__ import annotations

import hashlib
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor import native_pdf_convert
from smart_reporting.report_editor.native_models import NativeArtifacts
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_extract import extract_fixture

def receipt():
    deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6]);slide.shapes.add_textbox(Inches(1),Inches(1),Inches(4),Inches(1)).text='Converted real slide'
    stream=BytesIO();deck.save(stream);content=stream.getvalue()
    return {'content':content,'sha256':hashlib.sha256(content).hexdigest(),'size':len(content),'format':'pptx','pages':1,'warnings':['manual review'],'pageResults':[{'page':1,'status':'ok'}],'scannedDocument':False,'validation':{'ok':False,'issues':['manual review']}}

@pytest.mark.anyio
@pytest.mark.parametrize('fault',[None,'registration','postwrite','review','persistence'])
async def test_convert_office_publishes_independent_pptx_and_retains_download_on_late_faults(tmp_path,monkeypatch,fault):
    f=await extract_fixture(tmp_path);converted=receipt();monkeypatch.setattr(native_pdf_convert,'convert_pdf_office',lambda *args,**kwargs:converted)
    if fault=='registration':f.repository.create_from_source=AsyncMock(side_effect=RuntimeError('registration unavailable'))
    if fault=='persistence':f.publication.artifact_persistence.persist_available=AsyncMock(side_effect=RuntimeError('persistence unavailable'))
    if fault=='postwrite':
        original=f.workspace.awrite_bytes
        async def write_then_raise(*args,**kwargs):
            await original(*args,**kwargs);raise RuntimeError('after real write')
        monkeypatch.setattr(f.workspace,'awrite_bytes',write_then_raise)
    if fault=='review':monkeypatch.setattr(native_pdf_convert,'read_verified_file',AsyncMock(side_effect=RuntimeError('review unavailable')))
    result=await native_pdf_convert.convert_office(f.editor,f.parent,expected_sha256=f.parent.source_file.sha256,request_id='convert-1')
    artifact=result['artifacts']['pptx'];assert artifact['downloadUrl'];assert result['documentId']!=f.parent.document_id;assert result['revision']==1;assert result['validation']['ok'] is False
    content,_=await f.workspace.afile_bytes(f.thread,artifact['path']);assert content==converted['content'];assert len(Presentation(BytesIO(content)).slides)==1
    original,_=await f.workspace.afile_bytes(f.thread,f.original_identity.path);assert original==f.original
    assert result['conversion']['format']=='pptx';assert result['source']['sha256']==f.original_identity.sha256
    if fault=='registration':assert result['revisionRegistered'] is False;assert any(issue['code']=='native_derived_registration_failed' for issue in result['validation']['issues'])
    else:
        child=next(iter(f.repository.documents.values()));assert child.source.format=='pptx';assert child.source.parent_document_id==f.parent.document_id;assert child.source.parent_sha256==f.original_identity.sha256;assert result['revisionRegistered'] is True
    if fault in {'postwrite','review','persistence'}:assert any(fault in issue['code'] for issue in result['validation']['issues'])

@pytest.mark.anyio
@pytest.mark.parametrize('patch',[{'expected_sha256':'f'*64},{'output_format':'unsupported'},{'request_id':''}])
async def test_convert_office_rejects_untrusted_parameters_before_engine(tmp_path,monkeypatch,patch):
    f=await extract_fixture(tmp_path);engine=AsyncMock();monkeypatch.setattr(native_pdf_convert,'run_office_engine',engine)
    with pytest.raises(ReportingError):await native_pdf_convert.convert_office(f.editor,f.parent,**{'expected_sha256':f.original_identity.sha256,'request_id':'convert',**patch})
    engine.assert_not_called();assert not f.repository.documents

@pytest.mark.anyio
@pytest.mark.parametrize('office_enabled',[False,True])
async def test_conversion_editor_link_respects_pptx_feature_switch_but_keeps_registered_download(tmp_path,monkeypatch,office_enabled):
    f=await extract_fixture(tmp_path);f.editor.office_enabled=office_enabled
    monkeypatch.setattr(native_pdf_convert,'convert_pdf_office',lambda *args,**kwargs:receipt())
    result=await native_pdf_convert.convert_office(f.editor,f.parent,expected_sha256=f.original_identity.sha256,request_id='target-editor-switch')
    assert result['revisionRegistered'] is True
    assert result['artifacts']['pptx']['downloadUrl']
    assert ('editor' in result) is office_enabled

@pytest.mark.anyio
@pytest.mark.parametrize('output_format,artifact_key', [('docx','word'),('xlsx','xlsx')])
async def test_convert_office_publishes_actual_docx_and_xlsx(tmp_path,monkeypatch,output_format,artifact_key):
    f=await extract_fixture(tmp_path)
    stream=BytesIO()
    if output_format=='docx':
        from docx import Document
        document=Document();document.add_paragraph('Converted report');document.save(stream)
    else:
        from openpyxl import Workbook
        document=Workbook();document.active['A1']='Converted report';document.save(stream)
    content=stream.getvalue()
    monkeypatch.setattr(native_pdf_convert,'convert_pdf_office',lambda *args,**kwargs:{'content':content,'validation':{'issues':None}})
    result=await native_pdf_convert.convert_office(f.editor,f.parent,expected_sha256=f.original_identity.sha256,request_id='multi-office',output_format=output_format)
    artifact=result['artifacts'][artifact_key]
    assert artifact['downloadUrl'];assert artifact['path'].endswith('.'+output_format)
    assert result['conversion']['format']==output_format;assert result['revisionRegistered'] is True
    actual,_=await f.workspace.afile_bytes(f.thread,artifact['path']);assert actual==content
