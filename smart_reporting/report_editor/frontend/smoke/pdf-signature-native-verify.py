"""独立 pypdf/PyMuPDF/Pillow 回读签名，不调用产品 writer。"""
import base64
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image
from pypdf import PdfReader


def canonical(value):
    if hasattr(value, 'get_object') and value.get_object() is not value:
        return canonical(value.get_object())
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items() if k not in ['/P', '/Parent']}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return str(value)


def verify(directory):
    source_bytes = (directory / 'source.pdf').read_bytes()
    output_bytes = (directory / 'downloaded.pdf').read_bytes()
    saved = json.loads((directory / 'save.json').read_text())
    request, result = saved['request'], saved['result']
    assert hashlib.sha256(source_bytes).hexdigest() == request['expectedSha256']
    assert hashlib.sha256(output_bytes).hexdigest() == result['artifacts']['pdf']['sha256']
    assert len(output_bytes) == result['artifacts']['pdf']['size']
    assert result['revisionRegistered'] is True
    assert result['validation']['ok'] is False and result['validation']['issues']
    operations = request['operations']
    assert len(operations) == 3 and [o['shape'] for o in operations] == ['ink', 'image', 'image']
    before, after = PdfReader(BytesIO(source_bytes), strict=True), PdfReader(BytesIO(output_bytes), strict=True)
    a, b = pymupdf.open(stream=source_bytes, filetype='pdf'), pymupdf.open(stream=output_bytes, filetype='pdf')
    assert len(before.pages) == len(after.pages) == 3
    assert canonical(before.metadata) == canonical(after.metadata)
    assert a.get_toc() == b.get_toc()
    assert canonical(before.get_fields()) == canonical(after.get_fields())
    images = []
    for index, (old, new) in enumerate(zip(before.pages, after.pages, strict=True)):
        assert old.get_contents().get_data() == new.get_contents().get_data(), '正文内容流'
        assert canonical(old.get('/Resources')) == canonical(new.get('/Resources')), '页面资源'
        assert tuple(old.mediabox) == tuple(new.mediabox) and tuple(old.cropbox) == tuple(new.cropbox)
        assert old.rotation == new.rotation
        assert a[index].get_text() == b[index].get_text()
        if index:
            assert canonical(old.get('/Annots')) == canonical(new.get('/Annots')), '其他页面原有注释'
            assert a[index].get_pixmap().samples == b[index].get_pixmap().samples
            continue
        annots = [n.get_object() for n in new['/Annots']]
        assert [n['/Subtype'] for n in annots] == ['/Ink', '/Stamp', '/Stamp']
        assert [[float(v) for v in p] for p in annots[0]['/InkList']] == operations[0]['paths']
        assert [float(v) for v in annots[0]['/C']] == operations[0]['color']
        assert float(annots[0]['/BS']['/W']) == operations[0]['width']
        for annotation, operation in zip(annots[1:], operations[1:], strict=True):
            assert [float(v) for v in annotation['/Rect']] == operation['rect']
            assert annotation['/F'] & 4, '可打印批注'
            appearance = annotation['/AP']['/N'].get_object()
            image = appearance['/Resources']['/XObject']['/Im0'].get_object()
            original = Image.open(BytesIO(base64.b64decode(operation['image']))).convert('RGBA')
            assert (image['/Width'], image['/Height']) == original.size
            assert image.get_data() == original.convert('RGB').tobytes(), '签名真实RGB像素'
            if '/SMask' in image:
                assert image['/SMask'].get_object().get_data() == original.getchannel('A').tobytes(), '签名透明度'
            else:
                assert original.getchannel('A').getextrema() == (255, 255)
            images.append({'width': original.width, 'height': original.height, 'imageSha256': hashlib.sha256(base64.b64decode(operation['image'])).hexdigest()})
    assert a[0].get_pixmap().samples != b[0].get_pixmap().samples, '签名实际可见'
    a.close(); b.close()
    return {'ok': True, 'sourceSha256': hashlib.sha256(source_bytes).hexdigest(), 'outputSha256': hashlib.sha256(output_bytes).hexdigest(), 'pageCount': 3, 'nativeTypes': ['Ink', 'Stamp', 'Stamp'], 'images': images, 'validationFailedButDownloadIssued': True, 'preserved': ['正文内容流', '页面资源', '页面几何', '元数据', '目录', '原有注释', '其他页渲染', '表单字段']}


if __name__ == '__main__':
    directory = Path(sys.argv[1])
    result = verify(directory)
    (directory / 'independent-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
