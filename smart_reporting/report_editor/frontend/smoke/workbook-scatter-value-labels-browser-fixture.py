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
sheet.title = 'Scatter labels'
sheet.append(['Percent X', 'Percent Y', 'Decimal X', 'Decimal Y'])
for percent_x, percent_y, decimal_x, decimal_y in [
    (0, 0, 0, 0),
    (1, 0.25, 1, 1.25),
    (2, None, 2, None),
    (3, 0.5, 3, 2.5),
]:
    sheet.append([percent_x, percent_y, decimal_x, decimal_y])

charts = [
    ('Scatter value labels', 1, 2, 1, '0%', True),
    ('Scatter no labels', 3, 4, 10, '0.00', False),
]
for title, x_column, y_column, anchor_column, _number_format, _show_labels in charts:
    chart = ScatterChart()
    chart.title = title
    chart.scatterStyle = 'lineMarker'
    chart.legend = None
    chart.x_axis.scaling.min = 0
    chart.x_axis.scaling.max = 3
    chart.x_axis.majorUnit = 1
    chart.y_axis.scaling.min = 0
    chart.y_axis.scaling.max = 3
    chart.y_axis.majorUnit = 1
    chart.series.append(Series(
        Reference(sheet, min_col=y_column, min_row=2, max_row=5),
        xvalues=Reference(sheet, min_col=x_column, min_row=2, max_row=5),
        title=title,
    ))
    chart.anchor = TwoCellAnchor(
        _from=AnchorMarker(col=anchor_column, row=1),
        to=AnchorMarker(col=anchor_column + 9, row=16),
    )
    sheet.add_chart(chart)

workbook.save(output)

chart_ns = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
drawing_ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
ElementTree.register_namespace('c', chart_ns)
ElementTree.register_namespace('a', drawing_ns)
with ZipFile(output, 'r') as source:
    parts = {name: source.read(name) for name in source.namelist()}

for index, (_, _, _, _, number_format, show_labels) in enumerate(charts, 1):
    name = f'xl/charts/chart{index}.xml'
    root = ElementTree.fromstring(parts[name])
    scatter = root.find(f'.//{{{chart_ns}}}scatterChart')
    assert scatter is not None
    series = scatter.find(f'{{{chart_ns}}}ser')
    assert series is not None
    value_ref = series.find(f'{{{chart_ns}}}yVal/{{{chart_ns}}}numRef')
    assert value_ref is not None
    value_cache = value_ref.find(f'{{{chart_ns}}}numCache')
    if value_cache is None:
        value_cache = ElementTree.SubElement(value_ref, f'{{{chart_ns}}}numCache')
    format_code = value_cache.find(f'{{{chart_ns}}}formatCode')
    if format_code is None:
        format_code = ElementTree.Element(f'{{{chart_ns}}}formatCode')
        value_cache.insert(0, format_code)
    format_code.text = number_format
    point_count = value_cache.find(f'{{{chart_ns}}}ptCount')
    if point_count is None:
        point_count = ElementTree.SubElement(value_cache, f'{{{chart_ns}}}ptCount')
    point_count.set('val', '4')
    for point in list(value_cache.findall(f'{{{chart_ns}}}pt')):
        value_cache.remove(point)
    values = [0, 0.25, None, 0.5] if index == 1 else [0, 1.25, None, 2.5]
    for point_index, value in enumerate(values):
        if value is None:
            continue
        point = ElementTree.SubElement(value_cache, f'{{{chart_ns}}}pt', {'idx': str(point_index)})
        ElementTree.SubElement(point, f'{{{chart_ns}}}v').text = str(value)

    marker = series.find(f'{{{chart_ns}}}marker')
    if marker is None:
        marker = ElementTree.Element(f'{{{chart_ns}}}marker')
        series.insert(list(series).index(series.find(f'{{{chart_ns}}}xVal')), marker)
    symbol = marker.find(f'{{{chart_ns}}}symbol')
    if symbol is None:
        symbol = ElementTree.SubElement(marker, f'{{{chart_ns}}}symbol')
    symbol.set('val', 'none')

    shape = series.find(f'{{{chart_ns}}}spPr')
    if shape is None:
        shape = ElementTree.Element(f'{{{chart_ns}}}spPr')
        series.insert(list(series).index(marker), shape)
    line = shape.find(f'{{{drawing_ns}}}ln')
    if line is None:
        line = ElementTree.SubElement(shape, f'{{{drawing_ns}}}ln')
    solid = line.find(f'{{{drawing_ns}}}solidFill')
    if solid is None:
        solid = ElementTree.Element(f'{{{drawing_ns}}}solidFill')
        line.insert(0, solid)
    color = solid.find(f'{{{drawing_ns}}}srgbClr')
    if color is None:
        color = ElementTree.SubElement(solid, f'{{{drawing_ns}}}srgbClr')
    color.set('val', '1B7F5A')

    data_labels = ElementTree.Element(f'{{{chart_ns}}}dLbls')
    ElementTree.SubElement(data_labels, f'{{{chart_ns}}}showVal', {'val': '1' if show_labels else '0'})
    axis_id = scatter.find(f'{{{chart_ns}}}axId')
    scatter.insert(list(scatter).index(axis_id) if axis_id is not None else len(scatter), data_labels)
    parts[name] = ElementTree.tostring(root, encoding='utf-8', xml_declaration=True)

temporary = output.with_suffix('.rewritten.xlsx')
with ZipFile(temporary, 'w', ZIP_DEFLATED) as target:
    for name, data in parts.items():
        target.writestr(name, data)
temporary.replace(output)
