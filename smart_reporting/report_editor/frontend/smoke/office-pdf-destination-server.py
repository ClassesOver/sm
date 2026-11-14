"""目标定位验收：前批下载只读派生链接夹具，复用实际授权/源文件路由。"""
import argparse
import asyncio
import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
from runpy import run_path

import uvicorn
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NullObject, NumberObject, TextStringObject

links = run_path(str(Path(__file__).with_name('office-pdf-saved-links-server.py')))


def fixture(source):
    writer = PdfWriter(clone_from=BytesIO(links['fixture'](source)))
    cases = [
        ('xyz', 1, 'XYZ', [80, 230, 2], [80, 170], None),
        ('fit', 1, 'Fit', [], [0, 0], None),
        ('fit-b', 1, 'FitB', [], [0, 0], None),
        ('fit-h', 1, 'FitH', [250], [0, 150], None),
        ('fit-bh', 1, 'FitBH', [250], [0, 150], None),
        ('fit-v', 1, 'FitV', [50], [50, 0], None),
        ('fit-bv', 1, 'FitBV', [50], [50, 0], None),
        ('fit-r', 1, 'FitR', [50, 100, 250, 300], [50, 100], [200, 200]),
        ('rotated-xyz', 2, 'XYZ', [60, 290, 2], [520, 80], None),
        ('rotated-fit-r', 2, 'FitR', [60, 260, 180, 290], [460, 80], [60, 240]),
        ('xyz-null-preserve-zoom', 1, 'XYZ', [None, None, 0], [0, 0], None),
        ('xyz-no-zoom', 1, 'XYZ', [80, 230], [80, 170], None),
        ('fit-h-default', 1, 'FitH', [], [0, 0], None),
        ('fit-v-default', 1, 'FitV', [], [0, 0], None),
        ('invalid', 1, 'XYZ', [80, 230, -2], None, None),
    ]
    annotations = ArrayObject()
    reference = []
    for index, (name, page, kind, parameters, point, size) in enumerate(cases):
        destination = ArrayObject([writer.pages[page].indirect_reference, NameObject('/' + kind), *[NullObject() if p is None else FloatObject(p) for p in parameters]])
        if name == 'xyz':
            named = writer.add_named_destination('positioned-chapter', page)
            named.get_object()[NameObject('/D')] = destination
            target = TextStringObject('positioned-chapter')
        else:
            target = destination
        y = 370 - index * 23
        item = DictionaryObject({NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Link'),
                                 NameObject('/Rect'): ArrayObject(map(NumberObject, [30, y - 18, 180, y])),
                                 NameObject('/Dest'): target, NameObject('/F'): NumberObject(4)})
        ref = writer._add_object(item); annotations.append(ref)
        reference.append({'name': name, 'id': f'{ref.idnum}R', 'page': page, 'kind': kind, 'parameters': parameters, 'unitPoint': point, 'unitRectSize': size,
                          'pageSize': [300, 400] if page == 1 else [700, 520]})
    writer.pages[0][NameObject('/Annots')] = annotations
    output = BytesIO(); writer.write(output)
    return output.getvalue(), reference


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--directory', type=Path, required=True); parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args(); source_path = Path(os.environ['PDF_DESTINATION_SOURCE']); previous = source_path.read_bytes()
    source, cases = fixture(previous)
    app = asyncio.run(links['server']['create_app'](args.directory, args.port, source=source))
    (args.directory / 'reference-destinations.json').write_text(json.dumps({'inputSha256': hashlib.sha256(previous).hexdigest(), 'sourceSha256': hashlib.sha256(source).hexdigest(), 'cases': cases}, indent=2))
    assert source_path.read_bytes() == previous
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
