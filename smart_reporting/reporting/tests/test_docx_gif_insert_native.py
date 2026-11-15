import base64
from io import BytesIO
from zipfile import ZipFile
import pytest
from PIL import Image
from docx import Document
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx


def source():
    doc=Document();doc.add_paragraph('keep');out=BytesIO();doc.save(out);return out.getvalue()


def op(data,picture):
    a=inspect_docx(data)['blocks'][0]
    return {'kind':'insertParagraphImage','blockId':a['blockId'],'expectedObjectSha256':a['expectedObjectSha256'],'position':'after','image':{'mime':'image/gif','base64':base64.b64encode(picture).decode(),'widthPx':3,'heightPx':2}}


def test_native_gif_insert_preserves_original_animated_media_bytes():
    out=BytesIO();Image.new('RGB',(3,2),'red').save(out,format='GIF',save_all=True,append_images=[Image.new('RGB',(3,2),'blue')],duration=80,loop=0);gif=out.getvalue();data=source();result=patch_docx(data,[op(data,gif)])
    with ZipFile(BytesIO(result))as z:
        media=[name for name in z.namelist()if name.startswith('word/media/')and name.endswith('.gif')]
        assert len(media)==1
        assert z.read(media[0])==gif
    assert Document(BytesIO(result)).paragraphs[0].text=='keep'


def test_native_gif_insert_refuses_truncated_data_with_valid_header():
    data=source()
    with pytest.raises(ValueError):patch_docx(data,[op(data,b'GIF89a\x03\x00\x02\x00\x00\x00\x00')])
