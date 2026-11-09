"""Real attachment receipt, preview and nonblocking saved download."""
from io import BytesIO
import base64
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
async def test_attachment_preview_save_download_and_exact_removal_without_text_flag(tmp_path):
    editor, context, source, downloads = await fixture(tmp_path, text_enabled=False)
    source = patch_pdf(source, [{'kind':'addAttachment','name':'old.txt','bytesBase64':base64.b64encode(b'old').decode()}])
    await editor.workspace.awrite_bytes(bind_native_workspace(editor.workspace, context.scope), 'native/attachments.pdf', source)
    context = context.model_copy(update={'source_file':ArtifactFile(path='native/attachments.pdf',size=len(source),sha256=hashlib.sha256(source).hexdigest(),mediaType='application/pdf')})
    row = inspect_pdf(source)['attachments'][0]
    operations = [{'kind':'removeAttachment','attachmentId':row['attachmentId'],'expectedAttachmentSha256':row['expectedAttachmentSha256']},{'kind':'addAttachment','name':'new.bin','bytesBase64':base64.b64encode(bytes(range(256))).decode()}]
    preview = await editor.preview(context,expected_sha256=context.source_file.sha256,operations=operations)
    assert preview['previewDigest'] and preview['appliedOperationIndices'] == [0,1]
    assert [item['key'] for item in preview['model']['attachments']] == ['new.bin']
    actual = await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=operations,expected_preview_digest=preview['previewDigest'])
    with pytest.raises(ReportingError):
        await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=[operations[0],{**operations[1],'bytesBase64':'eA=='}],expected_preview_digest=preview['previewDigest'])
    result = await editor.save(context,expected_sha256=context.source_file.sha256,operations=operations,request_id='attachment-save')
    assert result['revisionRegistered'] and not result['validation']['ok']
    _, chunks = await downloads.stream(result['artifacts']['pdf']['downloadUrl'].split('/')[-2],artifact='pdf')
    content = b''.join([chunk async for chunk in chunks])
    assert content == actual['content']
    reader = PdfReader(BytesIO(content))
    assert dict(reader.attachments) == {'new.bin':[bytes(range(256))]}
    assert reader.pages[0].extract_text() == PdfReader(BytesIO(source)).pages[0].extract_text()
    assert (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace,context.scope),context.source_file.path))[0] == source
