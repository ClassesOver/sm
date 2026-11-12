"""Source typography, partial overrides, physical point sizes and pixel proof."""
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from runpy import run_path
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from PIL import Image

C = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
NS = {'c': C, 'a': A}
BLUE = '#4472c4'
THEME_CASE = os.environ.get('WORKBOOK_CHART_RENDER_CASE') == 'label-theme'


def font_style(size=None, bold=None, color=None, *, theme=False, fallback=False):
    root = etree.Element(etree.QName(C, 'txPr'))
    etree.SubElement(root, etree.QName(A, 'bodyPr'))
    etree.SubElement(root, etree.QName(A, 'lstStyle'))
    paragraph = etree.SubElement(root, etree.QName(A, 'p'))
    parent = paragraph if fallback else etree.SubElement(paragraph, etree.QName(A, 'pPr'))
    properties = etree.SubElement(parent, etree.QName(A, 'endParaRPr' if fallback else 'defRPr'))
    if size is not None:
        properties.set('sz', str(round(size * 100)))
    if bold is not None:
        properties.set('b', '1' if bold else '0')
    if color or theme:
        fill = etree.SubElement(properties, etree.QName(A, 'solidFill'))
        etree.SubElement(fill, etree.QName(A, 'schemeClr' if theme else 'srgbClr'), val='phClr' if theme else color.lstrip('#'))
    return root


def styled_ai_source(source):
    """A true source style and a point override that AI must preserve."""
    target = BytesIO()
    with ZipFile(BytesIO(source)) as before, ZipFile(target, 'w') as after:
        for entry in before.infolist():
            content = before.read(entry.filename)
            if entry.filename == 'xl/charts/chart1.xml':
                xml = etree.fromstring(content)
                plot = xml.find('.//c:barChart', NS)
                assert plot.find('c:dLbls', NS) is None
                labels = etree.Element(etree.QName(C, 'dLbls'))
                point = etree.SubElement(labels, etree.QName(C, 'dLbl'))
                etree.SubElement(point, etree.QName(C, 'idx'), val='1')
                etree.SubElement(point, etree.QName(C, 'numFmt'), formatCode='0.00', sourceLinked='0')
                point.append(font_style(bold=False))
                etree.SubElement(point, etree.QName(C, 'dLblPos'), val='ctr')
                etree.SubElement(labels, etree.QName(C, 'numFmt'), formatCode='0.000', sourceLinked='0')
                labels.append(font_style(12, True, 'FFFFFF'))
                etree.SubElement(labels, etree.QName(C, 'dLblPos'), val='ctr')
                for name, value in [('showLegendKey', '0'), ('showVal', '1'), ('showCatName', '0'), ('showSerName', '0'), ('showPercent', '0'), ('showBubbleSize', '0')]:
                    etree.SubElement(labels, etree.QName(C, name), val=value)
                plot.insert(list(plot).index(plot.findall('c:ser', NS)[-1]) + 1, labels)
                content = etree.tostring(xml, xml_declaration=True, encoding='UTF-8')
            after.writestr(entry, content)
    return target.getvalue()


