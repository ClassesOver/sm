import sys
from zipfile import ZipFile
from pathlib import Path
from xml.etree import ElementTree

from openpyxl import Workbook
from openpyxl.chart import ScatterChart, Series, Reference
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor


output = Path(sys.argv[1])
workbook = Workbook()
sheet = workbook.active
sheet.title = 'Scatter'
sheet.append(['X', 'Y'])
for x, y in [(-20, -20), (0, 0), (20, 20)]:
    sheet.append([x, y])


def add_chart(title, anchor, hidden=False):
    chart = ScatterChart()
    chart.title = title
    chart.x_axis.scaling.min = -10
    chart.x_axis.scaling.max = 10
    chart.x_axis.majorUnit = 10
    chart.x_axis.scaling.orientation = 'maxMin'
    chart.y_axis.scaling.min = -10
    chart.y_axis.scaling.max = 10
    chart.y_axis.majorUnit = 10
    chart.y_axis.scaling.orientation = 'maxMin'
    chart.x_axis.delete = hidden
    chart.y_axis.delete = hidden
    chart.legend = None
    series = Series(Reference(sheet, min_col=2, min_row=2, max_row=4),
                    xvalues=Reference(sheet, min_col=1, min_row=2, max_row=4),
                    title='XY')
    chart.series.append(series)
    chart.anchor = TwoCellAnchor(_from=AnchorMarker(col=anchor[0], row=1),
                                 to=AnchorMarker(col=anchor[1], row=15))
    sheet.add_chart(chart)


add_chart('Scatter visible axes', (1, 9))
add_chart('Scatter hidden axes', (10, 18), hidden=True)
workbook.save(output)

namespace = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
with ZipFile(output) as package:
    chart_paths = sorted(name for name in package.namelist()
                         if name.startswith('xl/charts/chart') and name.endswith('.xml'))
    assert len(chart_paths) == 2
    for index, chart_path in enumerate(chart_paths):
        chart = ElementTree.fromstring(package.read(chart_path))
        axes = chart.findall('.//c:valAx', namespace)
        assert len(axes) == 2
        for axis in axes:
            scaling = axis.find('c:scaling', namespace)
            assert scaling.find('c:min', namespace).get('val') == '-10'
            assert scaling.find('c:max', namespace).get('val') == '10'
            assert scaling.find('c:orientation', namespace).get('val') == 'maxMin'
            assert axis.find('c:delete', namespace).get('val') == ('1' if index else '0')
        series = chart.findall('.//c:ser', namespace)
        assert len(series) == 1
        assert series[0].findtext('c:xVal/c:numRef/c:f', namespaces=namespace).endswith('$A$2:$A$4')
        assert series[0].findtext('c:yVal/c:numRef/c:f', namespaces=namespace).endswith('$B$2:$B$4')
