"""Independent pypdf verification of actual styled mixed link downloads."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import ContentStream, IndirectObject, NullObject


def near(actual, expected, tolerance=.0051):
    assert len(actual) == len(expected), (actual, expected)
    assert all(abs(float(a) - float(b)) < tolerance for a, b in zip(actual, expected)), (actual, expected)


def verify(directory: Path):
    source, output = PdfReader(directory / 'source.pdf'), PdfReader(directory / 'mixed.pdf')
    staged = json.loads((directory / 'staged.json').read_text())
    assert len(source.pages) == len(output.pages) == 3
    for index, (before, after) in enumerate(zip(source.pages, output.pages)):
        if index:
            assert before.extract_text().strip() in after.extract_text()
        assert list(before.mediabox) == list(after.mediabox)
        assert list(before.cropbox) == list(after.cropbox)
        assert before.rotation == after.rotation
    assert 'source page one' not in output.pages[0].extract_text()
    found = []
    output.pages[0].extract_text(visitor_text=lambda text, cm, tm, font, size: found.append((text, cm, tm, font, size)))
    rows = []
    for segment, family, size, expected_x in [('AA', 'LiberationMono', 12, 24), ('BB', 'LiberationSerif-BoldItalic', 18, 38.4), ('CC', 'LiberationMono', 12, 62.412)]:
        text, cm, tm, font, pt = next(row for row in found if row[0].strip() == segment)
        assert family in str(font['/BaseFont']) and abs(pt - size) < .002
        x, y = tm[4] * cm[0] + tm[5] * cm[2] + cm[4], tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        assert abs(x - expected_x) < .05 and abs(y - 350) < .002
        descriptor = font['/DescendantFonts'][0].get_object()['/FontDescriptor'].get_object()
        assert len(descriptor['/FontFile2'].get_object().get_data()) > 100
        rows.append({'text': segment, 'font': str(font['/BaseFont']), 'size': pt, 'baseline': [x, y]})
    assert any(list(map(float, v)) == [1, 0, 0] for v, k in ContentStream(output.pages[0].get_contents(), output).operations if k == b'rg')
    annots = [ref.get_object() for ref in output.pages[0]['/Annots']]
    assert [str(a['/Subtype']) for a in annots] == ['/Underline', '/Link', '/Link', '/Link']
    marker = next(op for op in staged if op['kind'] == 'addMarkup')
    near(annots[0]['/QuadPoints'], [v for quad in marker['quads'] for v in quad])
    near(annots[0]['/C'], marker['color'])
    assert annots[0]['/AP']['/N'].get_object().get_data()
    links = []
    for annotation, op in zip(annots[1:], [op for op in staged if op.get('shape') == 'link'], strict=True):
        assert annotation['/Type'] == '/Annot' and annotation['/F'] == 4
        page_ref = annotation.raw_get('/P')
        assert isinstance(page_ref, IndirectObject) and page_ref == output.pages[0].indirect_reference
        near(annotation['/Rect'], op['rect'])
        assert '/AP' not in annotation and '/AA' not in annotation
        if 'url' in op:
            assert set(annotation) == {'/Type', '/Subtype', '/Rect', '/F', '/P', '/A'}
            action = annotation['/A'].get_object()
            assert set(action) == {'/Type', '/S', '/URI'}
            assert action['/Type'] == '/Action' and action['/S'] == '/URI'
            assert str(action['/URI']) == op['url']
            links.append({'rect': op['rect'], 'uri': str(action['/URI'])})
        else:
            assert set(annotation) == {'/Type', '/Subtype', '/Rect', '/F', '/P', '/Dest'}
            destination = annotation['/Dest']
            assert len(destination) == 5 and isinstance(destination[0], IndirectObject)
            assert destination[0] == output.pages[op['destPage'] - 1].indirect_reference
            assert str(destination[1]) == '/XYZ' and all(isinstance(value, NullObject) for value in destination[2:])
            links.append({'rect': op['rect'], 'destinationPage': op['destPage'], 'destinationReference': str(destination[0])})
    assert len(links) == 3 and sum('uri' in link for link in links) == 2
    assert not output.get_fields()
    return {'ok': True, 'rows': rows, 'links': links, 'otherPagesPreserved': True, 'sourceSpaceMarkupRetained': True, 'sourceSha256': hashlib.sha256((directory / 'source.pdf').read_bytes()).hexdigest(), 'outputSha256': hashlib.sha256((directory / 'mixed.pdf').read_bytes()).hexdigest()}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]))))
