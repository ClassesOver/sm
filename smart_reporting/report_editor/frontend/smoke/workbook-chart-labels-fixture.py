"""Explicit value labels: original switches, point identities and final pixels."""
import json
import sys
from io import BytesIO
from pathlib import Path
from runpy import run_path
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from PIL import Image

NS = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
BLUE, ORANGE = '#4472c4', '#ed7d31'
CASES = [('bar', 'Outside signed and zero', 'B', [3, -5, 0, None], 'outside-end', None),
         ('column', 'Center currency', 'B', [3, -5, 0, None], 'center', '"$"0.0'),
         ('bar', 'Reversed clipped inside', 'C', [3, 12, -5, 0], 'inside-end', '0.0'),
         ('bar', 'Point overrides', 'D', [3, 6, 9, 12], 'outside-end', '0'),
         ('bar', 'Series switches', 'D', [3, 6], 'outside-end', None),
         ('bar', 'Unsupported percent mode', 'D', [3, 6, 9, 12], 'outside-end', None),
         ('bar', 'Zero hidden by format', 'B', [3, -5, 0, None], 'outside-end', '0;-0;;'),
         ('bar', 'All labels hidden by format', 'D', [3, 6, 9, 12], 'outside-end', ';;;')]


def create():
    from smart_reporting.report_editor.native_office import patch_office
    book = Workbook()
    for row in [['Category', 'Signed', 'Clipped', 'Positive', 'Other'],
                ['A', 3, 3, 3, 2], ['B', -5, 12, 6, 4],
                ['C', 0, -5, 9, 6], ['D', None, 0, 12, 8]]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    additions = []
    for index, (kind, title, column, values, position, fmt) in enumerate(CASES):
        row = 1 + index * 8
        series = [{'name': 'Values', 'categories': list('ABCD')[:len(values)],
                   'values': [v or 0 for v in values], 'valuesRef': f"'Sheet'!${column}$2:${column}${len(values) + 1}"}]
        if index == 4:
            series.append({'name': 'Other', 'categories': ['A', 'B'], 'values': [2, 4], 'valuesRef': "'Sheet'!$E$2:$E$3"})
        additions.append({'worksheetSheetName': 'Sheet', 'anchor': {
            'fromRow': row, 'fromColumn': 6, 'fromRowOffset': 0, 'fromColumnOffset': 0,
            'toRow': row + 6, 'toColumn': 15, 'toRowOffset': 0, 'toColumnOffset': 0},
            'chart': {'chartType': kind, 'title': title, 'legend': 'none', 'series': series,
                      'dataLabels': 'percent' if index == 5 else 'value', 'dataLabelPosition': position,
                      **({'dataLabelFormat': fmt} if fmt else {}),
                      **({'valueAxis': {'min': -4, 'max': 8}} if index == 2 else {})}})
    raw = patch_office('xlsx', stream.getvalue(), [{'kind': 'applyChartAdditions', 'additions': additions}])
    target = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(target, 'w') as output:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename.startswith('xl/charts/chart') and entry.filename.endswith('.xml'):
                index = int(Path(entry.filename).stem.removeprefix('chart')) - 1
                xml = etree.fromstring(content)
                if index == 2:
                    xml.find('.//c:valAx/c:scaling/c:orientation', NS).set('val', 'maxMin')
                if index == 3:
                    labels = xml.find('.//c:barChart/c:dLbls', NS)
                    for point_index, tag, value in ((1, 'delete', '1'), (2, 'showVal', '0'), (3, 'numFmt', '"$"0')):
                        point = etree.Element(etree.QName(NS['c'], 'dLbl'))
                        etree.SubElement(point, etree.QName(NS['c'], 'idx'), val=str(point_index))
                        node = etree.SubElement(point, etree.QName(NS['c'], tag))
                        node.set('formatCode' if tag == 'numFmt' else 'val', value)
                        if tag == 'numFmt':
                            node.set('sourceLinked', '0')
                        labels.insert(0, point)
                if index == 4:
                    for series_index, series_xml in enumerate(xml.findall('.//c:ser', NS)):
                        labels = etree.Element(etree.QName(NS['c'], 'dLbls'))
                        if series_index == 1:
                            etree.SubElement(labels, etree.QName(NS['c'], 'numFmt'), formatCode='0%', sourceLinked='0')
                        etree.SubElement(labels, etree.QName(NS['c'], 'showVal'), val=str(series_index))
                        series_xml.insert(list(series_xml).index(series_xml.find('c:cat', NS)), labels)
                if index in (0, 1, 6):
                    cache = xml.find('.//c:ser/c:val/c:numRef/c:numCache', NS)
                    for point in cache.findall('c:pt', NS):
                        if point.get('idx') == '3':
                            cache.remove(point)
                content = etree.tostring(xml, xml_declaration=True, encoding='UTF-8')
            output.writestr(entry, content)
    return target.getvalue()


