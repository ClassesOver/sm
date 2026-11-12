"""Manual linear value domains and clipping, checked from OOXML and pixels."""
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

CASES = [('bar', 2, 8, 'B', [3, 6]), ('column', -4, 8, 'B', [3, 6]),
         ('bar', 2, 8, 'B', [3, 6]), ('bar', 2, 8, 'C', [-5, 12]),
         ('bar', -8, -2, 'D', [-3, -6]), ('bar', 1, 100, 'B', [3, 6])]


def create():
    book = Workbook()
    for row in [['Q', 'Positive', 'Clipped', 'Negative'], ['A', 3, -5, -3], ['B', 6, 12, -6]]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    additions = []
    for index, (kind, low, high, column, values) in enumerate(CASES):
        row = 1 + index * 8
        additions.append({'worksheetSheetName': 'Sheet', 'anchor': {
            'fromRow': row, 'fromColumn': 4, 'fromRowOffset': 0, 'fromColumnOffset': 0,
            'toRow': row + 6, 'toColumn': 13, 'toRowOffset': 0, 'toColumnOffset': 0},
            'chart': {'chartType': kind, 'title': ('Manual 2..8', 'Mixed -4..8', 'Reversed 2..8', 'Clipped 2..8', 'Negative -8..-2', 'Logarithmic')[index],
                'valueAxis': {'min': low, 'max': high}, 'legend': 'none',
                'series': [{'name': 'Values', 'categories': ['A', 'B'], 'values': values,
                            'valuesRef': f"'Sheet'!${column}$2:${column}$3"}]}})
    raw = patch_office('xlsx', stream.getvalue(), [{'kind': 'applyChartAdditions', 'additions': additions}])
    target = BytesIO()
    ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
    with ZipFile(BytesIO(raw)) as source, ZipFile(target, 'w') as result:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename.endswith(('chart3.xml', 'chart6.xml')):
                xml = etree.fromstring(content)
                scaling = xml.xpath('//c:valAx/c:scaling', namespaces=ns)[0]
                if entry.filename.endswith('chart3.xml'):
                    scaling.find('c:orientation', ns).set('val', 'maxMin')
                else:
                    log = etree.Element(etree.QName(ns['c'], 'logBase'))
                    log.set('val', '10')
                    scaling.insert(0, log)
                content = etree.tostring(xml, xml_declaration=True, encoding='UTF-8')
            result.writestr(entry, content)
    return target.getvalue()


def verify(directory):
    book = load_workbook(directory / 'source.xlsx')
    ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
    with ZipFile(directory / 'source.xlsx') as source:
        for index, (_kind, low, high, column, values) in enumerate(CASES, 1):
            xml = etree.fromstring(source.read(f'xl/charts/chart{index}.xml'))
            assert xml.xpath('//c:valAx/c:scaling/c:min/@val', namespaces=ns) == [str(low)]
            assert xml.xpath('//c:valAx/c:scaling/c:max/@val', namespaces=ns) == [str(high)]
            assert [book.active[f'{column}{row}'].value for row in (2, 3)] == values
            if index == 3:
                assert xml.xpath('//c:valAx/c:scaling/c:orientation/@val', namespaces=ns) == ['maxMin']
            if index == 6:
                assert xml.xpath('//c:valAx/c:scaling/c:logBase/@val', namespaces=ns) == ['10']
    image = Image.open(directory / 'charts.png').convert('RGB')
    geometry = run_path(str(Path(__file__).with_name('canvas_chart_pixels.py')))['chart_pixels'](image, ('#4472c4',))
    (directory / 'pixel-geometry.json').write_text(json.dumps(geometry, indent=2))
    assert len(geometry['frames']) == 6
    results = []
    for index, frame in enumerate(geometry['frames']):
        x, y, right, bottom = frame['x'], frame['y'], frame['x'] + frame['width'], frame['y'] + frame['height']
        bars = sorted((r for r in geometry['bars'] if x <= r['x'] and r['x'] + r['width'] <= right
                      and y <= r['y'] and r['y'] + r['height'] <= bottom), key=lambda r: r['x'] if index == 1 else r['y'])
        assert len(bars) == (0 if index == 5 else 1 if index == 3 else 2), (index, bars)
        width, height = frame['width'] - 16, frame['height'] + 1 - 28
        if index in (0, 2, 4):
            for bar, proportion in zip(bars, (1 / 6, 4 / 6)):
                assert abs(bar['width'] - width * proportion) <= 2, (index, bar)
                if index == 0:
                    assert abs(bar['x'] - (x + 8)) <= 2
                else:
                    assert abs(bar['x'] + bar['width'] - (right - 8)) <= 2
        elif index == 1:
            baseline = bottom - 7 - height / 3
            for bar, proportion in zip(bars, (3 / 12, 6 / 12)):
                assert abs(bar['height'] - height * proportion) <= 2
                assert abs(bar['y'] + bar['height'] - baseline) <= 2
        elif index == 3:
            assert abs(bars[0]['width'] - width) <= 2
            assert bars[0]['y'] > y + 20 + height / 2  # The excluded first category remains empty.
        else:
            ink = sum(max(rgb) < 100 for rgb in image.crop((x + 10, y + 22, right - 10, y + 50)).getdata())
            assert ink >= 30, ink
        results.append({'chart': index + 1, 'bars': len(bars), 'savedDomainAndClippingMatchPixels': True})
    return {'ok': True, 'charts': results, 'sourceOOXMLIndependentlyRead': True}


if __name__ == '__main__':
    if sys.argv[1] == 'create':
        Path(sys.argv[2]).write_bytes(create())
    else:
        print(json.dumps(verify(Path(sys.argv[2])), indent=2))
