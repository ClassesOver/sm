"""Multiple new fields share the existing preview/confirmation/revision/download chain."""
from io import BytesIO
import pytest
from pypdf import PdfReader
from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
@pytest.mark.parametrize('include_copy',[False,True])
async def test_multiple_form_creations_preview_confirm_save_download_preserve_source(tmp_path,include_copy):
    editor,context,source,downloads=await fixture(tmp_path,text_enabled=False)
    model=inspect_pdf(source)
    operations=[{'kind':'createFormField','sourceSha256':context.source_file.sha256,'pageId':model['pages'][0]['pageId'],'fieldName':'batch.name','fieldKind':'text','rect':[50,60,170,84],'required':True,'value':'Alice'},
        {'kind':'createFormField','sourceSha256':context.source_file.sha256,'pageId':model['pages'][-1]['pageId'],'fieldName':'batch.agree','fieldKind':'checkbox','rect':[50,100,70,120],'required':False,'checked':True}]
    if include_copy:
        operations.append({**operations[0],'fieldName':'batch.name_copy1','rect':[60,50,180,74]})
    with pytest.raises(ReportingError) as caught:
        await editor.save(context,expected_sha256=context.source_file.sha256,operations=operations,request_id='unconfirmed-fields')
    assert caught.value.code=='native_pdf_text_confirmation_required'
    assert not editor.repository.rows
    preview=await editor.preview(context,expected_sha256=context.source_file.sha256,operations=operations)
    assert preview['appliedOperationIndices']==list(range(len(operations)))
    assert preview['skippedOperations']==[]
    actual=await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=operations,expected_preview_digest=preview['previewDigest'])
    result=await editor.save(context,expected_sha256=context.source_file.sha256,operations=operations,request_id='confirmed-fields',confirmed_preview_digest=preview['previewDigest'])
    assert result['revisionRegistered'] and result['validation']['ok'] is False
    token=result['artifacts']['pdf']['downloadUrl'].split('/')[-2]
    _,chunks=await downloads.stream(token,artifact='pdf')
    saved=b''.join([chunk async for chunk in chunks]);assert saved==actual['content']
    reader=PdfReader(BytesIO(saved));fields=reader.get_fields()
    assert fields['batch.name']['/V']=='Alice'
    if include_copy:
        assert fields['batch.name_copy1']['/V']=='Alice' and int(fields['batch.name_copy1'].get('/Ff',0))&2
    assert fields['batch.agree']['/V'] not in ('/Off',None)
    assert len(reader.pages)==len(PdfReader(BytesIO(source)).pages)
    assert 'Amount due 500' in reader.pages[0].extract_text()
    output_model=inspect_pdf(saved)
    assert {(widget['fieldName'],widget['pageIndex']) for widget in output_model['formDesignWidgets']}=={(operation['fieldName'],int(operation['pageId'].rsplit(':page:',1)[1])) for operation in operations}
    assert (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace,context.scope),context.source_file.path))[0]==source