def verify(directory):
    book = load_workbook(directory / 'source.xlsx')
    with ZipFile(directory / 'source.xlsx') as source:
        for index, (_kind, _title, column, values, _position, _fmt) in enumerate(CASES, 1):
            assert [book.active[f'{column}{row}'].value for row in range(2, len(values) + 2)] == values
            xml = etree.fromstring(source.read(f'xl/charts/chart{index}.xml'))
            plot = xml.find('.//c:barChart', NS)
            assert plot.find('c:dLbls/c:showVal', NS).get('val') == ('0' if index == 6 else '1')
            if index == 2:
                assert plot.find('c:dLbls/c:numFmt', NS).get('formatCode') == '"$"0.0'
            if index == 3:
                assert xml.xpath('//c:valAx/c:scaling/c:min/@val', namespaces=NS) == ['-4']
                assert xml.xpath('//c:valAx/c:scaling/c:max/@val', namespaces=NS) == ['8']
                assert xml.xpath('//c:valAx/c:scaling/c:orientation/@val', namespaces=NS) == ['maxMin']
            if index == 4:
                assert plot.xpath('c:dLbls/c:dLbl[c:idx/@val="1"]/c:delete/@val', namespaces=NS) == ['1']
                assert plot.xpath('c:dLbls/c:dLbl[c:idx/@val="2"]/c:showVal/@val', namespaces=NS) == ['0']
            if index == 5:
                assert plot.xpath('c:ser/c:dLbls/c:showVal/@val', namespaces=NS) == ['0', '1']
    image = Image.open(directory / 'charts.png').convert('RGB')
    pixel_tools = run_path(str(Path(__file__).with_name('canvas_chart_pixels.py')))
    geometry = pixel_tools['chart_pixels'](image, (BLUE, ORANGE), ignore_enclosed_components=True)
    (directory / 'pixel-geometry.json').write_text(json.dumps(geometry, indent=2))
    assert len(geometry['frames']) == 8

    def dark(box):
        return sum(max(rgb) < 100 for rgb in image.crop(tuple(round(v) for v in box)).getdata())

    results = []
    for index, frame in enumerate(geometry['frames']):
        x, y, right, bottom = frame['x'], frame['y'], frame['x'] + frame['width'], frame['y'] + frame['height']
        bars = [r for r in geometry['bars'] if x <= r['x'] and r['x'] + r['width'] <= right and y <= r['y'] and r['y'] + r['height'] <= bottom]
        assert len(bars) == (2, 2, 3, 4, 4, 4, 2, 4)[index], (index, bars)
        bars.sort(key=lambda r: r['x'] if index == 1 else r['y'], reverse=index != 1)
        checks = []
        category_ink = dark((x + 8, y + 20, x + 26, bottom - 28)) if index != 1 else None
        if category_ink is not None:
            assert category_ink >= 10, (index, category_ink)
        if index in (1, 2):
            for bar_index, bar in enumerate(bars):
                glyph = pixel_tools['blue_bar_label_ink'](image, bar)
                assert glyph['pixels'] >= 20, (index, bar, glyph)
                bounds = glyph['bounds']
                if index == 1:
                    assert abs((bounds['left'] + bounds['right']) / 2 - (bar['x'] + bar['width'] / 2)) <= 3
                    assert abs((bounds['top'] + bounds['bottom']) / 2 - (bar['y'] + bar['height'] / 2)) <= 3
                elif bar_index < 2:
                    assert abs(bounds['left'] - bar['x'] - 4) <= 3
                else:
                    assert abs(bar['x'] + bar['width'] - bounds['right'] - 4) <= 3
                checks.append(glyph)
        elif index in (0, 6):
            for bar, value in zip(bars, (3, -5)):
                center = bar['y'] + bar['height'] / 2
                left = bar['x'] + bar['width'] + 2 if value > 0 else bar['x'] - 30
                ink = dark((left, center - 7, left + 28, center + 7))
                assert ink >= 3, (value, ink)
                checks.append(ink)
            zero_x = bars[0]['x']
            zero_y = y + 20 + (frame['height'] + 1 - 48) * 0.375
            ink = dark((zero_x + 2, zero_y - 7, zero_x + 25, zero_y + 7))
            assert ink >= 3 if index == 0 else ink == 0, (index, ink)
            checks.append(ink)
        elif index in (3, 4):
            for bar in bars:
                center = bar['y'] + bar['height'] / 2
                ink = dark((bar['x'] + bar['width'] + 2, center - 7, bar['x'] + bar['width'] + 44, center + 7))
                should_show = bars.index(bar) in (0, 3) if index == 3 else bar['color'] == ORANGE
                assert ink >= 3 if should_show else ink == 0, (index, bar, ink, should_show)
                checks.append(ink)
        else:
            ink = dark((min(b['x'] for b in bars) + 2, y + 22, right - 10, bottom - 29))
            assert ink == 0, ink
            assert all(pixel_tools['blue_bar_label_ink'](image, bar)['pixels'] == 0 for bar in bars)
            checks.append(ink)
        results.append({'chart': index + 1, 'bars': len(bars), 'labelInkPixels': checks, 'shortCategoryInk': category_ink, 'sourceLabelSwitchesAndPlacement': True})
    return {'ok': True, 'charts': results, 'sourceOOXMLAndValuesIndependentlyRead': True}


if __name__ == '__main__':
    if sys.argv[1] == 'create':
        Path(sys.argv[2]).write_bytes(create())
    else:
        print(json.dumps(verify(Path(sys.argv[2])), indent=2))
