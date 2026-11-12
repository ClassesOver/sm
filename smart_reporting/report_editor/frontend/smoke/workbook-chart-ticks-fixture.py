"""Original XLSX inputs and independent pixel measurements for numeric axes."""
import json
import sys
from io import BytesIO
from pathlib import Path
from runpy import run_path
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from PIL import Image

from smart_reporting.report_editor.native_office import patch_office

CASES = [
    ('bar', 'Mixed auto', 'B', [300, -500], None),
    ('column', 'Negative auto right', 'C', [-10, -20], None),
    ('bar', 'Percent 0..50%', 'D', [0.1, 0.4], {'min': 0, 'max': 0.5}),
    ('bar', 'Reversed top 2..8', 'E', [3, 6], {'min': 2, 'max': 8}),
    ('bar', 'Hidden axis', 'E', [3, 6], None),
    ('bar', 'Dense saved unit', 'E', [3, 6], {'min': 0, 'max': 10}),
]
NS = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}


def create():
    book = Workbook()
    for row in [['Q', 'Mixed', 'Negative', 'Percent', 'Values'],
                ['A', 300, -10, 0.1, 3], ['B', -500, -20, 0.4, 6]]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    additions = []
    for index, (kind, title, column, values, bounds) in enumerate(CASES):
        row = 1 + index * 8
        additions.append({'worksheetSheetName': 'Sheet', 'anchor': {
            'fromRow': row, 'fromColumn': 6, 'fromRowOffset': 0, 'fromColumnOffset': 0,
            'toRow': row + 6, 'toColumn': 15, 'toRowOffset': 0, 'toColumnOffset': 0},
            'chart': {'chartType': kind, 'title': title, 'legend': 'none',
                **({'valueAxis': bounds} if bounds else {}),
                'series': [{'name': 'Values', 'categories': ['A', 'B'], 'values': values,
                            'valuesRef': f"'Sheet'!${column}$2:${column}$3"}]}})
    raw = patch_office('xlsx', stream.getvalue(), [{'kind': 'applyChartAdditions', 'additions': additions}])
    target = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(target, 'w') as result:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename.startswith('xl/charts/chart') and entry.filename.endswith('.xml'):
                index = int(Path(entry.filename).stem.removeprefix('chart')) - 1
                xml = etree.fromstring(content)
                axis = xml.find('.//c:valAx', NS)
                if index in (2, 5):
                    unit = etree.SubElement(axis, etree.QName(NS['c'], 'majorUnit'))
                    unit.set('val', '0.1')
                if index == 2:
                    # Insert numFmt before crossAx, preserving CT_ValAx order.
                    fmt = etree.Element(etree.QName(NS['c'], 'numFmt'))
                    fmt.set('formatCode', '0%')
                    fmt.set('sourceLinked', '0')
                    axis.insert(list(axis).index(axis.find('c:crossAx', NS)), fmt)
                if index in (1, 3):
                    axis.find('c:axPos', NS).set('val', 'r' if index == 1 else 't')
                if index == 3:
                    axis.find('c:scaling/c:orientation', NS).set('val', 'maxMin')
                if index == 4:
                    axis.find('c:delete', NS).set('val', '1')
                content = etree.tostring(xml, xml_declaration=True, encoding='UTF-8')
            result.writestr(entry, content)
    return target.getvalue()


def verify(directory):
    book = load_workbook(directory / 'source.xlsx')
    with ZipFile(directory / 'source.xlsx') as source:
        for index, (_kind, _title, column, values, bounds) in enumerate(CASES, 1):
            assert [book.active[f'{column}{row}'].value for row in (2, 3)] == values
            xml = etree.fromstring(source.read(f'xl/charts/chart{index}.xml'))
            if bounds:
                for name, value in bounds.items():
                    assert float(xml.xpath(f'//c:valAx/c:scaling/c:{name}/@val', namespaces=NS)[0]) == value
            if index in (3, 6):
                assert xml.xpath('//c:valAx/c:majorUnit/@val', namespaces=NS) == ['0.1']
            if index == 3:
                assert xml.xpath('//c:valAx/c:numFmt/@formatCode', namespaces=NS) == ['0%']
            if index == 4:
                assert xml.xpath('//c:valAx/c:axPos/@val', namespaces=NS) == ['t']
                assert xml.xpath('//c:valAx/c:scaling/c:orientation/@val', namespaces=NS) == ['maxMin']
            if index == 5:
                assert xml.xpath('//c:valAx/c:delete/@val', namespaces=NS) == ['1']
    image = Image.open(directory / 'charts.png').convert('RGB')
    geometry = run_path(str(Path(__file__).with_name('canvas_chart_pixels.py')))['chart_pixels'](image, ('#4472c4',))
    (directory / 'pixel-geometry.json').write_text(json.dumps(geometry, indent=2))
    assert len(geometry['frames']) == 6
    hidden_frame = geometry['frames'][4]
    hidden_bars = [r for r in geometry['bars'] if hidden_frame['y'] < r['y'] < hidden_frame['y'] + hidden_frame['height']]
    assert len(hidden_bars) == 2
    # Same A/B category labels and frame width in all horizontal fixtures.
    plot_left = min(bar['x'] for bar in hidden_bars)
    horizontal_width = hidden_frame['x'] + hidden_frame['width'] - 8 - plot_left
    results = []
    for index, frame in enumerate(geometry['frames']):
        x, y, right, bottom = frame['x'], frame['y'], frame['x'] + frame['width'], frame['y'] + frame['height']
        bars = sorted((r for r in geometry['bars'] if x <= r['x'] and r['x'] + r['width'] <= right
                      and y <= r['y'] and r['y'] + r['height'] <= bottom), key=lambda r: r['x'] if index == 1 else r['y'], reverse=index != 1)
        assert len(bars) == 2, (index, bars)
        width, height = horizontal_width, frame['height'] + 1 - 48
        if index == 1:
            for bar, magnitude in zip(bars, (10, 20)):
                assert abs(bar['height'] - height * magnitude / 22.5) <= 2, bar
                assert abs(bar['y'] - (y + 20)) <= 2, bar  # Zero is at the top.
            tick_box = (right - 45, y + 22, right - 8, bottom - 8)
        else:
            expected = ((0.3, 0.5), (), (0.2, 0.8), (1 / 6, 4 / 6), (3 / 7, 6 / 7), (0.3, 0.6))[index]
            for bar, proportion in zip(bars, expected):
                assert abs(bar['width'] - width * proportion) <= 2, (index, bar, width)
            if index == 0:
                assert abs(bars[0]['x'] - (plot_left + width * 0.6)) <= 2
                assert abs(bars[1]['x'] + bars[1]['width'] - bars[0]['x']) <= 2
            if index == 3:
                assert all(abs(b['x'] + b['width'] - (right - 8)) <= 2 for b in bars)
            tick_box = (x + 8, y + 20, right - 8, y + 40) if index == 3 else (x + 8, bottom - 27, right - 8, bottom - 8)
        ink = sum(max(rgb) < 100 for rgb in image.crop(tick_box).getdata())
        assert ink == 0 if index == 4 else ink >= 20, (index, ink)
        results.append({'chart': index + 1, 'bars': 2, 'tickInkPixels': ink, 'domainAndZeroMatchSourceValues': True})
    return {'ok': True, 'charts': results, 'sourceOOXMLAndCellsIndependentlyRead': True}


if __name__ == '__main__':
    if sys.argv[1] == 'create':
        Path(sys.argv[2]).write_bytes(create())
    else:
        print(json.dumps(verify(Path(sys.argv[2])), indent=2))
