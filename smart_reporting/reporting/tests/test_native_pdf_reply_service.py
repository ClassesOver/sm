"""Reply parent identity survives real preview/publication/download across timezones."""
from io import BytesIO
import hashlib
import pytest
from pypdf import PdfReader
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf
from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile

@pytest.fixture
def anyio_backend(): return 'asyncio'

@pytest.mark.anyio
@pytest.mark.parametrize('timezone',['UTC','Asia/Tokyo'])
async def test_saved_root_reply_preview_download_preserves_exact_parent(tmp_path,monkeypatch,timezone):
    editor,context,source,downloads=await fixture(tmp_path,text_enabled=False)
    page=inspect_pdf(source)['pages'][0]
    root={'kind':'addTextAnnotation','pageId':page['pageId'],'rect':[30,100,50,118],'text':'identical root','createdMs':0}
    source=patch_pdf(source,[root,root]);model=inspect_pdf(source);parent=model['pages'][0]['notes'][1]
    await editor.workspace.awrite_bytes(bind_native_workspace(editor.workspace,context.scope),'native/thread.pdf',source)
    context=context.model_copy(update={'source_file':ArtifactFile(path='native/thread.pdf',size=len(source),sha256=hashlib.sha256(source).hexdigest(),mediaType='application/pdf')})
    operation={'kind':'replyNote','pageId':model['pages'][0]['pageId'],'annotationId':parent['annotationId'],'expectedAnnotationSha256':parent['expectedAnnotationSha256'],'contents':'回复 750 ✓','createdMs':1793970000123}
    monkeypatch.setenv('TZ',timezone)
    preview=await editor.preview(context,expected_sha256=context.source_file.sha256,operations=[operation]);assert preview['previewDigest'] and preview['appliedOperationIndices']==[0]
    monkeypatch.setenv('TZ','America/Los_Angeles')
    actual=await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=[operation],expected_preview_digest=preview['previewDigest'])
    for change in [{'contents':'changed'},{'expectedAnnotationSha256':'0'*64}]:
        with pytest.raises(ReportingError):await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=[{**operation,**change}],expected_preview_digest=preview['previewDigest'])
    result=await editor.save(context,expected_sha256=context.source_file.sha256,operations=[operation],request_id='reply-save')
    assert result['revisionRegistered'] and not result['validation']['ok']
    _,chunks=await downloads.stream(result['artifacts']['pdf']['downloadUrl'].split('/')[-2],artifact='pdf');content=b''.join([chunk async for chunk in chunks])
    assert content==actual['content']
    reader=PdfReader(BytesIO(content));annots=reader.pages[0]['/Annots'];reply=annots[-1].get_object()
    assert reply['/IRT']==annots[1].get_object() and reply['/RT']=='/R' and reply['/Contents']==operation['contents']
    assert reply['/CreationDate']==reply['/M']=='D:20261106130000Z'
    assert reader.pages[0].extract_text()==PdfReader(BytesIO(source)).pages[0].extract_text()
    assert (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace,context.scope),context.source_file.path))[0]==source
