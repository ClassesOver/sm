"""Original-object translations keep existing text feature and preview/download contracts."""
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
@pytest.mark.parametrize('action',['preview','preview_file','save'])
async def test_move_text_requires_existing_text_feature(tmp_path,action):
    editor,context,_,_=await fixture(tmp_path,text_enabled=False)
    options={'expected_sha256':context.source_file.sha256,'operations':[{'kind':'moveText'}]}
    if action=='save':
        options['request_id']='disabled-move'
    with pytest.raises(ReportingError) as caught:
        await getattr(editor,action)(context,**options)
    assert caught.value.code=='native_pdf_text_disabled'
    assert not editor.repository.rows

@pytest.mark.anyio
async def test_move_text_preview_confirmation_save_and_real_download_preserve_source(tmp_path):
    editor,context,source,downloads=await fixture(tmp_path)
    model=inspect_pdf(source,include_text=True)
    target=next(item for item in model['pages'][0]['textObjects'] if item['text']=='Amount due 500')
    operations=[{'kind':'moveText','sourceSha256':context.source_file.sha256,'pageId':model['pages'][0]['pageId'],'objectId':target['objectId'],'expectedTextSha256':target['expectedTextSha256'],'delta':[20,-30]}]
    with pytest.raises(ReportingError) as caught:
        await editor.save(context,expected_sha256=context.source_file.sha256,operations=operations,request_id='unconfirmed-move')
    assert caught.value.code=='native_pdf_text_confirmation_required'
    assert not editor.repository.rows
    preview=await editor.preview(context,expected_sha256=context.source_file.sha256,operations=operations)
    assert preview['appliedOperationIndices']==[0]
    assert preview['skippedOperations']==[]
    actual=await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=operations,expected_preview_digest=preview['previewDigest'])
    result=await editor.save(context,expected_sha256=context.source_file.sha256,operations=operations,request_id='confirmed-move',confirmed_preview_digest=preview['previewDigest'])
    assert result['revisionRegistered']
    assert result['validation']['ok'] is False
    token=result['artifacts']['pdf']['downloadUrl'].split('/')[-2]
    _,chunks=await downloads.stream(token,artifact='pdf')
    saved=b''.join([chunk async for chunk in chunks])
    assert saved==actual['content']
    def baseline(content):
        rows=[]
        PdfReader(BytesIO(content)).pages[0].extract_text(visitor_text=lambda text,cm,tm,font,size:rows.append((text,cm,tm,size)))
        _,cm,tm,size=next(item for item in rows if 'Amount due 500' in item[0])
        return tm[4]*cm[0]+tm[5]*cm[2]+cm[4],tm[4]*cm[1]+tm[5]*cm[3]+cm[5],size
    before=baseline(source);after=baseline(saved)
    assert after==pytest.approx((before[0]+20,before[1]-30,before[2]))
    assert 'UNCHANGED CONTROL' in PdfReader(BytesIO(saved)).pages[0].extract_text()
    assert (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace,context.scope),context.source_file.path))[0]==source
