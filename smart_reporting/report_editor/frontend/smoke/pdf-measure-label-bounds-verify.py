"""Independent Standard14 metrics and Poppler clipping checks for native measure fixtures."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, NameObject, RectangleObject
from reportlab.pdfbase.pdfmetrics import stringWidth


def verify(directory: Path):
    cases = json.loads((directory / 'cases.json').read_text())
    results = []
    for filename in ['standalone.pdf', 'mixed.pdf']:
        source = directory / filename
        reader = PdfReader(source)
        annotations = [ref.get_object() for ref in reader.pages[0]['/Annots']]
        assert len(annotations) == len(cases)
        measures = []
        for annotation, case in zip(annotations, cases, strict=True):
            ap = annotation['/AP']['/N'].get_object()
            path = ContentStream(ap, reader).operations
            assert [key for _, key in path] == [b'w', b'J', b'j', b'RG', b'm', b'l', b'S', b'BT', b'rg', b'Tf', b'Tm', b'Tj', b'ET']
            assert str(path[11][0][0]) == case['label']
            assert list(annotation['/L']) == case['from'] + case['to']
            font = ap['/Resources']['/Font']['/F1'].get_object()
            assert str(font['/BaseFont']) == '/Helvetica' and str(font['/Encoding']) == '/WinAnsiEncoding'
            a, b, c, d, e, f = map(float, path[10][0])
            xs = [case['from'][0], case['to'][0], float(path[4][0][0]), float(path[5][0][0])]
            ys = [case['from'][1], case['to'][1], float(path[4][0][1]), float(path[5][0][1])]
            advance = 0
            for char in case['label']:
                # Adobe Standard14 Helvetica AFM full-font FontBBox (1000-em).
                for gx in [-166, 1000]:
                    for gy in [-225, 931]:
                        x, y = advance + gx * .009, gy * .009
                        xs.append(a * x + c * y + e)
                        ys.append(b * x + d * y + f)
                advance += stringWidth(char, 'Helvetica', 9)
            expected = [min(xs)-4, min(ys)-4, max(xs)+4, max(ys)+4]
            assert all(abs(float(actual)-want)<1e-8 for actual, want in zip(annotation['/Rect'], expected, strict=True)), (case, annotation['/Rect'], expected)
            assert list(ap['/BBox']) == list(annotation['/Rect'])
            measures.append({'label': case['label'], 'rect': list(map(float, annotation['/Rect'])), 'matrix': [a,b,c,d,e,f], 'unkernedAdvance': advance})
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        for page in writer.pages:
            for ref in page.get('/Annots', []):
                annotation = ref.get_object()
                box = RectangleObject(list(page.cropbox))
                annotation[NameObject('/Rect')] = box
                annotation['/AP']['/N'].get_object()[NameObject('/BBox')] = box
        stem = source.stem
        expanded = directory / f'{stem}-expanded.pdf'
        with expanded.open('wb') as stream:
            writer.write(stream)
        for pdf, suffix in [(source, 'actual'), (expanded, 'expanded')]:
            subprocess.run(['pdftoppm', '-r', '144', '-singlefile', '-png', str(pdf), str(directory / f'{stem}-{suffix}')], check=True, capture_output=True)
        before = Image.open(directory / f'{stem}-actual.png').convert('RGB')
        after = Image.open(directory / f'{stem}-expanded.png').convert('RGB')
        assert before.size == after.size
        difference = ImageChops.difference(before, after).tobytes()
        changed = sum(any(difference[index:index+3]) for index in range(0, len(difference), 3))
        assert changed == 0, (filename, changed)
        results.append({'filename': filename, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'size': source.stat().st_size, 'changedPixels': changed, 'renderSize': list(before.size), 'measures': measures})
    return {'ok': True, 'results': results, 'scope': 'Conservative full-font bounds; existing midpoint origin retained; page CropBox remains authoritative.'}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1])), ensure_ascii=False, indent=2))
