"""破坏副本验证独立检查器；不重存修订、不修改原下载与保存回执。"""
import json
import sys
from io import BytesIO
from pathlib import Path
from runpy import run_path

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, FloatObject, NameObject, NumberObject, TextStringObject

verify = run_path(str(Path(__file__).with_name('office-pdf-link-verify.py')))['verify']
directory = Path(sys.argv[1])
original = (directory / 'downloaded.pdf').read_bytes()


def rewritten(change):
    writer = PdfWriter(clone_from=BytesIO(original))
    writer.pdf_header = b'%PDF-1.7'
    change(writer)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def annot(writer, page, index):
    return writer.pages[page]['/Annots'][index].get_object()


def destination(writer):
    annot(writer, 0, 2)[NameObject('/Dest')] = ArrayObject([writer.pages[1].indirect_reference, NameObject('/Fit')])


def crop(writer):
    writer.pages[2][NameObject('/CropBox')] = ArrayObject(map(NumberObject, [0, 0, 290, 390]))


def content(writer):
    stream = DecodedStreamObject()
    stream.set_data(writer.pages[0].get_contents().get_data() + b'\nq 1 0 0 1 0 0 cm Q\n')
    writer.pages[0][NameObject('/Contents')] = writer._add_object(stream)


def image(writer):
    images = writer.pages[2]['/Resources']['/XObject']
    obj = next(value.get_object() for value in images.values() if value.get_object().get('/Subtype') == '/Image')
    obj[NameObject('/Width')] = NumberObject(int(obj['/Width']) + 1)


cases = [
    ('https target', lambda w: annot(w, 0, 0)['/A'].__setitem__(NameObject('/URI'), TextStringObject('https://wrong.example.com')), 'link URI'),
    ('mailto target', lambda w: annot(w, 0, 1)['/A'].__setitem__(NameObject('/URI'), TextStringObject('mailto:wrong@example.com')), 'link URI'),
    ('internal destination', destination, 'link destination'),
    ('expanded link rectangle', lambda w: annot(w, 0, 0)['/Rect'].__setitem__(0, FloatObject(0)), 'link rectangle'),
    ('original link removed', lambda w: w.pages[1]['/Annots'].pop(0), 'original annotations'),
    ('original note changed', lambda w: annot(w, 1, 1).__setitem__(NameObject('/Contents'), TextStringObject('changed')), 'original annotations'),
    ('title changed', lambda w: w.add_metadata({'/Title': 'changed'}), 'document metadata'),
    ('outline changed', lambda w: w._root_object['/Outlines']['/First'].__setitem__(NameObject('/Title'), TextStringObject('changed')), 'document outline'),
    ('crop changed', crop, 'page crop'),
    ('content changed', content, 'page content stream'),
    ('image resource changed', image, 'page resources'),
]
assert verify(directory, rewritten(lambda _: None))['ok']
results = []
for name, change, expected in cases:
    try:
        verify(directory, rewritten(change))
    except AssertionError as error:
        assert expected in str(error), (name, str(error), expected)
        results.append({'name': name, 'rejected': True, 'reason': str(error)})
    else:
        raise AssertionError(f'corruption accepted: {name}')
result = {'ok': True, 'positiveReserializationControl': True, 'originalFileUnchanged': (directory / 'downloaded.pdf').read_bytes() == original, 'cases': results}
(directory / 'verifier-faults.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
