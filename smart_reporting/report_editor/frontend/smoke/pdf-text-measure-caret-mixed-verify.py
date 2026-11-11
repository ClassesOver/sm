"""Independent pypdf/Poppler checks of real measure/caret mixed downloads."""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops
from reportlab.pdfbase.pdfmetrics import stringWidth
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, IndirectObject, NameObject, RectangleObject


def near(actual, expected, tolerance=.0051):
    assert len(actual) == len(expected), (actual, expected)
    assert all(abs(float(a) - float(b)) < tolerance for a, b in zip(actual, expected)), (actual, expected)


def render_expanded_comparison(directory: Path, filename: str):
    """A diagnostic copy expands matching Rect/BBox together, preserving 1:1 placement."""
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(directory / filename))
    for page in writer.pages:
        for ref in page.get('/Annots', []):
            annotation = ref.get_object()
            if annotation['/Subtype'] == '/Line' and '/Contents' in annotation:
                box = list(page.cropbox)
                annotation[NameObject('/Rect')] = RectangleObject(box)
                annotation['/AP']['/N'].get_object()[NameObject('/BBox')] = RectangleObject(box)
    with (directory / 'diagnostic-expanded.pdf').open('wb') as stream:
        writer.write(stream)
    for path, name in [(directory / filename, 'actual-render'), (directory / 'diagnostic-expanded.pdf', 'expanded-render')]:
        subprocess.run(['pdftoppm', '-r', '144', '-f', '1', '-l', '1', '-singlefile', '-png', str(path), str(directory / name)], check=True, capture_output=True)
    before = Image.open(directory / 'actual-render.png').convert('RGB')
    after = Image.open(directory / 'expanded-render.png').convert('RGB')
    assert before.size == after.size
    changed = sum(pixel != (0, 0, 0) for pixel in ImageChops.difference(before, after).getdata())
    return {'changedPixels': changed, 'renderSize': list(before.size), 'actualPng': 'actual-render.png', 'expandedDiagnosticPng': 'expanded-render.png'}


