"""直接插图表：独立 openpyxl/lxml/ZIP 回读；不调用被测文件引擎。"""
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
    for row in [('Year', 'Amount', 'Cost'), (2023, 10, 5), (2024, 20, 8), (2025, 30, 12)]:
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

kinds = ['column', 'bar', 'line', 'area', 'pie', 'scatter', 'radar', 'doughnut', 'combo']
ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
with ZipFile(directory / 'source.xlsx') as before, ZipFile(directory / 'direct-charts.xlsx') as after:
    assert before.read('xl/charts/chart1.xml') == after.read('xl/charts/chart1.xml')
    old_drawing = etree.fromstring(before.read('xl/drawings/drawing1.xml'))
    drawing = etree.fromstring(after.read('xl/drawings/drawing1.xml'))
    assert etree.tostring(old_drawing[0], method='c14n') == etree.tostring(drawing[0], method='c14n')
    for number, kind in enumerate(kinds, start=2):
        chart = etree.fromstring(after.read(f'xl/charts/chart{number}.xml'))
        tags = [etree.QName(node).localname for node in chart.xpath('.//c:plotArea/*', namespaces=ns)]
        expected = {'column': 'barChart', 'bar': 'barChart', 'line': 'lineChart', 'area': 'areaChart', 'pie': 'pieChart', 'scatter': 'scatterChart', 'radar': 'radarChart', 'doughnut': 'doughnutChart', 'combo': 'barChart'}[kind]
        assert expected in tags, (kind, tags)
        if kind == 'combo':
            assert 'lineChart' in tags
        if kind in ('column', 'bar'):
            assert chart.xpath('string(.//c:barDir/@val)', namespaces=ns) == ('col' if kind == 'column' else 'bar')
        series = chart.xpath('.//c:plotArea/*/c:ser', namespaces=ns)
        assert len(series) == 2, (kind, len(series))
        for item, column, values in zip(series, ['B', 'C'], [['10', '20', '30'], ['5', '8', '12']], strict=True):
            category, value = ('xVal', 'yVal') if kind == 'scatter' else ('cat', 'val')
            assert item.xpath(f'string(c:{category}/*/c:f)', namespaces=ns) == "'Sheet'!$A$2:$A$4", kind
            assert item.xpath(f'c:{category}/*/*/c:pt/c:v/text()', namespaces=ns) == ['2023', '2024', '2025'], kind
            assert item.xpath(f'string(c:{value}/c:numRef/c:f)', namespaces=ns) == f"'Sheet'!${column}$2:${column}$4", kind
            assert item.xpath(f'c:{value}/c:numRef/c:numCache/c:pt/c:v/text()', namespaces=ns) == values, kind
    allowed = {'[Content_Types].xml', 'xl/worksheets/sheet1.xml', 'xl/worksheets/_rels/sheet1.xml.rels', 'xl/drawings/drawing1.xml', 'xl/drawings/_rels/drawing1.xml.rels', 'xl/styles.xml'}
    preserved = []
    for path in before.namelist():
        if path not in allowed and not path.endswith('/'):
            assert before.read(path) == after.read(path), path
            preserved.append(path)
    new_files = {path for path in after.namelist() if not path.endswith('/')} - {path for path in before.namelist() if not path.endswith('/')}
    assert new_files == {f'xl/charts/chart{number}.xml' for number in range(2, 11)}, new_files
workbook = load_workbook(directory / 'direct-charts.xlsx')
sheet = workbook.active
assert sheet['D20'].value == 'Manual direct chart' and sheet['D20'].font.bold is True
assert [sheet[f'A{row}'].value for row in range(2, 5)] == [2023, 2024, 2025]
assert [sheet[f'B{row}'].value for row in range(2, 5)] == [10, 20, 30]
assert [sheet[f'C{row}'].value for row in range(2, 5)] == [5, 8, 12]
assert len(sheet._charts) == 10
print(json.dumps({'ok': True, 'sha256': hashlib.sha256((directory / 'direct-charts.xlsx').read_bytes()).hexdigest(), 'charts': 10, 'insertedKinds': kinds, 'allSeriesReferencesAndCachesVerified': True, 'manualValueAndBoldPreserved': True, 'originalChartAndAnchorExact': True, 'newFiles': sorted(new_files), 'preservedParts': preserved}, ensure_ascii=False))
