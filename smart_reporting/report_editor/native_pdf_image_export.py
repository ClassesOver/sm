"""已保存 PDF 的会话内图片 ZIP 下载；不创建持久化产物或授权链接。"""
from __future__ import annotations

import hashlib
import json
import math
from io import BytesIO
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pymupdf

from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.models import ReportingError

MAX_SOURCE_BYTES=24*1024*1024
MAX_EXPORT_BYTES=64*1024*1024
MAX_PAGE_PIXELS=20_000_000
MAX_TOTAL_PIXELS=100_000_000

def _invalid(message='图片导出参数无效，支持 1–50 个不重复页码、PNG/JPEG 和 72–216 DPI。'):
    return ReportingError('native_pdf_image_export_invalid',message)

def render_pdf_images(content:bytes,*,pages:list[int],image_format:str='png',dpi:int=144):
    if (not isinstance(pages,list) or not 1<=len(pages)<=50 or any(type(page) is not int or page<1 for page in pages)
        or len(set(pages))!=len(pages) or image_format not in {'png','jpeg'} or type(dpi) is not int or not 72<=dpi<=216):raise _invalid()
    if not isinstance(content,bytes) or not 1<=len(content)<=MAX_SOURCE_BYTES or not content.startswith(b'%PDF-'):raise _invalid('来源不是有效的有界 PDF。')
    try:document=pymupdf.open(stream=content,filetype='pdf')
    except Exception:raise _invalid('PDF 来源无法解析。') from None
    with document:
        if document.is_encrypted or document.needs_pass or any(page>len(document) for page in pages):raise _invalid('PDF 受保护或所选页码超出范围。')
        scale=dpi/72;total=0
        for number in pages:
            rect=document[number-1].rect
            if not all(math.isfinite(value) for value in (rect.width,rect.height)) or rect.width<=0 or rect.height<=0:raise _invalid('PDF 页面尺寸无效。')
            pixels=math.ceil(rect.width*scale)*math.ceil(rect.height*scale);total+=pixels
            if pixels>MAX_PAGE_PIXELS or total>MAX_TOTAL_PIXELS:raise _invalid('图片导出超过单页 2000 万或合计 1 亿像素预算，请减少页数或 DPI。')
        source_sha=hashlib.sha256(content).hexdigest();output=BytesIO();entries=[];extension='png' if image_format=='png' else 'jpg'
        with ZipFile(output,'w',compression=ZIP_STORED,allowZip64=False) as archive:
            def append(name,data):
                if output.tell()+len(data)+len(name.encode())+1024>MAX_EXPORT_BYTES:raise _invalid('图片 ZIP 超过 64 MiB，请减少页数或 DPI。')
                info=ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=ZIP_STORED;info.external_attr=0o600<<16;archive.writestr(info,data)
            for number in pages:
                pixmap=document[number-1].get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=pymupdf.csRGB,alpha=False,annots=True)
                image=pixmap.tobytes(image_format,jpg_quality=90);name=f'page-{number}.{extension}'
                append(name,image);entries.append({'page':number,'name':name,'width':pixmap.width,'height':pixmap.height,'sha256':hashlib.sha256(image).hexdigest(),'size':len(image)})
            append('manifest.json',json.dumps({'sourceSha256':source_sha,'pages':pages,'format':image_format,'dpi':dpi,'images':entries},ensure_ascii=False,sort_keys=True).encode())
        raw=output.getvalue()
        if len(raw)>MAX_EXPORT_BYTES:raise _invalid('图片 ZIP 超过 64 MiB。')
        return {'content':raw,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'filename':f'pdf-pages-{image_format}.zip','mediaType':'application/zip','pages':pages,'sourceSha256':source_sha}

async def export_pdf_images(editor,context,*,expected_sha256:str,pages:list[int],image_format:str='png',dpi:int=144):
    editor.require_enabled('pdf')
    if context.format!='pdf':raise ReportingError('native_format_invalid','只有 PDF 可以导出页面图片。')
    if expected_sha256!=context.source_file.sha256:raise ReportingError('native_source_changed','PDF 来源身份已变化，请重新打开修订。')
    content=await editor.read_file(context)
    if hashlib.sha256(content).hexdigest()!=expected_sha256:raise ReportingError('native_source_changed','PDF 实际文件身份已变化。')
    return await run_office_engine(render_pdf_images,content,pages=pages,image_format=image_format,dpi=dpi)
