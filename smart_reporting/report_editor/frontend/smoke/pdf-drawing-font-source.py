"""Generate actual native AP bytes and independently inspect them with pypdf."""
from __future__ import annotations

import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, DecodedStreamObject, NameObject, NumberObject, RectangleObject

from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf


def generate(directory: Path, geometry='default'):
    assert geometry in ('default', 'crop-userunit'), geometry
    directory.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    cropped = geometry == 'crop-userunit'
    page = writer.add_blank_page(width=500 if cropped else 400, height=600 if cropped else 400)
    if cropped:
        page.cropbox = RectangleObject([30, 40, 430, 440])
        page[NameObject('/UserUnit')] = NumberObject(2)
    stream = BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    page_id = inspect_pdf(source)['pages'][0]['pageId']
    common = {'kind': 'addDrawing', 'pageId': page_id, 'color': [.86, .22, .18], 'width': 1}
    operations = [
        {**common, 'shape': 'measure', 'from': [40, 320], 'to': [240, 320], 'label': '3.00 m AV To ffi'},
        {**common, 'shape': 'measure', 'from': [40.003, 220.007], 'to': [180.991, 260.003], 'label': '12.34 m (gj)'},
        {**common, 'shape': 'measure', 'from': [320, 180], 'to': [100, 180], 'label': '0.04 m'},
        {**common, 'shape': 'measure', 'from': [70, 40], 'to': [70, 140], 'label': 'To AV 9.99 m'},
        {**common, 'shape': 'caret', 'point': [300.003, 90.007]},
    ]
    if cropped:
        # These remain PDF user-space coordinates. UserUnit is interpreted by
        # the PDF renderer, not multiplied into native operation coordinates.
        for operation in operations:
            for key in ('from', 'to', 'point'):
                if key in operation:
                    x, y = operation[key]
                    operation[key] = [x + 30, y + 40]
    edited = patch_pdf(source, operations)
    (directory / 'source.pdf').write_bytes(source)
    (directory / 'saved-ap.pdf').write_bytes(edited)
    reader = PdfReader(BytesIO(edited))
    source_page = PdfReader(BytesIO(source)).pages[0]
    source_geometry = {'variant': geometry, 'mediaBox': list(map(float, source_page.mediabox)),
                       'cropBox': list(map(float, source_page.cropbox)),
                       'userUnit': float(source_page.get('/UserUnit', 1))}
    assert list(reader.pages[0].mediabox) == list(source_page.mediabox)
    assert list(reader.pages[0].cropbox) == list(source_page.cropbox)
    assert reader.pages[0].get('/UserUnit', 1) == source_page.get('/UserUnit', 1)
    annotations = [raw.get_object() for raw in reader.pages[0]['/Annots']]
    assert len(annotations) == len(operations)
    evidence = []
    for operation, annotation in zip(operations, annotations, strict=True):
        ap = annotation['/AP']['/N'].get_object()
        instructions = ContentStream(ap, reader).operations
        if operation['shape'] == 'measure':
            assert str(annotation['/Subtype']) == '/Line'
            tm = next(list(map(float, args)) for args, op in instructions if op == b'Tm')
            label = next(str(args[0]) for args, op in instructions if op == b'Tj')
            font = ap['/Resources']['/Font']['/F1'].get_object()
            assert str(font['/BaseFont']) == '/Helvetica'
            assert label == operation['label']
            assert next(float(args[1]) for args, op in instructions if op == b'Tf') == 9
            stroke_width = next(float(args[0]) for args, op in instructions if op == b'w')
            assert stroke_width == operation['width']
            evidence.append({'shape': 'measure', 'label': label, 'tm': tm,
                             'font': '/Helvetica', 'strokeWidth': stroke_width})
        else:
            assert str(annotation['/Subtype']) == '/Caret'
            vertices = [list(map(float, args)) for args, op in instructions if op in (b'm', b'l')]
            assert len(vertices) == 3 and instructions[-1][1] == b'f'
            assert int(annotation['/F']) == 4
            evidence.append({'shape': 'caret', 'vertices': vertices})
    # Independent text-only diagnostic: preserve actual AP text instructions,
    # font resources, BBox and annotation geometry; omit line/caret ink only.
    diagnostic = PdfWriter(clone_from=BytesIO(edited))
    kept = []
    for raw in diagnostic.pages[0]['/Annots']:
        annotation = raw.get_object()
        if str(annotation['/Subtype']) != '/Line':
            continue
        original = annotation['/AP']['/N'].get_object()
        instructions = ContentStream(original, diagnostic)
        instructions.operations = [(args, op) for args, op in instructions.operations
                                   if op in (b'rg', b'BT', b'Tf', b'Tm', b'Tj', b'ET')]
        stream = DecodedStreamObject()
        stream.update({key: value for key, value in original.items() if key not in ('/Filter', '/Length')})
        stream.set_data(instructions.get_data())
        annotation['/AP'][NameObject('/N')] = diagnostic._add_object(stream)
        kept.append(raw)
    diagnostic.pages[0][NameObject('/Annots')] = ArrayObject(kept)
    diagnostic.write(directory / 'saved-labels.pdf')
    result = {'sourceSha256': hashlib.sha256(source).hexdigest(),
              'savedSha256': hashlib.sha256(edited).hexdigest(),
              'geometry': source_geometry, 'operations': operations, 'appearance': evidence}
    (directory / 'native-ap.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    print(json.dumps(generate(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else 'default')))
