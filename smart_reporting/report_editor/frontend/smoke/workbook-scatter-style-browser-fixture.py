import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree

from openpyxl import Workbook
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor


output = Path(sys.argv[1])
workbook = Workbook()
sheet = workbook.active
sheet.title = 'Scatter style'
sheet.append(['X', 'Y'])
for point in [(1, 1), (2, 3), (3, 2), (4, 4)]:
    sheet.append(point)

styles = [
    ('Scatter marker only', 'marker', None, None, 'circle'),
    ('Scatter line color width', 'lineMarker', 'D52B2B', 4, 'circle'),
    ('Scatter explicit no line', 'lineMarker', 'none', None, 'circle'),
    ('Scatter hidden markers', 'lineMarker', '1B7F5A', None, 'none'),
]

for index, (title, style, _line_color, _line_width, _marker) in enumerate(styles):
    chart = ScatterChart()
    chart.title = title
    chart.legend = None
    chart.x_axis.scaling.min = 0
    chart.x_axis.scaling.max = 5
    chart.x_axis.majorUnit = 1
    chart.y_axis.scaling.min = 0
    chart.y_axis.scaling.max = 5
    chart.y_axis.majorUnit = 1
    chart.series.append(Series(Reference(sheet, min_col=2, min_row=2, max_row=5),
                               xvalues=Reference(sheet, min_col=1, min_row=2, max_row=5),
                               title='XY'))
    chart.anchor = TwoCellAnchor(_from=AnchorMarker(col=(1 if index % 2 == 0 else 10), row=(1 if index < 2 else 16)),
                                 to=AnchorMarker(col=(9 if index % 2 == 0 else 18), row=(14 if index < 2 else 29)))
    sheet.add_chart(chart)

workbook.save(output)

with ZipFile(output, 'r') as source:
    parts = {name: source.read(name) for name in source.namelist()}
chart_ns = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
drawing_ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
ElementTree.register_namespace('c', chart_ns)
ElementTree.register_namespace('a', drawing_ns)
for index, (_, style, line_color, line_width, marker) in enumerate(styles, 1):
    name = f'xl/charts/chart{index}.xml'
    root = ElementTree.fromstring(parts[name])
    scatter = root.find(f'.//{{{chart_ns}}}scatterChart')
    assert scatter is not None
    scatter.insert(0, ElementTree.Element(f'{{{chart_ns}}}scatterStyle', {'val': style}))
    series = scatter.find(f'{{{chart_ns}}}ser')
    assert series is not None
    for child in list(series):
        if child.tag in (f'{{{chart_ns}}}spPr', f'{{{chart_ns}}}marker'):
            series.remove(child)
    shape = ElementTree.Element(f'{{{chart_ns}}}spPr')
    line = ElementTree.SubElement(shape, f'{{{drawing_ns}}}ln',
                                  **({'w': str(line_width * 9525)} if line_width is not None else {}))
    if line_color == 'none':
        ElementTree.SubElement(line, f'{{{drawing_ns}}}noFill')
    elif line_color is not None:
        solid = ElementTree.SubElement(line, f'{{{drawing_ns}}}solidFill')
        ElementTree.SubElement(solid, f'{{{drawing_ns}}}srgbClr', {'val': line_color})
    marker_node = ElementTree.Element(f'{{{chart_ns}}}marker')
    ElementTree.SubElement(marker_node, f'{{{chart_ns}}}symbol', {'val': marker})
    series.insert(2, shape)
    series.insert(3, marker_node)
    parts[name] = ElementTree.tostring(root, encoding='utf-8', xml_declaration=True)

temporary = output.with_suffix('.rewritten.xlsx')
with ZipFile(temporary, 'w', ZIP_DEFLATED) as target:
    for name, data in parts.items():
        target.writestr(name, data)
temporary.replace(output)
