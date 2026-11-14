"""推荐图表浏览器夹具与独立 openpyxl/lxml/ZIP 回读，不调用被测引擎。"""
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
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Sheet'
    for row in [('Year', 'Amount'), (2023, 10), (2024, 20), (2025, 30)]:
        sheet.append(row)
    chart = BarChart()
    chart.title = 'Keep original'
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=4), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=4))
    chart.anchor = TwoCellAnchor(_from=AnchorMarker(col=10, row=8), to=AnchorMarker(col=18, row=23))
    sheet.add_chart(chart)
    workbook.save(directory / 'fixture.xlsx')
    print(json.dumps({'sourceSha256': hashlib.sha256((directory / 'fixture.xlsx').read_bytes()).hexdigest()}))
    sys.exit(0)

ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
      'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'}
with ZipFile(directory / 'source.xlsx') as before, ZipFile(directory / 'recommended.xlsx') as after:
    assert before.read('xl/charts/chart1.xml') == after.read('xl/charts/chart1.xml')
    old_drawing = etree.fromstring(before.read('xl/drawings/drawing1.xml'))
    drawing = etree.fromstring(after.read('xl/drawings/drawing1.xml'))
    assert etree.tostring(old_drawing[0], method='c14n') == etree.tostring(drawing[0], method='c14n')
    new_chart = etree.fromstring(after.read('xl/charts/chart2.xml'))
    series = new_chart.xpath('.//c:lineChart/c:ser', namespaces=ns)
    assert len(series) == 1, 'Numeric year vector must be categories, not a plotted series'
    assert series[0].xpath('string(c:val/c:numRef/c:f)', namespaces=ns) == "'Sheet'!$B$2:$B$4"
    assert series[0].xpath('string(c:cat/*/c:f)', namespaces=ns) == "'Sheet'!$A$2:$A$4"
    assert series[0].xpath('c:cat/*/*/c:pt/c:v/text()', namespaces=ns) == ['2023', '2024', '2025']
    assert series[0].xpath('c:val/c:numRef/c:numCache/c:pt/c:v/text()', namespaces=ns) == ['10', '20', '30']
    allowed = {'[Content_Types].xml', 'xl/worksheets/sheet1.xml', 'xl/worksheets/_rels/sheet1.xml.rels',
               'xl/drawings/drawing1.xml', 'xl/drawings/_rels/drawing1.xml.rels', 'xl/styles.xml'}
    preserved = []
    for path in before.namelist():
        if path not in allowed:
            assert before.read(path) == after.read(path), path
            preserved.append(path)
    assert set(after.namelist()) - set(before.namelist()) == {'xl/charts/chart2.xml'}
workbook = load_workbook(directory / 'recommended.xlsx')
sheet = workbook.active
assert sheet['D20'].value == 'Manual recommendation' and sheet['D20'].font.bold is True
assert [sheet[f'A{row}'].value for row in range(2, 5)] == [2023, 2024, 2025]
assert [sheet[f'B{row}'].value for row in range(2, 5)] == [10, 20, 30]
assert len(sheet._charts) == 2
assert sheet._charts[1].__class__.__name__ == 'LineChart'
assert sheet._charts[1].anchor._from.col == 3 and sheet._charts[1].anchor._from.row == 0
print(json.dumps({'ok': True, 'sha256': hashlib.sha256((directory / 'recommended.xlsx').read_bytes()).hexdigest(),
    'charts': 2, 'recommendedKind': 'line', 'numericYearsAsCategories': True, 'manualDraftPreserved': True,
    'originalChartAndAnchorExact': True, 'preservedParts': preserved}, ensure_ascii=False))
