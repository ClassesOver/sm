"""组合图真实来源及独立 openpyxl/lxml/ZIP 回读；不调用被测引擎。"""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

directory = Path(sys.argv[1])
if '--fixture' in sys.argv:
    book = Workbook()
    sheet = book.active
    sheet.title = 'Data'
    for row in [('Quarter', 'North', 'South', 'Rate', 'Added'), ('Q1', 10, 20, 1000, 7), ('Q2', 30, 40, 2000, 9)]:
        sheet.append(row)
    bars, line = BarChart(), LineChart()
    bars.title = 'Keep native combo'
    bars.add_data(Reference(sheet, min_col=2, max_col=3, min_row=1, max_row=3), titles_from_data=True)
    bars.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=3))
    bars.series[0].graphicalProperties.solidFill = '123456'
    line.add_data(Reference(sheet, min_col=4, min_row=1, max_row=3), titles_from_data=True)
    line.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=3))
    line.y_axis.axId = 200
    line.y_axis.axPos = 'r'
    line.y_axis.crosses = 'max'
    bars += line
    bars.anchor = TwoCellAnchor(_from=AnchorMarker(col=5, row=5), to=AnchorMarker(col=14, row=23))
    sheet.add_chart(bars)
    book.save(directory / 'fixture.xlsx')
    print(json.dumps({'sourceSha256': hashlib.sha256((directory / 'fixture.xlsx').read_bytes()).hexdigest()}))
    sys.exit(0)

before = load_workbook(directory / 'source.xlsx')
after = load_workbook(directory / 'combo.xlsx')
assert after['Data']['J2'].value == 'Manual combo draft' and after['Data']['J2'].font.bold is True
for row in range(1, 4):
    for column in range(1, 6):
        assert before['Data'].cell(row, column).value == after['Data'].cell(row, column).value
ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
expected = [('barChart', 'Added', False, 0, [7, 9]), ('lineChart', 'North', False, 1, [10, 30]), ('barChart', 'South', True, 2, [20, 40]), ('lineChart', 'Rate', True, 3, [1000, 2000])]
preserved, inspected = [], []
with ZipFile(directory / 'source.xlsx') as source, ZipFile(directory / 'combo.xlsx') as saved:
    assert set(source.namelist()) == set(saved.namelist())
    xml, old = etree.fromstring(saved.read('xl/charts/chart1.xml')), etree.fromstring(source.read('xl/charts/chart1.xml'))
    plot = xml.find('c:chart/c:plotArea', ns)
    groups = [node for node in plot if etree.QName(node).localname in {'barChart', 'lineChart'}]
    assert len(groups) == 4
    axes = {node.find('c:axId', ns).get('val'): node for node in plot if etree.QName(node).localname in {'catAx', 'valAx'}}
    assert len(axes) == 4
    for group, (family, name, secondary, order, values) in zip(groups, expected):
        assert etree.QName(group).localname == family
        entries = group.findall('c:ser', ns)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.xpath('string(c:tx/c:v)', namespaces=ns) == name
        assert entry.find('c:idx', ns).get('val') == str(order)
        assert entry.find('c:order', ns).get('val') == str(order)
        assert [float(value) for value in entry.xpath('c:val/c:numRef/c:numCache/c:pt/c:v/text()', namespaces=ns)] == values
        assert entry.xpath('c:cat/c:strRef/c:strCache/c:pt/c:v/text()', namespaces=ns) == ['Q1', 'Q2']
        ids = [node.get('val') for node in group.findall('c:axId', ns)]
        assert len(ids) == 2 and all(key in axes for key in ids)
        value_axis = next(axes[key] for key in ids if etree.QName(axes[key]).localname == 'valAx')
        assert (value_axis.find('c:axPos', ns).get('val') == 'r') is secondary
        assert value_axis.find('c:crossAx', ns).get('val') in ids
        inspected.append({'name': name, 'plot': family, 'secondaryAxis': secondary, 'order': order, 'axisIds': ids, 'values': values})
    for axis in old.xpath('c:chart/c:plotArea/c:catAx | c:chart/c:plotArea/c:valAx[c:axPos/@val!="r"]', namespaces=ns):
        assert etree.tostring(axis, method='c14n') == etree.tostring(axes[axis.find('c:axId', ns).get('val')], method='c14n')
    assert etree.tostring(old.find('c:chart/c:title', ns), method='c14n') == etree.tostring(xml.find('c:chart/c:title', ns), method='c14n')
    for path in source.namelist():
        if path not in {'xl/charts/chart1.xml', 'xl/worksheets/sheet1.xml', 'xl/styles.xml'}:
            assert source.read(path) == saved.read(path), path
            preserved.append(path)
print(json.dumps({'ok': True, 'sha256': hashlib.sha256((directory / 'combo.xlsx').read_bytes()).hexdigest(), 'bytes': (directory / 'combo.xlsx').stat().st_size,
    'manualDraftPreserved': True, 'series': inspected, 'sourcePrimaryAxesExact': True, 'sourceTitleExact': True, 'preservedParts': preserved}, ensure_ascii=False))
