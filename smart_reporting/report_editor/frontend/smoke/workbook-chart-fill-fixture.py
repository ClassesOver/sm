"""来源主题/稀疏逐点填充与最终画布像素的独立验收，不调用产品颜色算法。"""
import colorsys
import json
import sys
from io import BytesIO
from pathlib import Path
from runpy import run_path
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, DoughnutChart, PieChart, Reference
from openpyxl.chart.marker import DataPoint
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.colors import ColorChoice, SchemeColor
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.utils import get_column_letter
from PIL import Image

COLORS = ('#136B4A', '#A02040', '#2F5597')
THEME_COLORS = ('#136B4A', '#A02040', '#4472C4')


def create(path):
    book = Workbook()
    sheet = book.active
    for row in [['Quarter', 'Revenue'], ['Q1', 3], ['Q2', None], ['Q3', 6]]:
        sheet.append(row)
    for column in range(1, 21):
        sheet.column_dimensions[get_column_letter(column)].width = 12
    for row in range(1, 60):
        sheet.row_dimensions[row].height = 18
    for index, kind in enumerate(('column', 'bar', 'pie', 'doughnut', 'complex', 'shaded')):
        chart = PieChart() if kind == 'pie' else DoughnutChart() if kind == 'doughnut' else BarChart()
        if kind == 'bar':
            chart.type = 'bar'
        chart.title, chart.legend, chart.varyColors = f'Fill {kind}', None, False
        chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=4), titles_from_data=True)
        chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=4))
        series = chart.series[0]
        if kind in ('column', 'pie'):
            series.spPr = GraphicalProperties(solidFill=ColorChoice(schemeClr=SchemeColor(val='accent1')))
        if kind == 'complex':
            series.spPr = GraphicalProperties(solidFill=ColorChoice(schemeClr=SchemeColor(val='accent1', lumMod=75000)))
        elif kind == 'shaded':
            series.spPr = GraphicalProperties(solidFill=ColorChoice(schemeClr=SchemeColor(val='accent3', lumMod=75000)))
        else:
            series.data_points = [DataPoint(idx=2, spPr=GraphicalProperties(solidFill=ColorChoice(schemeClr=SchemeColor(val='accent2'))))]
        if kind == 'bar':
            series.data_points.append(DataPoint(idx=0, spPr=GraphicalProperties(noFill=True)))
        row = 1 + index * 9
        chart.anchor = TwoCellAnchor(_from=AnchorMarker(col=4, row=row), to=AnchorMarker(col=13, row=row + 7))
        sheet.add_chart(chart)
    stream = BytesIO()
    book.save(stream)
    target = BytesIO()
    ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with ZipFile(stream) as source, ZipFile(target, 'w') as output:
        for entry in source.infolist():
            raw = source.read(entry.filename)
            if entry.filename == 'xl/theme/theme1.xml':
                theme = etree.fromstring(raw)
                for slot, color in zip(('accent1', 'accent2', 'accent3'), THEME_COLORS):
                    node = theme.find(f'.//a:clrScheme/a:{slot}', ns)
                    node.clear()
                    etree.SubElement(node, '{' + ns['a'] + '}srgbClr', val=color[1:])
                raw = etree.tostring(theme)
            elif entry.filename == 'xl/charts/chart5.xml':
                chart = etree.fromstring(raw)
                series = chart.find('.//{http://schemas.openxmlformats.org/drawingml/2006/chart}ser')
                shape = series.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}spPr')
                shape.remove(shape.find('a:solidFill', ns))
                gradient = etree.Element('{' + ns['a'] + '}gradFill')
                shape.insert(0, gradient)
                stops = etree.SubElement(gradient, '{' + ns['a'] + '}gsLst')
                for position, color in ((0, '136B4A'), (100000, 'A02040')):
                    stop = etree.SubElement(stops, '{' + ns['a'] + '}gs', pos=str(position))
                    etree.SubElement(stop, '{' + ns['a'] + '}srgbClr', val=color)
                etree.SubElement(gradient, '{' + ns['a'] + '}lin', ang='0', scaled='1')
                raw = etree.tostring(chart)
            output.writestr(entry, raw)
    path.write_bytes(target.getvalue())


