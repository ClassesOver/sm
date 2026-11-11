"""Independent slot claims/content comparison and optional physical host border measurement."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from runpy import run_path
from zipfile import ZipFile
import openpyxl
import pymupdf

currency_verify = run_path(str(Path(__file__).with_name('pdf-xlsx-currency-precision-verify.py')))['verify']

def host_table_measurements(path: Path):
    document = pymupdf.open(path)
    parts = []
    first_column = None
    for page in document:
        words = page.get_text('words')
        outer_headers = [word for word in words if word[4] in {'Region', 'Margin'}]
        if not outer_headers:
            continue
        header_top = min(word[1] for word in outer_headers)
        lines = [item for drawing in page.get_drawings() for item in drawing['items']
                 if item[0] == 'l' and abs(item[1].y - item[2].y) < .01 and item[1].y < header_top]
        assert lines, ('table border not readable', page.number + 1)
        top = max(line[1].y for line in lines)
        intervals = sorted((max(page.rect.x0, min(line[1].x, line[2].x)),
                            min(page.rect.x1, max(line[1].x, line[2].x)))
                           for line in lines if abs(line[1].y - top) < .01)
        merged = []
        for left, right in intervals:
            if right <= left:
                continue
            if merged and left <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], right)
            else:
                merged.append([left, right])
        parts.append({'page': page.number + 1, 'topBorderY': top, 'intervals': merged,
                      'visibleWidthPoints': sum(right - left for left, right in merged)})
        region = next((word for word in outer_headers if word[4] == 'Region'), None)
        revenue = next((word for word in words if word[4] == 'Revenue' and region and abs(word[1] - region[1]) < 1), None)
        if region and revenue:
            # Both headers have the same writer inset/font; their actual
            # baseline x-origin difference measures the complete first column.
            first_column = revenue[0] - region[0]
    assert parts and first_column is not None, 'known fixture table headers must be readable'
    return {'pageCount': len(document), 'tableParts': parts,
            'visibleTopBorderWidthPoints': sum(part['visibleWidthPoints'] for part in parts),
            'completeFirstColumnPoints': first_column}

def builder_width(sheet):
    return sum((max(1, round(column.width * 7 + 5)) if column else 64) * .75
               for column in (sheet.column_dimensions.get(openpyxl.utils.get_column_letter(index))
                              for index in range(1, sheet.max_column + 1)))

def verify(source: Path, xlsx: Path, rendered: Path | None = None, baseline: Path | None = None):
    result = currency_verify(source, xlsx, rendered)
    sheet = openpyxl.load_workbook(xlsx, rich_text=True)['Page 1']
    assert all(sheet.column_dimensions.get(column) is not None for column in 'ABCDEF')
    assert sheet.column_dimensions['A'].width == 2, 'known tiny source interval retains the old clamp'
    assert sheet.column_dimensions['A'].width < sheet.column_dimensions['B'].width
    assert sheet.column_dimensions['C'].width < sheet.column_dimensions['F'].width
    result.update(tableSlotClaimsComplete=True, builderConventionWidthPoints=builder_width(sheet),
                  minimumColumnClampRetained=True, defaultFontMdwFidelityPassed=False,
                  printLayoutFidelityPassed=False)
    if baseline is not None:
        assert hashlib.sha256((baseline / 'source.pdf').read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest(), 'same-source comparison required'
        with ZipFile(baseline / 'converted.xlsx') as before, ZipFile(xlsx) as after:
            sheets = sorted(name for name in before.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', name))
            assert sheets == sorted(name for name in after.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', name))
            for name in sheets:
                assert re.sub(rb'<cols>.*?</cols>', b'', before.read(name), flags=re.S) == re.sub(rb'<cols>.*?</cols>', b'', after.read(name), flags=re.S), ('only column widths may change in worksheet XML', name)
            assert before.read('xl/styles.xml') == after.read('xl/styles.xml'), 'all cell styles retained'
            images = sorted(name for name in before.namelist() if name.startswith('xl/media/') and not name.endswith('/'))
            assert images == sorted(name for name in after.namelist() if name.startswith('xl/media/') and not name.endswith('/'))
            assert all(before.read(name) == after.read(name) for name in images), 'actual image bytes retained'
        old = openpyxl.load_workbook(baseline / 'converted.xlsx', rich_text=True)['Page 1']
        assert builder_width(sheet) < builder_width(old)
        result.update(sameSourceWorksheetContentAndMergesRetained=True, sameSourceStylesAndImageBytesRetained=True,
                      baselineBuilderConventionWidthPoints=builder_width(old))
    if rendered is not None:
        current = host_table_measurements(rendered)
        result['hostTableMeasurements'] = current
        if baseline is not None and (baseline / 'rendered.pdf').is_file():
            previous = host_table_measurements(baseline / 'rendered.pdf')
            result['baselineHostTableMeasurements'] = previous
            assert current['visibleTopBorderWidthPoints'] < previous['visibleTopBorderWidthPoints'], 'actual host table width must improve; source physical-point fidelity remains unclaimed'
            result['hostRelativeTableWidthImproved'] = True
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('xlsx', type=Path)
    parser.add_argument('rendered_pdf', type=Path, nargs='?')
    parser.add_argument('--baseline-directory', type=Path, default=os.environ.get('PDF_XLSX_TABLE_SLOT_BASELINE_DIRECTORY'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.source, args.xlsx, args.rendered_pdf, args.baseline_directory)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + '\n')
    print(text)
