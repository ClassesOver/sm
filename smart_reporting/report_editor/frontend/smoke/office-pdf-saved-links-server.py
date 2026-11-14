"""已保存链接交互：以前批真实下载为来源，派生几何夹具；不覆盖来源或创建修订。"""
import argparse
import asyncio
import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
from runpy import run_path

import pymupdf
import uvicorn
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NullObject, NumberObject, TextStringObject

server = run_path(str(Path(__file__).with_name('pdf-static-text-server.py')))


def fixture(source: bytes):
    writer = PdfWriter(clone_from=BytesIO(source))
    writer.pdf_header = b'%PDF-1.7'
    destination = writer.add_named_destination('chapter-three', 2)
    destination.get_object()[NameObject('/D')] = ArrayObject([writer.pages[2].indirect_reference, NameObject('/XYZ'), NullObject(), NullObject(), NullObject()])
    named = DictionaryObject({NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Link'),
                              NameObject('/Rect'): ArrayObject(map(NumberObject, [190, 280, 270, 310])),
                              NameObject('/Dest'): TextStringObject('chapter-three'), NameObject('/F'): NumberObject(4)})
    annotations = writer.pages[0].get('/Annots')
    if annotations is None:
        annotations = ArrayObject(); writer.pages[0][NameObject('/Annots')] = annotations
    annotations.append(writer._add_object(named))
    page_two_annotations = writer.pages[1].get('/Annots')
    if page_two_annotations is None:
        page_two_annotations = ArrayObject(); writer.pages[1][NameObject('/Annots')] = page_two_annotations
    for action in [
        DictionaryObject({NameObject('/S'): NameObject('/URI'), NameObject('/URI'): TextStringObject('javascript:alert(1)')}),
        DictionaryObject({NameObject('/S'): NameObject('/Launch'), NameObject('/F'): TextStringObject('/tmp/do-not-launch')}),
    ]:
        item = DictionaryObject({NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Link'),
                                 NameObject('/Rect'): ArrayObject(map(NumberObject, [180, 60, 260, 90])), NameObject('/A'): action})
        page_two_annotations.append(writer._add_object(item))
    third = writer.pages[2]
    third[NameObject('/UserUnit')] = NumberObject(2)
    third[NameObject('/CropBox')] = ArrayObject(map(NumberObject, [20, 30, 280, 380]))
    third[NameObject('/Rotate')] = NumberObject(90)
    web = DictionaryObject({NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Link'),
                            NameObject('/Rect'): ArrayObject(map(NumberObject, [60, 260, 180, 290])),
                            NameObject('/A'): DictionaryObject({NameObject('/S'): NameObject('/URI'), NameObject('/URI'): TextStringObject('https://geometry.example.com/keep')})})
    third[NameObject('/Annots')] = ArrayObject([writer._add_object(web)])
    stream = BytesIO(); writer.write(stream)
    return stream.getvalue()


def geometry(document, index):
    page = document[index]
    links = []
    for link in page.get_links():
        if link['kind'] not in [pymupdf.LINK_URI, pymupdf.LINK_GOTO] and not (link['kind'] == pymupdf.LINK_NAMED and link.get('page', -1) >= 0):
            continue
        uri = link.get('uri')
        if uri and not uri.startswith(('https://', 'http://', 'mailto:')):
            continue
        # get_links 已返回旋转后的页面坐标；再次旋转会使独立参照失真。
        rect = link['from']
        links.append({'id': f"{link['xref']}R", 'rect': list(rect), 'url': uri, 'targetPage': link.get('page')})
    return {'width': page.rect.width, 'height': page.rect.height, 'links': links}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4394)
    args = parser.parse_args()
    source_path = Path(os.environ['PDF_SAVED_LINKS_SOURCE'])
    previous = source_path.read_bytes(); source = fixture(previous)
    app = asyncio.run(server['create_app'](args.directory, args.port, source=source))
    doc = pymupdf.open(stream=source, filetype='pdf')
    reference = {'inputSha256': hashlib.sha256(previous).hexdigest(), 'sourceSha256': hashlib.sha256(source).hexdigest(), 'pages': [geometry(doc, index) for index in range(3)], 'scenarios': []}
    for cropped in [False, True]:
        for rotation in [0, 90, 180, 270]:
            doc[0].set_cropbox(pymupdf.Rect(10, 10, 290, 380) if cropped else pymupdf.Rect(0, 0, 300, 400))
            doc[0].set_rotation(rotation)
            reference['scenarios'].append({'name': f"{'crop' if cropped else 'full'}-{rotation}", 'crop': [10, 20, 290, 390] if cropped else None, 'rotation': rotation, **geometry(doc, 0)})
    doc.close()
    assert source_path.read_bytes() == previous
    (args.directory / 'reference-geometry.json').write_text(json.dumps(reference, indent=2))
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
