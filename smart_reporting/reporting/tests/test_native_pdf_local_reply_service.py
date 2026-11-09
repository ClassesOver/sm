"""Local root/reply graph through real preview, publication and warning-bearing download."""
from io import BytesIO
import pytest
from pypdf import PdfReader
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf

@pytest.fixture
def anyio_backend():return 'asyncio'

@pytest.mark.anyio
@pytest.mark.parametrize('legacy_root',[True,False])
async def test_local_root_reply_preview_save_download(tmp_path,monkeypatch,legacy_root):
    editor,context,source,downloads=await fixture(tmp_path,text_enabled=False)
    page=inspect_pdf(source)['pages'][0]['pageId']
    root={'kind':'addTextAnnotation','pageId':page,'localId':'a'*32,'text':'identical root','rect':[30,100,50,118],'createdMs':0}
    second={**root,'localId':'b'*32}
    if legacy_root:second.pop('createdMs')
    reply={'kind':'replyPendingNote','pageId':page,'parentLocalId':'b'*32,'contents':'local 回复 ✓','createdMs':1793970000123}
    operations=[reply,root,second]
    monkeypatch.setenv('TZ','Asia/Tokyo')
    preview=await editor.preview(context,expected_sha256=context.source_file.sha256,operations=operations)
    assert preview['previewDigest'] and preview['appliedOperationIndices']==[0,1,2]
    monkeypatch.setenv('TZ','America/Los_Angeles')
    actual=await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=operations,expected_preview_digest=preview['previewDigest'])
    for change in [{'parentLocalId':'a'*32},{'parentLocalId':'0'*32}]:
        with pytest.raises(ReportingError):await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=[{**reply,**change},root,second],expected_preview_digest=preview['previewDigest'])
    result=await editor.save(context,expected_sha256=context.source_file.sha256,operations=operations,request_id='local-reply-save')
    assert result['revisionRegistered'] and not result['validation']['ok']
    _,chunks=await downloads.stream(result['artifacts']['pdf']['downloadUrl'].split('/')[-2],artifact='pdf');content=b''.join([chunk async for chunk in chunks]);assert content==actual['content']
    reader=PdfReader(BytesIO(content));annots=reader.pages[0]['/Annots'];child=annots[-1].get_object()
    assert child.raw_get('/IRT')==annots[1] and child.raw_get('/IRT')!=annots[0] and child['/RT']=='/R'
    assert child['/CreationDate']==child['/M']=='D:20261106130000Z'
    assert ('/CreationDate' not in annots[1].get_object()) if legacy_root else annots[1].get_object()['/CreationDate']=='D:19700101000000Z'
    assert reader.pages[0].extract_text()==PdfReader(BytesIO(source)).pages[0].extract_text()
