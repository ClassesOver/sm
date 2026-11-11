from __future__ import annotations

import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest
from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from smart_reporting.report_editor.native_pdf_image_export import render_pdf_images, export_pdf_images
from smart_reporting.reporting.models import ReportingError

def pdf():
    output=BytesIO();canvas=Canvas(output,pagesize=(100,150),invariant=True)
    for color in [(1,0,0),(0,0,1)]:
        canvas.setFillColorRGB(*color);canvas.rect(0,0,100,150,fill=1,stroke=0);canvas.showPage()
    canvas.save();return output.getvalue()

@pytest.mark.parametrize('format,extension',[('png','png'),('jpeg','jpg')])
def test_true_page_render_zip_retains_requested_order_dimensions_and_colors(format,extension):
    source=pdf();result=render_pdf_images(source,pages=[2,1],image_format=format,dpi=144)
    assert result['sha256']==hashlib.sha256(result['content']).hexdigest()
    assert result['size']==len(result['content'])
    with ZipFile(BytesIO(result['content'])) as archive:
        assert archive.namelist()==[f'page-2.{extension}',f'page-1.{extension}','manifest.json']
        for name,want in [(f'page-2.{extension}',(0,0,255)),(f'page-1.{extension}',(255,0,0))]:
            image=Image.open(BytesIO(archive.read(name)))
            assert image.size==(200,300)
            assert all(abs(a-b)<5 for a,b in zip(image.getpixel((100,150)),want))
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['pages']==[2,1]
        assert manifest['sourceSha256']==hashlib.sha256(source).hexdigest()
    assert render_pdf_images(source,pages=[2,1],image_format=format,dpi=144)['sha256']==result['sha256']

@pytest.mark.parametrize('patch',[{'pages':[]},{'pages':[True]},{'pages':[0]},{'pages':[3]},{'pages':[1,1]},{'pages':list(range(1,52))},{'dpi':71},{'dpi':217},{'dpi':True},{'image_format':'svg'}])
def test_invalid_export_requests_fail_before_rendering(patch):
    with pytest.raises(ReportingError):render_pdf_images(pdf(),**{'pages':[1],'image_format':'png','dpi':144,**patch})

def test_pixel_budgets_reject_huge_page_before_pixmap_allocation():
    import pymupdf
    document=pymupdf.open();document.new_page(width=20000,height=20000)
    with pytest.raises(ReportingError):render_pdf_images(document.tobytes(),pages=[1],dpi=144)

@pytest.mark.anyio
async def test_source_bound_service_exports_saved_bytes_and_rejects_stale_identity():
    source=pdf();sha=hashlib.sha256(source).hexdigest();context=SimpleNamespace(format='pdf',source_file=SimpleNamespace(sha256=sha))
    editor=SimpleNamespace(require_enabled=lambda _:None,read_file=AsyncMock(return_value=source))
    result=await export_pdf_images(editor,context,expected_sha256=sha,pages=[1],dpi=72)
    assert result['sourceSha256']==sha;assert result['mediaType']=='application/zip'
    with pytest.raises(ReportingError):await export_pdf_images(editor,context,expected_sha256='f'*64,pages=[1])
    editor.read_file.return_value=b'%PDF-changed'
    with pytest.raises(ReportingError):await export_pdf_images(editor,context,expected_sha256=sha,pages=[1])
