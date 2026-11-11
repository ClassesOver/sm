"""Independent currency precision and optional actual host display checks."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from runpy import run_path
import openpyxl
import pymupdf

decimal_verify = run_path(str(Path(__file__).with_name('pdf-xlsx-decimal-font-verify.py')))['verify']
VALUES = [('B8', '$12345.678', 12345.678, '"$"#,##0.000', '$12,345.678'),
          ('B9', '€31.1', 31.1, '"€"#,##0.0', '€31.1'),
          ('B10', '-£0.0500', -.05, '"£"#,##0.0000', '-£0.0500'),
          ('B11', '12.345%', .12345, '0.000%', '12.345%'),
          ('B12', '0.0007%', .000007, '0.0000%', '0.0007%')]

def verify(source: Path, xlsx: Path, rendered: Path | None = None):
    result = decimal_verify(source, xlsx, rendered)
    text = pymupdf.open(source)[1].get_text()
    sheet = openpyxl.load_workbook(xlsx, rich_text=True)['Page 2']
    cells = []
    for address, label, value, number_format, display in VALUES:
        assert label in text, label
        assert sheet[address].data_type == 'n' and sheet[address].value == value, address
        assert sheet[address].number_format == number_format, (address, sheet[address].number_format)
        cells.append({'address': address, 'value': value, 'numberFormat': number_format, 'display': display})
    assert sheet.column_dimensions['B'].width > 0
    result.update(currencyAndPercentPrecision=True, formattedColumnWidth=sheet.column_dimensions['B'].width, currencyAndPercentCells=cells)
    if rendered is not None:
        document = pymupdf.open(rendered)
        text = '\n'.join(page.get_text() for page in document)
        assert '###' not in text
        for _, _, _, _, display in VALUES:
            assert display in text, ('actual Calc display', display)
        result['hostCalcCurrencyAndPercentPrecision'] = True
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
