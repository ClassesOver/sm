"""Removing one image placement preserves the real revision and download contracts."""
from io import BytesIO
import hashlib
import pytest
import pymupdf as fitz
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader
from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.report_editor.native_models import NativeEditorContext
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
async def test_image_placement_delete_preview_save_download_preserves_shared_survivors(tmp_path):
    editor,old,_,downloads=await fixture(tmp_path,text_enabled=False)
    stream=BytesIO();c=canvas.Canvas(stream,pagesize=(400,500));image=ImageReader(Image.new('RGB',(20,20),(200,30,40)));c.drawString(30,450,'Original body');c.drawImage(image,60,90,100,80);c.drawImage(image,240,300,80,60);c.showPage();c.drawImage(image,40,40,60,60);c.save();source=stream.getvalue();sha=hashlib.sha256(source).hexdigest()
    key=bind_native_workspace(editor.workspace,old.scope);path='native/source-images.pdf';await editor.workspace.awrite_bytes(key,path,source)
    context=NativeEditorContext(documentId='document',revision=1,scope=old.scope,format='pdf',origin='upload',sourceFile=ArtifactFile(path=path,size=len(source),sha256=sha,mediaType='application/pdf'))
    model=inspect_pdf(source);target=model['existingImages'][0];assert target['removable'] and not target['replaceable']
    operations=[{'kind':'transformExistingImage','sourceSha256':sha,'pageId':target['pageId'],'imageId':target['imageId'],'expectedImageSha256':target['expectedImageSha256'],'rect':target['rect'],'remove':True}]
    with pytest.raises(ReportingError) as caught:
        await editor.save(context,expected_sha256=sha,operations=operations,request_id='image-delete-unconfirmed')
    assert caught.value.code=='native_pdf_text_confirmation_required' and not editor.repository.rows
    preview=await editor.preview(context,expected_sha256=sha,operations=operations);assert preview['appliedOperationIndices']==[0] and preview['skippedOperations']==[]
    actual=await editor.preview_file(context,expected_sha256=sha,operations=operations,expected_preview_digest=preview['previewDigest'])
    result=await editor.save(context,expected_sha256=sha,operations=operations,request_id='image-delete-confirmed',confirmed_preview_digest=preview['previewDigest']);assert result['revisionRegistered'] and result['validation']['ok'] is False
    token=result['artifacts']['pdf']['downloadUrl'].split('/')[-2];_,chunks=await downloads.stream(token,artifact='pdf');saved=b''.join([chunk async for chunk in chunks]);assert saved==actual['content']
    before=fitz.open(stream=source,filetype='pdf');after=fitz.open(stream=saved,filetype='pdf')
    def images(doc):
        return [(page.number,tuple(row['bbox']),row['digest']) for page in doc for row in page.get_image_info(hashes=True)]
    assert images(after)==images(before)[1:]
    assert [len(p.get_image_info()) for p in after]==[1,1]
    assert 'Original body' in PdfReader(BytesIO(saved)).pages[0].extract_text()
    assert (await editor.workspace.afile_bytes(key,path))[0]==source
