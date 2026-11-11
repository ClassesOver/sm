"""Independent source precision, native rich fonts and optional Calc display checks."""
from __future__ import annotations
import argparse
from io import BytesIO
import json
from pathlib import Path
import re
from runpy import run_path
from fontTools.ttLib import TTFont
import openpyxl
import pymupdf

rich_verify = run_path(str(Path(__file__).with_name('pdf-xlsx-rich-text-verify.py')))['verify']
DECIMALS = [('A3', '12345.67', 12345.67, '0.00'), ('A4', '12345.6789', 12345.6789, '0.0000'), ('A5', '-31.10', -31.1, '0.00'), ('A6', '12,345.678', 12345.678, '#,##0.000')]

def verify(source: Path, xlsx: Path, rendered: Path | None = None):
    result = rich_verify(source, xlsx, rendered)
    text = pymupdf.open(source)[1].get_text()
    for _, label, _, _ in DECIMALS:
        assert label in text, label
    sheet = openpyxl.load_workbook(xlsx, rich_text=True)['Page 2']
    assert sheet['A2'].value[0].font.rFont == 'Liberation Sans', 'Helvetica-BoldOblique must resolve to a known installed substitute'
    for address, _, value, number_format in DECIMALS:
        assert sheet[address].data_type == 'n' and sheet[address].value == value
        assert sheet[address].number_format == number_format, (address, sheet[address].number_format)
    assert sheet['A7'].value == 1250 and sheet['A7'].number_format == 'General'
    assert sheet.column_dimensions['A'].width > 0
    result.update(authoredDecimalPrecision=True, exponentPolicyUnchanged=True, decimalColumnWidth=sheet.column_dimensions['A'].width)
    if rendered is not None:
        document = pymupdf.open(rendered)
        text = '\n'.join(page.get_text() for page in document)
        assert '###' not in text
        for _, label, _, _ in DECIMALS:
            assert label in text, ('Calc must display every authored decimal', label)
        expected = 'LiberationSans-BoldItalic'
        page = next(page for page in document if 'Dominant decorated words plain' in page.get_text())
        fonts = [font for font in page.get_fonts(full=True) if re.sub(r'^[A-Z]{6}\+', '', font[3]) == expected]
        assert len(fonts) == 1, fonts
        xref, _, _, base_font, *_ = fonts[0]
        embedded = TTFont(BytesIO(document.extract_font(xref)[3]))
        names = {name.toUnicode() for name in embedded['name'].names if name.nameID == 6}
        assert names == {expected}, names
        # MuPDF's span name can truncate the subset-prefixed BaseFont to 31
        # characters. Verify the exact PDF and embedded names before accepting
        # that precise representation; never accept an arbitrary font prefix.
        allowed = {expected, re.sub(r'^[A-Z]{6}\+', '', base_font[:31])}
        assert result['dominantRenderedFamily'] in allowed, result['dominantRenderedFamily']
        result.update(hostCalcDecimalPrecision=True, hostCalcKnownBoldItalic=True,
                      dominantPdfBaseFont=base_font, dominantEmbeddedPostScriptName=expected)
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
