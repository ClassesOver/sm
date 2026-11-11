"""Independent openpyxl/source PDF and optional host Calc rendering verification."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import openpyxl
import pymupdf

LABELS = ['Underlined amount', 'Struck adjustment', 'Regular label', 'Both decorations']
EXPECTED = [(True, False), (False, True), (False, False), (True, True)]

def rendered_decorations(page, span):
    x0, _, x1, _ = span['bbox']
    baseline = span['origin'][1]
    found = set()
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0] != 'l':
                continue
            start, end = item[1:3]
            if abs(start.y - end.y) > .05 or abs(start.x - x0) > 1 or abs(end.x - x1) > 1:
                continue
            relative = (baseline - start.y) / span['size']
            if -.35 <= relative < -.03:
                found.add('underline')
            if .15 <= relative <= .62:
                found.add('strike')
    return found

def verify(source: Path, xlsx: Path, rendered: Path | None = None):
    original = pymupdf.open(source)
    assert len(original) == 2
    assert all(label in original[1].get_text() for label in LABELS)
    workbook = openpyxl.load_workbook(xlsx, data_only=False)
    assert workbook.sheetnames == ['Page 1', 'Page 2']
    cells = {cell.value: cell for row in workbook['Page 2'] for cell in row if cell.value is not None}
    assert list(cells) == LABELS
    states = {}
    for label, (underline, strike) in zip(LABELS, EXPECTED):
        font = cells[label].font
        assert (font.u == 'single', bool(font.strike)) == (underline, strike), (label, font)
        assert font.sz == 14 and font.name == 'Liberation Sans'
        assert not font.b and not font.i
        states[label] = {'cell': cells[label].coordinate, 'underline': underline, 'strike': strike}
    first = workbook['Page 1']
    values = [cell.value for row in first for cell in row if cell.value is not None]
    text = '\n'.join(value for value in values if isinstance(value, str))
    for expected in ['Complex quarterly report', 'Left column line 8', 'Right column line 8', 'Region', 'Revenue', 'Margin', 'East', 'West', 'Code 001 / fixed width', 'naïve résumé €']:
        assert expected in text, expected
    for coordinate, expected in [('C6', 12345.67), ('C7', 9876.54), ('F6', .125), ('F7', .098)]:
        assert first[coordinate].value == expected and first[coordinate].data_type == 'n'
    assert first['F6'].number_format == first['F7'].number_format == '0.0%'
    with ZipFile(xlsx) as archive:
        images = [name for name in archive.namelist() if name.startswith('xl/media/') and not name.endswith('/')]
        assert len(images) == 1
        assert b'<drawing ' in archive.read('xl/worksheets/sheet1.xml')
    result = {'ok': True, 'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'xlsxSha256': hashlib.sha256(xlsx.read_bytes()).hexdigest(), 'editableCellDecorations': states, 'originalTableNumbersRetained': True, 'originalPictureCount': len(images), 'overallFidelityPassed': False, 'manualReview': True}
    if rendered is not None:
        document = pymupdf.open(rendered)
        matches = [(page, span) for page in document for block in page.get_text('dict')['blocks'] for line in block.get('lines', []) for span in line['spans'] if span['text'] in LABELS]
        assert len(matches) == 4
        for label, (underline, strike) in zip(LABELS, EXPECTED):
            page, span = next((page, span) for page, span in matches if span['text'] == label)
            assert rendered_decorations(page, span) == ({'underline'} if underline else set()) | ({'strike'} if strike else set()), label
        result.update(hostCalcDecorations=True, renderedPdfSha256=hashlib.sha256(rendered.read_bytes()).hexdigest(), renderedPageCount=len(document))
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('xlsx', type=Path)
    parser.add_argument('rendered_pdf', type=Path, nargs='?')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.source, args.xlsx, args.rendered_pdf)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + '\n')
    print(text)