def create():
    from smart_reporting.report_editor.native_office import patch_office
    book = Workbook()
    for row in [['Category', 'Amount'], ['A', 10], ['B', 20]]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    additions = []
    for index, title in enumerate(('Default 11px', 'Plot 12pt bold', 'Series and point RGB', 'Unresolved theme', 'Too large 72pt', 'Fallback 9pt red')):
        row = 1 + index * 8
        additions.append({'worksheetSheetName': 'Sheet', 'anchor': {
            'fromRow': row, 'fromColumn': 4, 'fromRowOffset': 0, 'fromColumnOffset': 0,
            'toRow': row + 6, 'toColumn': 13, 'toRowOffset': 0, 'toColumnOffset': 0},
            'chart': {'chartType': 'bar', 'title': title, 'legend': 'none', 'dataLabels': 'value',
                      'dataLabelPosition': 'outside-end' if index == 5 else 'center', 'dataLabelFormat': '0.0',
                      'series': [{'name': 'Values', 'categories': ['A', 'B'], 'values': [10, 20], 'valuesRef': "'Sheet'!$B$2:$B$3"}]}})
    raw = patch_office('xlsx', stream.getvalue(), [{'kind': 'applyChartAdditions', 'additions': additions}])
    target = BytesIO()
    with ZipFile(BytesIO(raw)) as before, ZipFile(target, 'w') as after:
        for entry in before.infolist():
            content = before.read(entry.filename)
            if entry.filename.startswith('xl/charts/chart') and entry.filename.endswith('.xml'):
                index = int(Path(entry.filename).stem.removeprefix('chart')) - 1
                xml = etree.fromstring(content)
                labels = xml.find('.//c:barChart/c:dLbls', NS)
                if index:
                    style = font_style(9, True, 'A02040', fallback=True) if index == 5 else font_style(72 if index == 4 else 12, True, 'FFFFFF', theme=index == 3)
                    labels.insert(list(labels).index(labels.find('c:dLblPos', NS)), style)
                if index == 2:
                    series = xml.find('.//c:ser', NS)
                    own = etree.Element(etree.QName(C, 'dLbls'))
                    point = etree.SubElement(own, etree.QName(C, 'dLbl'))
                    etree.SubElement(point, etree.QName(C, 'idx'), val='1')
                    point.append(font_style(9, color='FFD700'))
                    own.append(font_style(bold=False, color='90EE90'))
                    etree.SubElement(own, etree.QName(C, 'showVal'), val='1')
                    series.insert(list(series).index(series.find('c:cat', NS)), own)
                content = etree.tostring(xml, xml_declaration=True, encoding='UTF-8')
            if THEME_CASE and entry.filename == 'xl/charts/chart2.xml':
                content = content.replace(b'<a:srgbClr val="FFFFFF"/>', b'<a:schemeClr val="accent2"/>')
            after.writestr(entry, content)
    return target.getvalue()


def color_ink(image, box, background, foreground):
    """Pixels must lie on the actual source foreground/background blend."""
    bg, fg = tuple(bytes.fromhex(background.lstrip('#'))), tuple(bytes.fromhex(foreground.lstrip('#')))
    delta = tuple(f - b for f, b in zip(fg, bg))
    norm = sum(d * d for d in delta)
    points = []
    for y in range(round(box[1]), round(box[3])):
        for x in range(round(box[0]), round(box[2])):
            rgb = image.getpixel((x, y))
            alpha = sum((v - b) * d for v, b, d in zip(rgb, bg, delta)) / norm
            residual = max(abs(v - b - alpha * d) for v, b, d in zip(rgb, bg, delta))
            if 0.6 <= alpha <= 1.01 and residual <= 2:
                points.append((x, y))
    return {'pixels': len(points), 'bounds': {
        'left': min(p[0] for p in points), 'right': max(p[0] for p in points),
        'top': min(p[1] for p in points), 'bottom': max(p[1] for p in points),
    } if points else None}


