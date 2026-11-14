"""Select Data 独立 openpyxl/lxml/ZIP 回读；不调用被测引擎。"""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

directory = Path(sys.argv[1])
if '--fixture' in sys.argv:
    book = Workbook()
    sheet = book.active
    sheet.title = 'Data'
    for row in [('Quarter', 'North', 'South', 'Added'), ('Q1', 10, 20, 11), ('Q2', 30, 40, 12)]:
        sheet.append(row)
    chart = BarChart()
    chart.title = 'Keep source chart'
    chart.add_data(Reference(sheet, min_col=2, max_col=3, min_row=1, max_row=3), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=3))
    chart.series[0].graphicalProperties.solidFill = '123456'
    chart.anchor = TwoCellAnchor(_from=AnchorMarker(col=5, row=5), to=AnchorMarker(col=13, row=20))
    sheet.add_chart(chart)
    other = book.create_sheet("O'Brien Data")
    other.append(['A', 5])
    other.append(['B', 8])
    book.save(directory / 'fixture.xlsx')
    print(json.dumps({'sourceSha256': hashlib.sha256((directory / 'fixture.xlsx').read_bytes()).hexdigest()}))
    sys.exit(0)

before = load_workbook(directory / 'source.xlsx')
after = load_workbook(directory / 'selected-data.xlsx')
assert after['Data']['J2'].value == 'Manual select draft' and after['Data']['J2'].font.bold is True
for row in range(1, 4):
    for column in range(1, 5):
        assert before['Data'].cell(row, column).value == after['Data'].cell(row, column).value
assert len(after['Data']._charts) == 1
ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
preserved = []
with ZipFile(directory / 'source.xlsx') as source, ZipFile(directory / 'selected-data.xlsx') as saved:
    assert set(source.namelist()) == set(saved.namelist())
    xml = etree.fromstring(saved.read('xl/charts/chart1.xml'))
    old = etree.fromstring(source.read('xl/charts/chart1.xml'))
    series = xml.xpath('.//c:barChart/c:ser', namespaces=ns)
    assert len(series) == 2
    for index, entry in enumerate(series):
        assert entry.xpath('string(c:tx/c:v)', namespaces=ns) == ['A', 'B'][index]
        assert entry.xpath('c:cat/c:strLit/c:pt/c:v/text()', namespaces=ns) == ['Added', 'Renamed']
        assert entry.xpath('c:val/c:numLit/c:pt/c:v/text()', namespaces=ns) == [['11', '5'], ['12', '8']][index]
        assert entry.xpath('count(.//c:f)', namespaces=ns) == 0
    assert etree.tostring(old.find('c:chart/c:title', ns), method='c14n') == etree.tostring(xml.find('c:chart/c:title', ns), method='c14n')
    for path in source.namelist():
        if path not in {'xl/charts/chart1.xml', 'xl/worksheets/sheet1.xml', 'xl/styles.xml'}:
            assert source.read(path) == saved.read(path), path
            preserved.append(path)
print(json.dumps({'ok': True, 'sha256': hashlib.sha256((directory / 'selected-data.xlsx').read_bytes()).hexdigest(),
    'manualDraftPreserved': True, 'literalTransposeReadBack': True, 'sourceTitleExact': True, 'preservedParts': preserved}, ensure_ascii=False))
