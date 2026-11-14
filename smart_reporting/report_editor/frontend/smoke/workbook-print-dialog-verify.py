"""PrintDialog 真实夹具与独立 openpyxl/lxml/ZIP、PDF 回读。"""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.pagebreak import Break


directory = Path(sys.argv[1])
if '--fixture' in sys.argv:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Print'
    sheet.append(['Item', 'Amount', 'Count', 'Note'])
    for row in range(2, 81):
        sheet.append([f'Print row {row}', row * 10, row, f'Keep {row}'])
    sheet['F1'] = '=SUM(B2:B80)'
    for column in 'ABCD':
        sheet.column_dimensions[column].width = 16
    for row in range(1, 81):
        sheet.row_dimensions[row].height = 18
    sheet.print_area = 'A1:D80'
    sheet.print_title_rows = '1:1'
    sheet.row_breaks.append(Break(id=30))
    sheet.row_breaks.append(Break(id=60))
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = '9'
    sheet.page_setup.scale = 85
    sheet.page_setup.fitToWidth = 2
    sheet.page_setup.fitToHeight = 3
    sheet.page_setup.copies = 2
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    for key, value in dict(left=.31, right=.42, top=.53, bottom=.64, header=.17, footer=.18).items():
        setattr(sheet.page_margins, key, value)
    sheet.oddHeader.center.text = 'Original &P/&N'
    sheet.firstHeader.center.text = 'Keep first &P/&N'
    sheet.evenHeader.center.text = 'Keep even &P/&N'
    sheet.HeaderFooter.differentFirst = True
    sheet.HeaderFooter.differentOddEven = True
    workbook.create_sheet('Other')['A1'] = 'Other printable'
    workbook['Other'].page_setup.orientation = 'portrait'
    workbook['Other'].page_setup.paperSize = '1'
    hidden = workbook.create_sheet('Hidden')
    hidden['A1'] = 'Never print hidden sheet'
    hidden.sheet_state = 'hidden'
    workbook.save(directory / 'fixture.xlsx')
    print(json.dumps({'sourceSha256': hashlib.sha256((directory / 'fixture.xlsx').read_bytes()).hexdigest()}))
    sys.exit(0)

before = load_workbook(directory / 'source.xlsx')
after = load_workbook(directory / 'printed.xlsx')
old, sheet = before['Print'], after['Print']
assert sheet['D95'].value == 'Manual print draft' and sheet['D95'].font.bold is True
assert sheet['F1'].value == old['F1'].value == '=SUM(B2:B80)'
assert sheet.page_setup.orientation == 'landscape'
assert str(sheet.page_setup.paperSize) == '13'
assert sheet.page_setup.scale == 70
assert not sheet.sheet_properties.pageSetUpPr.fitToPage
assert [sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight] == [2, 3]
assert sheet.page_setup.copies == 2, 'Copies remain a desktop/system print setting'
assert [sheet.page_margins.left, sheet.page_margins.right, sheet.page_margins.top, sheet.page_margins.bottom, sheet.page_margins.header, sheet.page_margins.footer] == [.25, .25, .75, .75, .3, .3]
assert sheet.print_options.gridLines is True and sheet.print_options.headings is True
assert sheet.oddHeader.center.text == 'Updated &P/&N'
assert sheet.firstHeader.center.text == old.firstHeader.center.text
assert sheet.evenHeader.center.text == old.evenHeader.center.text
assert sheet.HeaderFooter.differentFirst and sheet.HeaderFooter.differentOddEven
assert str(sheet.print_area) == str(old.print_area) and sheet.print_title_rows == old.print_title_rows
assert [b.id for b in sheet.row_breaks.brk] == [30, 60]
for row in range(1, 81):
    for column in range(1, 5):
        assert sheet.cell(row, column).value == old.cell(row, column).value
assert after['Hidden'].sheet_state == 'hidden'
assert after['Other'].page_setup.orientation == 'portrait' and str(after['Other'].page_setup.paperSize) == '1'
preserved = []
with ZipFile(directory / 'source.xlsx') as source, ZipFile(directory / 'printed.xlsx') as saved:
    assert set(source.namelist()) == set(saved.namelist())
    for path in source.namelist():
        if path not in {'xl/worksheets/sheet1.xml', 'xl/styles.xml'}:
            assert source.read(path) == saved.read(path), path
            preserved.append(path)
    xml = etree.fromstring(saved.read('xl/worksheets/sheet1.xml'))
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    assert xml.xpath('string(m:pageSetup/@scale)', namespaces=ns) == '70'
    assert xml.xpath('string(m:printOptions/@gridLines)', namespaces=ns) in ('1', 'true')
    assert xml.xpath('string(m:printOptions/@headings)', namespaces=ns) in ('1', 'true')
from pypdf import PdfReader
pdf = PdfReader(directory / 'selected-pages.pdf')
assert len(pdf.pages) == 2
for page in pdf.pages:
    assert abs(float(page.mediabox.width) - 10.12 * 72) < 1
    assert abs(float(page.mediabox.height) - 7.17 * 72) < 1
text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
assert 'Print row' in text and 'Never print hidden sheet' not in text
print(json.dumps({'ok': True, 'sha256': hashlib.sha256((directory / 'printed.xlsx').read_bytes()).hexdigest(),
    'manualDraftPreserved': True, 'settingsReadBack': True, 'firstEvenHeaderAndFitCountsPreserved': True,
    'preservedParts': preserved, 'pdfPages': len(pdf.pages), 'pdfPageSizes': [[float(page.mediabox.width), float(page.mediabox.height)] for page in pdf.pages],
    'pdfTextExcerpt': text[:600]}, ensure_ascii=False))
