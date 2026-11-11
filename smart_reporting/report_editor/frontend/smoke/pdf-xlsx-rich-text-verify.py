"""Independent mixed inline-run reader plus optional real host Calc checks."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import openpyxl
from openpyxl.cell.rich_text import CellRichText, TextBlock
import pymupdf

LABELS = ['Plain Bold Italic Under Strike Serif', 'Dominant decorated words plain']
FIRST = [('Plain ', False, False, False, False), ('Bold ', True, False, False, False), ('Italic ', False, True, False, False), ('Under ', False, False, True, False), ('Strike ', False, False, False, True), ('Serif', False, False, False, False)]

def font_flags(font):
    return bool(font.b), bool(font.i), font.u == 'single', bool(font.strike)

def decorations(page, bounds, baseline, size):
    found = set()
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0] != 'l':
                continue
            start, end = item[1:3]
            cover = max(0, min(end.x, bounds.x1) - max(start.x, bounds.x0)) / bounds.width
            if abs(start.y - end.y) > .05 or cover < .8:
                continue
            relative = (baseline - start.y) / size
            if -.35 <= relative < -.03:
                found.add('underline')
            if .15 <= relative <= .62:
                found.add('strike')
    return found

def verify(source: Path, xlsx: Path, rendered: Path | None = None):
    original = pymupdf.open(source)
    assert len(original) == 2
    assert all(label in original[1].get_text() for label in LABELS)
    workbook = openpyxl.load_workbook(xlsx, rich_text=True)
    assert workbook.sheetnames == ['Page 1', 'Page 2']
    sheet = workbook['Page 2']
    assert isinstance(sheet['A1'].value, CellRichText), 'A1 must contain native editable rich text'
    assert str(sheet['A1'].value) == LABELS[0]
    assert len(sheet['A1'].value) == 6
    states = []
    for run, (text, bold, italic, underline, strike) in zip(sheet['A1'].value, FIRST):
        assert isinstance(run, TextBlock)
        assert run.text == text and font_flags(run.font) == (bold, italic, underline, strike), (text, run.font)
        assert run.font.sz == 14
        assert run.font.rFont == ('Liberation Serif' if text == 'Serif' else 'Liberation Sans')
        states.append({'text': text, 'family': run.font.rFont, 'bold': bold, 'italic': italic, 'underline': underline, 'strike': strike})
    assert isinstance(sheet['A2'].value, CellRichText) and str(sheet['A2'].value) == LABELS[1]
    dominant, regular = sheet['A2'].value
    assert dominant.text == 'Dominant decorated words ' and font_flags(dominant.font) == (True, True, True, True)
    assert regular.text == 'plain' and font_flags(regular.font) == (False, False, False, False)
    for address in ['A1', 'A2']:
        assert font_flags(sheet[address].font) == (False, False, False, False), 'cell font must not leak dominant run flags'
    assert sheet['A3'].data_type == 'n' and sheet['A3'].value == 12345.67
    first = workbook['Page 1']
    values = [cell.value for row in first for cell in row if cell.value is not None]
    text = '\n'.join(str(value) for value in values if not isinstance(value, (float, int)))
    for expected in ['Complex quarterly report', 'Left column line 8', 'Right column line 8', 'Region', 'Revenue', 'Margin', 'Code 001 / fixed width']:
        assert expected in text, expected
    for coordinate, expected in [('C6', 12345.67), ('C7', 9876.54), ('F6', .125), ('F7', .098)]:
        assert first[coordinate].value == expected and first[coordinate].data_type == 'n'
    assert first['F6'].number_format == first['F7'].number_format == '0.0%'
    with ZipFile(xlsx) as archive:
        images = [name for name in archive.namelist() if name.startswith('xl/media/') and not name.endswith('/')]
        assert len(images) == 1
        assert b'<drawing ' in archive.read('xl/worksheets/sheet1.xml')
    result = {'ok': True, 'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'xlsxSha256': hashlib.sha256(xlsx.read_bytes()).hexdigest(), 'editableMixedRuns': states, 'dominantFlagsNeutralized': True, 'minorityRegularRestored': True, 'numericCellsRetained': True, 'originalTableAndPictureRetained': True, 'dominantDeclaredFamily': dominant.font.rFont, 'overallFidelityPassed': False, 'manualReview': True}
    if rendered is not None:
        document = pymupdf.open(rendered)
        rows = [(page, line) for page in document for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])]
        first_page, first_line = next((page, line) for page, line in rows if ''.join(span['text'] for span in line['spans']) == LABELS[0])
        second_page, second_line = next((page, line) for page, line in rows if ''.join(span['text'] for span in line['spans']) == LABELS[1])
        fonts = {}
        for token, bold, italic, underline, strike in FIRST:
            token = token.strip()
            span = next(span for span in first_line['spans'] if token in span['text'])
            assert (bool(span['flags'] & 16), bool(span['flags'] & 2)) == (bold, italic), (token, span)
            if token == 'Serif':
                assert 'Serif' in span['font']
            word = next(word for word in first_page.get_text('words') if word[4] == token)
            assert decorations(first_page, pymupdf.Rect(word[:4]), span['origin'][1], span['size']) == ({'underline'} if underline else set()) | ({'strike'} if strike else set()), token
            fonts[token] = span['font']
        styled_span = next(span for span in second_line['spans'] if 'Dominant' in span['text'])
        plain_span = next(span for span in second_line['spans'] if span['text'] == 'plain')
        assert styled_span['flags'] & 16 and styled_span['flags'] & 2
        assert not plain_span['flags'] & (16 | 2)
        assert decorations(second_page, pymupdf.Rect(styled_span['bbox']), styled_span['origin'][1], styled_span['size']) == {'underline', 'strike'}
        assert decorations(second_page, pymupdf.Rect(plain_span['bbox']), plain_span['origin'][1], plain_span['size']) == set()
        result.update(hostCalcMixedRuns=True, hostCalcMinorityRegular=True, hostFirstRunFonts=fonts, dominantRenderedFamily=styled_span['font'], renderedPdfSha256=hashlib.sha256(rendered.read_bytes()).hexdigest(), renderedPageCount=len(document))
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
