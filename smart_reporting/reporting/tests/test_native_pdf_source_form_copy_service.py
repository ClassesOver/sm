"""Source field clones retain real PDF values through preview, confirmation and download."""
from io import BytesIO
import hashlib
import pytest
from pypdf import PdfReader
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
@pytest.mark.parametrize("field_kind",["text","date","signature"])
async def test_existing_form_copy_preview_save_download_preserves_source_and_properties(tmp_path,field_kind):
    editor,old,empty,downloads=await fixture(tmp_path,text_enabled=False)
    page=inspect_pdf(empty)['pages'][0]['pageId']
    field_name='Signature1' if field_kind=='signature' else 'customer.name'
    source_value='14/11/2026' if field_kind=='date' else 'Alice'
    source=patch_pdf(empty,[{'kind':'createFormField','sourceSha256':old.source_file.sha256,'pageId':page,'fieldName':field_name,'fieldKind':field_kind,'rect':[50,60,170,84],'required':True,**({} if field_kind=='signature' else {'value':source_value}),**({'dateFormat':'dd/mm/yyyy'} if field_kind=='date' else {})}])
    workspace_key=bind_native_workspace(editor.workspace,old.scope)
    await editor.workspace.awrite_bytes(workspace_key,'native/source-with-fields.pdf',source)
    sha=hashlib.sha256(source).hexdigest()
    context=NativeEditorContext(documentId='document',revision=1,scope=old.scope,format='pdf',origin='upload',sourceFile=ArtifactFile(path='native/source-with-fields.pdf',size=len(source),sha256=sha,mediaType='application/pdf'))
    model=inspect_pdf(source);w=model['formDesignWidgets'][0];assert w['copyEditable'] is True
    operations=[{'kind':'createFormField','sourceSha256':sha,'pageId':model['pages'][0]['pageId'],'fieldName':field_name+'_copy1','fieldKind':field_kind,'rect':[60,50,180,74],'required':True,'copyFrom':{key:w[key] for key in ('fieldName','widgetId','widgetIdentity','expectedWidgetSha256')}}]
    with pytest.raises(ReportingError) as caught:
        await editor.save(context,expected_sha256=sha,operations=operations,request_id='copy-unconfirmed')
    assert caught.value.code=='native_pdf_text_confirmation_required'
    assert not editor.repository.rows
    preview=await editor.preview(context,expected_sha256=sha,operations=operations)
    assert preview['appliedOperationIndices']==[0] and preview['skippedOperations']==[]
    actual=await editor.preview_file(context,expected_sha256=sha,operations=operations,expected_preview_digest=preview['previewDigest'])
    result=await editor.save(context,expected_sha256=sha,operations=operations,request_id='copy-confirmed',confirmed_preview_digest=preview['previewDigest'])
    assert result['revisionRegistered'] and result['validation']['ok'] is False
    token=result['artifacts']['pdf']['downloadUrl'].split('/')[-2]
    _,chunks=await downloads.stream(token,artifact='pdf');saved=b''.join([chunk async for chunk in chunks])
    assert saved==actual['content']
    reader=PdfReader(BytesIO(saved));fields=reader.get_fields();terminal={name:field for name,field in fields.items() if field.get('/FT')}
    assert set(terminal)=={field_name,field_name+'_copy1'}
    if field_kind!='signature':
        assert len(fields['customer']['/Kids'])==2
    for name in terminal:
        assert int(fields[name].get('/Ff',0))&2
        if field_kind!='signature':
            assert fields[name]['/V']==source_value
    if field_kind=='signature':
        roots=reader.trailer['/Root']['/AcroForm']['/Fields'];annots=reader.pages[0]['/Annots']
        assert {(ref.idnum,ref.generation) for ref in roots}=={(ref.idnum,ref.generation) for ref in annots}
        for ref in annots:
            widget=ref.get_object();assert str(widget['/FT'])=='/Sig'
            assert all(key not in widget for key in ['/V','/DV','/AP','/Kids','/Parent','/ByteRange'])
        assert inspect_pdf(saved)['digitalSignatures']==[]
    if field_kind=='date':
        for widget in reader.pages[0]['/Annots']:
            aa=widget.get_object()['/Parent'].get_object()['/AA']
            assert str(aa['/F']['/JS'])=='AFDate_FormatEx("dd/mm/yyyy");'
            assert str(aa['/K']['/JS'])=='AFDate_KeystrokeEx("dd/mm/yyyy");'
    assert 'Amount due 500' in reader.pages[0].extract_text()
    assert (await editor.workspace.afile_bytes(workspace_key,context.source_file.path))[0]==source
