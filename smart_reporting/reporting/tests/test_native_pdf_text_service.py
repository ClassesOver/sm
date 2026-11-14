from io import BytesIO
import hashlib

import pytest
from pypdf import PdfReader

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_models import NativeEditorContext
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication
from smart_reporting.reporting.tests.test_pdf_native_text_edits import source_pdf, text_operation

@pytest.fixture
def anyio_backend(): return 'asyncio'

async def fixture(tmp_path, *, text_enabled=True):
    publication,old,downloads=await create_publication(tmp_path)
    content=source_pdf();key=bind_native_workspace(publication.workspace,old.scope)
    await publication.workspace.awrite_bytes(key,'native/source.pdf',content)
    context=NativeEditorContext(documentId='document',revision=1,scope=old.scope,format='pdf',origin='upload',sourceFile=ArtifactFile(path='native/source.pdf',size=len(content),sha256=hashlib.sha256(content).hexdigest(),mediaType='application/pdf'))
    editor=NativeEditorService(publication.workspace,publication.repository,publication.editor_grants,pdf_enabled=True,pdf_text_enabled=text_enabled,publication=publication)
    return editor,context,content,downloads

@pytest.mark.anyio
async def test_text_feature_is_independent_and_confirmation_required(tmp_path):
    editor,context,content,_=await fixture(tmp_path,text_enabled=False)
    operation=text_operation(content,'Amount due 750')
    with pytest.raises(ReportingError) as caught:
        await editor.preview(context,expected_sha256=context.source_file.sha256,operations=[operation])
    assert caught.value.code=='native_pdf_text_disabled'
    editor.pdf_text_enabled=True
    with pytest.raises(ReportingError) as caught:
        await editor.save(context,expected_sha256=context.source_file.sha256,operations=[operation],request_id='save')
    assert caught.value.code=='native_pdf_text_confirmation_required'
    assert not editor.repository.rows

@pytest.mark.anyio
async def test_confirmed_text_preview_saves_applied_and_skipped_with_real_download(tmp_path):
    editor,context,content,downloads=await fixture(tmp_path)
    operation=text_operation(content,'Amount due 750')
    skipped={**text_operation(content,'X'*1000,index=1)}
    operations=[operation,skipped]
    preview=await editor.preview(context,expected_sha256=context.source_file.sha256,operations=operations)
    assert len(preview['skippedOperations'])==1
    assert preview['appliedOperationIndices']==[0]
    assert preview['model']['pages'][0]['textObjects']
    with pytest.raises(ReportingError) as caught:
        await editor.save(context,expected_sha256=context.source_file.sha256,operations=operations,request_id='wrong',confirmed_preview_digest='0'*64)
    assert caught.value.code=='native_pdf_text_preview_changed'
    result=await editor.save(context,expected_sha256=context.source_file.sha256,operations=operations,request_id='save',confirmed_preview_digest=preview['previewDigest'])
    assert result['revisionRegistered']
    assert not result['validation']['ok']
    assert any(issue['code']=='native_pdf_text_skipped' for issue in result['validation']['issues'])
    url=result['artifacts']['pdf']['downloadUrl'];raw=url.split('/')[-2]
    _,chunks=await downloads.stream(raw,artifact='pdf');revised=b''.join([chunk async for chunk in chunks])
    text=PdfReader(BytesIO(revised)).pages[0].extract_text()
    assert 'Amount due 750' in text and 'UNCHANGED CONTROL' in text and 'Amount due 500' not in text
    assert (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace,context.scope),context.source_file.path))[0]==content


@pytest.mark.anyio
async def test_pdf_preview_file_matches_confirmed_semantics_and_rejects_changed_preview(tmp_path):
    editor,context,content,_=await fixture(tmp_path)
    operations=[text_operation(content,'Amount due 750')]
    preview=await editor.preview(context,expected_sha256=context.source_file.sha256,operations=operations)
    result=await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=operations,expected_preview_digest=preview['previewDigest'])
    assert 'Amount due 750' in PdfReader(BytesIO(result['content'])).pages[0].extract_text()
    assert result['previewDigest']==preview['previewDigest']
    with pytest.raises(ReportingError) as caught:
        await editor.preview_file(context,expected_sha256=context.source_file.sha256,operations=operations,expected_preview_digest='0'*64)
    assert caught.value.code=='native_pdf_text_preview_changed'
