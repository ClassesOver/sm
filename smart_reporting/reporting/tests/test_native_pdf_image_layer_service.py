"""Image text-band changes preserve real downloads and visibly change the paint order."""
from io import BytesIO
import hashlib
import pytest
import pymupdf as fitz
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
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
@pytest.mark.parametrize('layer',['belowText','aboveText'])
async def test_image_layer_preview_save_download_preserves_pixels_and_changes_text_occlusion(tmp_path,layer):
    editor,old,_,downloads=await fixture(tmp_path,text_enabled=False)
    stream=BytesIO();c=canvas.Canvas(stream,pagesize=(400,500));image=ImageReader(Image.new('RGB',(20,20),(70,100,200)))
    def draw():
        c.drawImage(image,40,300,200,50)
    if layer=='aboveText':
        draw()
    c.drawString(30,450,'Original body');c.setFont('Helvetica',20);c.drawString(50,320,'COVERED CONTROL')
    if layer=='belowText':
        draw()
    c.drawImage(image,260,80,50,50);c.showPage();c.drawImage(image,40,40,60,60);c.save();source=stream.getvalue();sha=hashlib.sha256(source).hexdigest()
    key=bind_native_workspace(editor.workspace,old.scope);path='native/source-image-layer.pdf';await editor.workspace.awrite_bytes(key,path,source)
    context=NativeEditorContext(documentId='document',revision=1,scope=old.scope,format='pdf',origin='upload',sourceFile=ArtifactFile(path=path,size=len(source),sha256=sha,mediaType='application/pdf'))
    model=inspect_pdf(source);target=next(w for w in model['existingImages'] if w['pageIndex']==0 and w['rect'][0]==40);assert target['layerable']
    operations=[{'kind':'transformExistingImage','sourceSha256':sha,'pageId':target['pageId'],'imageId':target['imageId'],'expectedImageSha256':target['expectedImageSha256'],'rect':target['rect'],'layer':layer}]
    with pytest.raises(ReportingError) as caught:
        await editor.save(context,expected_sha256=sha,operations=operations,request_id='image-layer-unconfirmed')
    assert caught.value.code=='native_pdf_text_confirmation_required' and not editor.repository.rows
    preview=await editor.preview(context,expected_sha256=sha,operations=operations);assert preview['appliedOperationIndices']==[0] and preview['skippedOperations']==[]
    actual=await editor.preview_file(context,expected_sha256=sha,operations=operations,expected_preview_digest=preview['previewDigest'])
    result=await editor.save(context,expected_sha256=sha,operations=operations,request_id='image-layer-confirmed',confirmed_preview_digest=preview['previewDigest']);assert result['revisionRegistered'] and result['validation']['ok'] is False
    token=result['artifacts']['pdf']['downloadUrl'].split('/')[-2];_,chunks=await downloads.stream(token,artifact='pdf');saved=b''.join([chunk async for chunk in chunks]);assert saved==actual['content']
    before=fitz.open(stream=source,filetype='pdf');after=fitz.open(stream=saved,filetype='pdf')
    def images(doc):
        return sorted((p.number,tuple(row['bbox']),row['digest']) for p in doc for row in p.get_image_info(hashes=True))
    def dark(doc):
        pix=doc[0].get_pixmap(clip=fitz.Rect(40,150,240,200),alpha=False);data=pix.samples
        return sum(max(data[i:i+3])<30 for i in range(0,len(data),pix.n))
    assert images(after)==images(before)
    assert dark(after)>dark(before) if layer=='belowText' else dark(after)<dark(before)
    assert after[0].get_text()==before[0].get_text()
    changed=next(w for w in inspect_pdf(saved)['existingImages'] if w['pageIndex']==0 and w['rect'][0]==40);assert changed['aboveText']==(layer=='aboveText')
    assert (await editor.workspace.afile_bytes(key,path))[0]==source