def verify(directory: Path):
    source, output = PdfReader(directory / 'source.pdf'), PdfReader(directory / 'mixed.pdf')
    staged = json.loads((directory / 'staged.json').read_text())
    bounds_case = os.environ.get('PDF_MEASURE_LABEL_BOUNDS_SMOKE') == '1'
    expected_labels = ['3.00 m', '0.04 m'] if bounds_case else ['3.00 m', '1.50 m']
    expected_lines = [[80, 200, 240, 200], [80, 300, 82, 300]] if bounds_case else [[30, 100, 240, 260], [45, 40, 150, 120]]
    staged_measures = [op for op in staged if op.get('kind') == 'addDrawing' and op.get('shape') == 'measure']
    assert [op['label'] for op in staged_measures] == expected_labels
    assert len(staged_measures) == len(expected_lines)
    for op, line in zip(staged_measures, expected_lines, strict=True):
        near(op['from'] + op['to'], line)
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
    assert [str(a['/Subtype']) for a in annots] == ['/Underline', '/Line', '/Caret', '/Line']
    marker = next(op for op in staged if op['kind'] == 'addMarkup')
    near(annots[0]['/QuadPoints'], [v for quad in marker['quads'] for v in quad])
    near(annots[0]['/C'], marker['color'])
    assert annots[0]['/AP']['/N'].get_object().get_data()
    measured = []
    for annotation, op in zip(annots[1:], [op for op in staged if op['kind'] == 'addDrawing'], strict=True):
        assert annotation['/Type'] == '/Annot' and annotation['/F'] == 4
        assert set(annotation) <= {'/Type', '/Subtype', '/Rect', '/C', '/F', '/P', '/AP', '/T', '/BS', '/L', '/Contents'}
        page_ref = annotation.raw_get('/P')
        assert isinstance(page_ref, IndirectObject) and page_ref == output.pages[0].indirect_reference
        near(annotation['/C'], op['color'])
        ap = annotation['/AP']['/N'].get_object()
        assert ap['/Type'] == '/XObject' and ap['/Subtype'] == '/Form'
        near(ap.get('/Matrix', [1, 0, 0, 1, 0, 0]), [1, 0, 0, 1, 0, 0])
        path = ContentStream(ap, output).operations
        if op['shape'] == 'caret':
            x, y = op['point']
            assert annotation['/Subtype'] == '/Caret' and '/BS' not in annotation and '/Resources' not in ap
            near(annotation['/Rect'], [x - 10, y - 10, x + 10, y + 10])
            assert [k for _, k in path] == [b'rg', b'm', b'l', b'l', b'f']
            for (args, _), want in zip(path[:4], [op['color'], [x, y], [x - 8, y - 6], [x + 8, y - 6]], strict=True):
                near(args, want)
            measured.append({'shape': 'caret', 'point': op['point'], 'filledTriangle': True})
        else:
            assert op['shape'] == 'measure' and annotation['/Subtype'] == '/Line'
            fx, fy = op['from']
            tx, ty = op['to']
            mx, my = (fx + tx) / 2, (fy + ty) / 2
            angle = math.atan2(ty - fy, tx - fx)
            tilt = angle + math.pi if abs(angle) > math.pi / 2 else angle
            c, s = math.cos(tilt), math.sin(tilt)
            pad = op['width'] + 2
            # Independently use ReportLab's Standard14 Helvetica advance metrics;
            # AP uses literal Tj (no kerning) and the serialized two-decimal Tm.
            a, b, cc, d, e, f = map(float, path[10][0])
            xs, ys = [fx, tx, float(path[4][0][0]), float(path[5][0][0])], [fy, ty, float(path[4][0][1]), float(path[5][0][1])]
            advance = 0
            for char in op['label']:
                # Adobe Helvetica AFM full-font FontBBox, in 1000-em units.
                for gx in [-166, 1000]:
                    for gy in [-225, 931]:
                        px, py = advance + gx * .009, gy * .009
                        xs.append(a * px + cc * py + e)
                        ys.append(b * px + d * py + f)
                advance += stringWidth(char, 'Helvetica', 9)
            near(annotation['/Rect'], [min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad])
            near(annotation['/L'], op['from'] + op['to'])
            near([annotation['/BS']['/W']], [op['width']])
            assert str(annotation['/Contents']) == op['label']
            assert [k for _, k in path] == [b'w', b'J', b'j', b'RG', b'm', b'l', b'S', b'BT', b'rg', b'Tf', b'Tm', b'Tj', b'ET']
            for index, want in [(0, [op['width']]), (1, [1]), (2, [1]), (3, op['color']), (4, op['from']), (5, op['to']), (8, op['color']), (10, [c, s, -s, c, mx, my + 6])]:
                near(path[index][0], want)
            assert str(path[9][0][0]) == '/F1' and float(path[9][0][1]) == 9
            assert str(path[11][0][0]) == op['label']
            assert set(ap['/Resources']) == {'/Font'} and set(ap['/Resources']['/Font']) == {'/F1'}
            assert isinstance(ap['/Resources']['/Font'].raw_get('/F1'), IndirectObject)
            font = ap['/Resources']['/Font']['/F1'].get_object()
            assert set(font) == {'/Type', '/Subtype', '/BaseFont', '/Encoding'}
            assert [str(font[key]) for key in ['/Type', '/Subtype', '/BaseFont', '/Encoding']] == ['/Font', '/Type1', '/Helvetica', '/WinAnsiEncoding']
            measured.append({'shape': 'measure', 'label': op['label'], 'textMatrix': list(map(float, path[10][0])), 'font': '/Helvetica'})
        near(ap['/BBox'], annotation['/Rect'])
    assert [item['shape'] for item in measured] == ['measure', 'caret', 'measure']
    assert [item['label'] for item in measured if item['shape'] == 'measure'] == expected_labels
    assert not output.get_fields()
    render = render_expanded_comparison(directory, 'mixed.pdf')
    assert render['changedPixels'] == 0, render
    return {'ok': True, 'rows': rows, 'measured': measured, 'diagonalLabelsRenderUnclipped': True, 'render': render, 'otherPagesPreserved': True, 'sourceSpaceMarkupRetained': True, 'sourceSha256': hashlib.sha256((directory / 'source.pdf').read_bytes()).hexdigest(), 'outputSha256': hashlib.sha256((directory / 'mixed.pdf').read_bytes()).hexdigest()}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[2]))))