def verify(directory):
    book = load_workbook(directory / 'source.xlsx')
    assert [book.active[f'B{row}'].value for row in (2, 3)] == [10, 20]
    source_path = directory / ('downloaded.xlsx' if (directory / 'downloaded.xlsx').exists() else 'source.xlsx')
    with ZipFile(source_path) as source:
        theme = etree.fromstring(source.read('xl/theme/theme1.xml'))
        theme_color = '#' + theme.xpath('//a:clrScheme/a:accent2/a:srgbClr/@val', namespaces=NS)[0]
        second = etree.fromstring(source.read('xl/charts/chart2.xml'))
        third = etree.fromstring(source.read('xl/charts/chart3.xml'))
        assert second.xpath('//c:barChart/c:dLbls/c:txPr//a:defRPr/@sz', namespaces=NS) == ['1200']
        assert second.xpath('//c:barChart/c:dLbls/c:txPr//a:defRPr/@b', namespaces=NS) == ['1']
        assert third.xpath('//c:ser/c:dLbls/c:txPr//a:defRPr/@b', namespaces=NS) == ['0']
        assert third.xpath('//c:ser/c:dLbls/c:dLbl/c:txPr//a:defRPr/@sz', namespaces=NS) == ['900']
        assert third.xpath('//c:ser/c:dLbls/c:txPr//a:srgbClr/@val', namespaces=NS) == ['90EE90']
        assert third.xpath('//c:ser/c:dLbls/c:dLbl/c:txPr//a:srgbClr/@val', namespaces=NS) == ['FFD700']
        fourth = etree.fromstring(source.read('xl/charts/chart4.xml'))
        fifth = etree.fromstring(source.read('xl/charts/chart5.xml'))
        sixth = etree.fromstring(source.read('xl/charts/chart6.xml'))
        assert fourth.xpath('//c:barChart/c:dLbls/c:txPr//a:schemeClr/@val', namespaces=NS) == ['phClr']
        assert fifth.xpath('//c:barChart/c:dLbls/c:txPr//a:defRPr/@sz', namespaces=NS) == ['7200']
        assert sixth.xpath('//c:barChart/c:dLbls/c:txPr//a:endParaRPr/@sz', namespaces=NS) == ['900']
        assert sixth.xpath('//c:barChart/c:dLbls/c:txPr//a:srgbClr/@val', namespaces=NS) == ['A02040']
    if THEME_CASE:
        with ZipFile(directory / 'source.xlsx') as before, ZipFile(source_path) as after:
            changed = [n for n in before.namelist() if before.read(n) != after.read(n)]
            assert changed == ['xl/theme/theme1.xml'], changed
            assert theme_color.upper() == '#E97132'
            chart = etree.fromstring(after.read('xl/charts/chart2.xml'))
            assert chart.xpath('//c:dLbls/c:txPr//a:schemeClr/@val', namespaces=NS) == ['accent2']
    image = Image.open(directory / 'charts.png').convert('RGB')
    geometry = run_path(str(Path(__file__).with_name('canvas_chart_pixels.py')))['chart_pixels'](image, (BLUE,), ignore_enclosed_components=True)
    (directory / 'pixel-geometry.json').write_text(json.dumps(geometry, indent=2))
    assert len(geometry['frames']) == 6
    results = []
    for index, frame in enumerate(geometry['frames']):
        x, y, right, bottom = frame['x'], frame['y'], frame['x'] + frame['width'], frame['y'] + frame['height']
        bars = sorted((r for r in geometry['bars'] if x <= r['x'] and r['x'] + r['width'] <= right and y <= r['y'] and r['y'] + r['height'] <= bottom), key=lambda b: b['y'], reverse=True)
        assert len(bars) == 2, (index, bars)
        glyphs = []
        for point_index, bar in enumerate(bars):
            if index == 5:
                center = bar['y'] + bar['height'] / 2
                glyph = color_ink(image, (bar['x'] + bar['width'] + 2, center - 15, bar['x'] + bar['width'] + 80, center + 15), '#FFFFFF', '#A02040')
            else:
                color = ('#90EE90' if point_index == 0 else '#FFD700') if index == 2 else theme_color if THEME_CASE and index == 1 else '#FFFFFF'
                glyph = color_ink(image, (bar['x'] + 3, bar['y'] + 3, bar['x'] + bar['width'] - 3, bar['y'] + bar['height'] - 3), BLUE, color)
            if index in (3, 4):
                assert glyph['pixels'] == 0, (index, glyph)
            else:
                assert glyph['pixels'] >= 20, (index, glyph)
                bounds = glyph['bounds']
                assert abs((bounds['top'] + bounds['bottom']) / 2 - (bar['y'] + bar['height'] / 2)) <= 3
                if index != 5:
                    assert abs((bounds['left'] + bounds['right']) / 2 - (bar['x'] + bar['width'] / 2)) <= 3
            glyphs.append(glyph)
        results.append({'chart': index + 1, 'glyphs': glyphs, 'sourceStyleAndPlacementMatchPixels': True})
    for a, b in zip(results[0]['glyphs'], results[1]['glyphs']):
        assert b['bounds']['bottom'] - b['bounds']['top'] >= a['bounds']['bottom'] - a['bounds']['top'] + 2
        assert b['pixels'] > a['pixels'] * 1.2
    assert results[1]['glyphs'][0]['pixels'] > results[2]['glyphs'][0]['pixels'] * 1.2
    return {'ok': True, 'charts': results, 'sourceOOXMLAndCellsIndependentlyRead': True}


if __name__ == '__main__':
    if sys.argv[1] == 'create':
        Path(sys.argv[2]).write_bytes(create())
    else:
        print(json.dumps(verify(Path(sys.argv[2])), indent=2))
