"""Whole source radio groups preserve their field tree through the real save/download chain."""
from io import BytesIO
import hashlib
import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.report_editor.native_models import NativeEditorContext
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
@pytest.mark.parametrize("multipage",[False,True])
async def test_source_radio_group_copy_preview_save_download_preserves_values_and_pages(tmp_path,multipage):
    editor,old,_,downloads=await fixture(tmp_path,text_enabled=False)
    stream=BytesIO();c=canvas.Canvas(stream,pagesize=(400,500));c.drawString(30,450,'Original radio body');c.showPage();c.drawString(30,450,'Second control')
    if multipage:
        c.showPage();c.drawString(30,450,'Third control')
    c.save();empty=stream.getvalue();model=inspect_pdf(empty);sha=hashlib.sha256(empty).hexdigest()
    rows=[{'pageId':model['pages'][1 if multipage and i>0 else 0]['pageId'],'rect':[30+i*60,300,50+i*60,320],'exportValue':value,'checked':i==1} for i,value in enumerate(['Yes','No','Maybe'])]
    source=patch_pdf(empty,[{'kind':'createFormField','sourceSha256':sha,'pageId':rows[0]['pageId'],'fieldName':'party.answer','fieldKind':'radio','rect':rows[0]['rect'],'required':True,'radioWidgets':rows}])
    key=bind_native_workspace(editor.workspace,old.scope);path='native/source-radio.pdf';await editor.workspace.awrite_bytes(key,path,source);sha=hashlib.sha256(source).hexdigest()
    context=NativeEditorContext(documentId='document',revision=1,scope=old.scope,format='pdf',origin='upload',sourceFile=ArtifactFile(path=path,size=len(source),sha256=sha,mediaType='application/pdf'))
    model=inspect_pdf(source);group=model['formDesignWidgets'];assert len(group)==3 and all(w['copyEditable'] for w in group);first=group[0]
    copied_rows=[{'pageId':model['pages'][w['pageIndex']+1 if multipage else 1]['pageId'],'rect':[v+(10 if j%2==0 else -10) for j,v in enumerate(w['rect'])],'exportValue':w['radioOptions'][i],'checked':w['radioChecked']} for i,w in enumerate(group)]
    operations=[{'kind':'createFormField','sourceSha256':sha,'pageId':copied_rows[0]['pageId'],'fieldName':'party.answer_copy1','fieldKind':'radio','rect':copied_rows[0]['rect'],'required':True,'copyFrom':{k:first[k] for k in ('fieldName','widgetId','widgetIdentity','expectedWidgetSha256')},'radioWidgets':copied_rows}]
    with pytest.raises(ReportingError) as caught:
        await editor.save(context,expected_sha256=sha,operations=operations,request_id='radio-unconfirmed')
    assert caught.value.code=='native_pdf_text_confirmation_required' and not editor.repository.rows
    preview=await editor.preview(context,expected_sha256=sha,operations=operations);assert preview['appliedOperationIndices']==[0] and preview['skippedOperations']==[]
    actual=await editor.preview_file(context,expected_sha256=sha,operations=operations,expected_preview_digest=preview['previewDigest'])
    result=await editor.save(context,expected_sha256=sha,operations=operations,request_id='radio-confirmed',confirmed_preview_digest=preview['previewDigest']);assert result['revisionRegistered'] and result['validation']['ok'] is False
    token=result['artifacts']['pdf']['downloadUrl'].split('/')[-2];_,chunks=await downloads.stream(token,artifact='pdf');saved=b''.join([chunk async for chunk in chunks]);assert saved==actual['content']
    reader=PdfReader(BytesIO(saved));fields=reader.get_fields();assert {name for name,f in fields.items() if f.get('/FT')}=={'party.answer','party.answer_copy1'};assert len(fields['party']['/Kids'])==2
    assert fields['party.answer']['/V']==fields['party.answer_copy1']['/V'] and fields['party.answer']['/Opt']==fields['party.answer_copy1']['/Opt'];assert [len(p['/Annots']) for p in reader.pages]==([1,3,2] if multipage else [3,3])
    for name,page_index in [('party.answer',0),('party.answer_copy1',1)]:
        widgets=[w for w in inspect_pdf(saved)['formDesignWidgets'] if w['fieldName']==name];assert [w['pageIndex'] for w in widgets]==(([0,1,1] if page_index==0 else [1,2,2]) if multipage else [page_index]*3);assert [w['radioChecked'] for w in widgets]==[False,True,False];assert all(w['radioValue']=='No' and w['required'] for w in widgets)
    assert 'Original radio body' in reader.pages[0].extract_text() and 'Second control' in reader.pages[1].extract_text()
    assert (await editor.workspace.afile_bytes(key,path))[0]==source