def verify(directory):
    book = load_workbook(directory / 'source.xlsx')
    assert [book.active[f'B{row}'].value for row in (2, 3, 4)] == [3, None, 6]
    ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main', 'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
    with ZipFile(directory / 'source.xlsx') as source:
        theme = etree.fromstring(source.read('xl/theme/theme1.xml'))
        for slot, color in zip(('accent1', 'accent2', 'accent3'), THEME_COLORS):
            assert theme.xpath(f'//a:clrScheme/a:{slot}/a:srgbClr/@val', namespaces=ns) == [color[1:]]
        for index in range(1, 5):
            chart = etree.fromstring(source.read(f'xl/charts/chart{index}.xml'))
            assert chart.xpath('//c:ser/c:dPt[c:idx/@val="2"]/c:spPr/a:solidFill/a:schemeClr/@val', namespaces=ns) == ['accent2']
            assert chart.xpath('//c:ser/c:val/c:numRef/c:f/text()', namespaces=ns) == ["'Sheet'!$B$2:$B$4"]
            if index == 2:
                assert len(chart.xpath('//c:ser/c:dPt[c:idx/@val="0"]/c:spPr/a:noFill', namespaces=ns)) == 1
            if index == 4:
                assert chart.xpath('//c:doughnutChart/c:varyColors/@val', namespaces=ns) == ['0']
                assert chart.xpath('//c:ser/c:spPr/a:solidFill', namespaces=ns) == []
        complex_chart = etree.fromstring(source.read('xl/charts/chart5.xml'))
        assert len(complex_chart.xpath('//c:ser/c:spPr/a:gradFill/a:gsLst/a:gs', namespaces=ns)) == 2
        shaded = etree.fromstring(source.read('xl/charts/chart6.xml'))
        assert shaded.xpath('//c:ser/c:spPr/a:solidFill/a:schemeClr/a:lumMod/@val', namespaces=ns) == ['75000']
        rgb = [int(THEME_COLORS[2][offset:offset + 2], 16) / 255 for offset in (1, 3, 5)]
        h, lightness, saturation = colorsys.rgb_to_hls(*rgb)
        transformed = '#' + ''.join(f'{round(channel * 255):02X}' for channel in colorsys.hls_to_rgb(h, lightness * .75, saturation))
        assert transformed == COLORS[2], transformed
    image = Image.open(directory / 'charts.png').convert('RGB')
    evidence = run_path(str(Path(__file__).with_name('canvas_chart_pixels.py')))['chart_pixels'](image, COLORS)
    assert len(evidence['frames']) == 6, evidence['frames']
    actual = []
    for index, frame in enumerate(evidence['frames']):
        components = [part for part in evidence['bars'] if frame['x'] < part['x'] < frame['x'] + frame['width']
                      and frame['y'] < part['y'] < frame['y'] + frame['height']]
        colors = sorted(part['color'] for part in components)
        expected = [] if index == 4 else [COLORS[2], COLORS[2]] if index == 5 else [COLORS[1]] if index == 1 else sorted(COLORS[:2])
        assert colors == expected, (index, colors, expected)
        actual.append({'kind': ('column', 'bar', 'pie', 'doughnut', 'complex', 'shaded')[index], 'colors': colors})
    return {'ok': True, 'sourceOOXMLIndependentlyRead': True, 'missingPointPreserved': True,
            'complexFillHasNoInventedBars': True, 'charts': actual, 'pixels': evidence}


if __name__ == '__main__':
    if sys.argv[1] == 'create':
        create(Path(sys.argv[2]))
    else:
        print(json.dumps(verify(Path(sys.argv[2])), ensure_ascii=False))
