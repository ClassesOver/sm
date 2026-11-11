"""Pillow PNG fixture and independent pypdf/Pillow verification of actual downloads."""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream, IndirectObject


def make(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    pixels = [(255, 0, 0, 255), (0, 255, 0, 128), (0, 0, 255, 0), (255, 255, 255, 255)]
    for mode, name in [('RGB', 'opaque'), ('RGBA', 'alpha')]:
        image = Image.new(mode, (2, 2))
        image.putdata([p[:3] if mode == 'RGB' else p for p in pixels])
        image.save(directory / (name + '.png'), format='PNG')
    return {'ok': True, 'files': ['opaque.png', 'alpha.png']}


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
    assert [str(a['/Subtype']) for a in annots] == ['/Underline', '/Stamp', '/Stamp', '/Line']
    marker = next(op for op in staged if op['kind'] == 'addMarkup')
    near(annots[0]['/QuadPoints'], [v for quad in marker['quads'] for v in quad])
    near(annots[0]['/C'], marker['color'])
    assert annots[0]['/AP']['/N'].get_object().get_data()
    pictures = []
    for annotation, op in zip(annots[1:3], [op for op in staged if op.get('shape') == 'image'], strict=True):
        original = Image.open(BytesIO(base64.b64decode(op['image'], validate=True))).convert('RGBA')
        expected_rgb, expected_alpha = original.convert('RGB').tobytes(), original.getchannel('A').tobytes()
        assert annotation['/Type'] == '/Annot' and annotation['/F'] == 4
        assert '/GenOfficeFormField' not in annotation and '/Contents' not in annotation
        page_ref = annotation.raw_get('/P')
        assert isinstance(page_ref, IndirectObject) and page_ref == output.pages[0].indirect_reference
        near(annotation['/Rect'], op['rect'])
        x1, y1, x2, y2 = op['rect']
        width, height = x2 - x1, y2 - y1
        ap = annotation['/AP']['/N'].get_object()
        assert ap['/Type'] == '/XObject' and ap['/Subtype'] == '/Form'
        near(ap['/BBox'], [0, 0, width, height])
        near(ap.get('/Matrix', [1, 0, 0, 1, 0, 0]), [1, 0, 0, 1, 0, 0])
        path = ContentStream(ap, output).operations
        assert [k for _, k in path] == [b'q', b'cm', b'Do', b'Q']
        rotation = output.pages[0].rotation % 360
        cm = {0: [width, 0, 0, height, 0, 0], 90: [0, height, -width, 0, width, 0], 180: [-width, 0, 0, -height, width, height], 270: [0, -height, width, 0, 0, height]}[rotation]
        near(path[1][0], cm)
        assert str(path[2][0][0]) == '/Im0'
        assert set(ap['/Resources']) == {'/XObject'} and set(ap['/Resources']['/XObject']) == {'/Im0'}
        image = ap['/Resources']['/XObject']['/Im0'].get_object()
        assert image['/Type'] == '/XObject' and image['/Subtype'] == '/Image'
        assert image['/BitsPerComponent'] == 8 and image['/ColorSpace'] == '/DeviceRGB'
        assert (image['/Width'], image['/Height']) == original.size
        assert '/Decode' not in image and '/ImageMask' not in image
        assert image.get_data() == expected_rgb
        has_alpha = any(value != 255 for value in expected_alpha)
        if has_alpha:
            smask = image['/SMask'].get_object()
            assert smask['/BitsPerComponent'] == 8 and smask['/ColorSpace'] == '/DeviceGray'
            assert (smask['/Width'], smask['/Height']) == original.size
            near(smask['/Decode'], [0, 1])
            assert smask.get_data() == expected_alpha
        else:
            assert '/SMask' not in image
        pictures.append({'rect': op['rect'], 'pixelSize': list(original.size), 'rgbSha256': hashlib.sha256(expected_rgb).hexdigest(), 'alphaSha256': hashlib.sha256(expected_alpha).hexdigest() if has_alpha else None, 'appearanceMatrix': list(map(float, path[1][0]))})
    arrow = next(op for op in staged if op.get('shape') == 'arrow')
    near(annots[3]['/L'], arrow['from'] + arrow['to'])
    assert sum(k == b'm' for _, k in ContentStream(annots[3]['/AP']['/N'].get_object(), output).operations) == 3
    assert not output.get_fields()
    return {'ok': True, 'rows': rows, 'pictures': pictures, 'otherPagesPreserved': True, 'sourceSpaceMarkupAndVectorRetained': True, 'sourceSha256': hashlib.sha256((directory / 'source.pdf').read_bytes()).hexdigest(), 'outputSha256': hashlib.sha256((directory / 'mixed.pdf').read_bytes()).hexdigest()}


if __name__ == '__main__':
    print(json.dumps((make if sys.argv[1] == 'make' else verify)(Path(sys.argv[2]))))
