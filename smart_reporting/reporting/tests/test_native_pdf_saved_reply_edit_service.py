"""Saved leaf reply identity/mutation with actual preview, publication and download."""
from io import BytesIO
import hashlib
import pytest
from pypdf import PdfReader
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf
from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile

@pytest.fixture
def anyio_backend():return 'asyncio'

@pytest.mark.anyio
@pytest.mark.parametrize('kind',['editNote','removeNote'])
async def test_saved_leaf_reply_mutation_preview_save_download(tmp_path,monkeypatch,kind):
    editor,context,source,downloads=await fixture(tmp_path,text_enabled=False)
    page=inspect_pdf(source)['pages'][0]['pageId'];root={'kind':'addTextAnnotation','pageId':page,'localId':'a'*32,'rect':[30,100,50,118],'text':'root','createdMs':0}
    child={'kind':'replyPendingNote','pageId':page,'parentLocalId':'a'*32,'contents':'identical reply','createdMs':0}
    source=patch_pdf(source,[root,child,child]);m=inspect_pdf(source);target=m['pages'][0]['notes'][1]
    await editor.workspace.awrite_bytes(bind_native_workspace(editor.workspace,context.scope),'native/thread.pdf',source)
    context=context.model_copy(update={'source_file':ArtifactFile(path='native/thread.pdf',size=len(source),sha256=hashlib.sha256(source).hexdigest(),mediaType='application/pdf')})
    op={'kind':kind,'pageId':m['pages'][0]['pageId'],'annotationId':target['annotationId'],'expectedAnnotationSha256':target['expectedAnnotationSha256'],**({'contents':'edited reply ✓','modifiedAt':'2026-11-09T09:00:00Z'} if kind=='editNote' else {})}
    monkeypatch.setenv('TZ','Asia/Tokyo');preview=await editor.preview(context,expected_sha256=context.source_file.sha256,operations=[op]);assert preview['previewDigest'] and preview['appliedOperationIndices']==[0]
    monkeypatch.setenv('TZ','America/Los_Angeles');actual=await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=[op],expected_preview_digest=preview['previewDigest'])
    with pytest.raises(ReportingError):await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=[{**op,'expectedAnnotationSha256':'0'*64}],expected_preview_digest=preview['previewDigest'])
    sibling=m['pages'][0]['notes'][2]
    with pytest.raises(ReportingError):await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=[{**op,'annotationId':sibling['annotationId'],'expectedAnnotationSha256':sibling['expectedAnnotationSha256']}],expected_preview_digest=preview['previewDigest'])
    result=await editor.save(context,expected_sha256=context.source_file.sha256,operations=[op],request_id='saved-reply-mutation');assert result['revisionRegistered'] and not result['validation']['ok']
    _,chunks=await downloads.stream(result['artifacts']['pdf']['downloadUrl'].split('/')[-2],artifact='pdf');content=b''.join([chunk async for chunk in chunks]);assert content==actual['content']
    reader=PdfReader(BytesIO(content));a=reader.pages[0]['/Annots'];before=PdfReader(BytesIO(source)).pages[0]['/Annots']
    assert a[0].idnum==before[0].idnum and a[-1].idnum==before[2].idnum and a[-1].get_object()['/Contents']=='identical reply'
    assert a[-1].get_object().raw_get('/IRT')==a[0]
    if kind=='editNote':assert len(a)==3 and a[1].get_object()['/Contents']=='edited reply ✓' and a[1].get_object()['/CreationDate']=='D:19700101000000Z' and a[1].get_object()['/M']=='D:20261109090000Z'
    else:assert len(a)==2
    assert inspect_pdf(content)['pages'][0]['notes'][0]['replyable']
    assert reader.pages[0].extract_text()==PdfReader(BytesIO(source)).pages[0].extract_text()
    assert (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace,context.scope),context.source_file.path))[0]==source
