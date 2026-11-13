"""Actual category OOXML, live blanks, source order and independent pixels."""
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
DATA = ([3, None, 9, 6], [1, 2, None, 4])


def create():
    from smart_reporting.report_editor.native_office import patch_office
    book = Workbook()
    for row in [['Category', 'First', 'Second', None, 'Percent'],
                ['Alpha', 3, 1, None, 0.1], [None, None, 2, None, 0.25],
                ['Gamma', 9, None, None, 0.5], ['Fourth', 6, 4, None, 0.75]]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    additions = []
    for index, kind in enumerate(('bar', 'column', 'bar', 'column', 'bar', 'bar')):
        entries = []
        for series_index, values in enumerate(DATA[:2 if index < 3 else 1]):
            column = 'BC'[series_index]
            entries.append({'name': f'Series {series_index + 1}', 'categories': ['STALE'] * 4,
                            'categoriesRef': "'Sheet'!$A$2:$A$5", 'values': [v or 0 for v in values],
                            'valuesRef': f"'Sheet'!${column}$2:${column}$5"})
        row = 1 + index * 8
        additions.append({'worksheetSheetName': 'Sheet', 'anchor': {
            'fromRow': row, 'fromColumn': 6, 'fromRowOffset': 0, 'fromColumnOffset': 0,
            'toRow': row + 6, 'toColumn': 15, 'toRowOffset': 0, 'toColumnOffset': 0},
            'chart': {'chartType': kind, 'title': ('Live bar', 'Live column', 'Reverse bar', 'Reverse percent top', 'Cached right', 'Hidden category')[index],
                      'legend': 'none', 'series': entries}})
    raw = patch_office('xlsx', stream.getvalue(), [{'kind': 'applyChartAdditions', 'additions': additions}])
    target = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(target, 'w') as output:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename.startswith('xl/charts/chart') and entry.filename.endswith('.xml'):
                index = int(Path(entry.filename).stem.removeprefix('chart')) - 1
                xml = etree.fromstring(content)
                axis = xml.find('.//c:catAx', NS)
                if index in (2, 3):
                    axis.find('c:scaling/c:orientation', NS).set('val', 'maxMin')
                if index == 3:
                    axis.find('c:axPos', NS).set('val', 't')
                    cat = xml.find('.//c:ser/c:cat', NS)
                    cat.clear()
                    ref = etree.SubElement(cat, etree.QName(NS['c'], 'numRef'))
                    etree.SubElement(ref, etree.QName(NS['c'], 'f')).text = "'Sheet'!$E$2:$E$5"
                    cache = etree.SubElement(ref, etree.QName(NS['c'], 'numCache'))
                    etree.SubElement(cache, etree.QName(NS['c'], 'formatCode')).text = '0%'
                    etree.SubElement(cache, etree.QName(NS['c'], 'ptCount')).set('val', '4')
                    for point_index, value in enumerate((0.1, 0.25, 0.5, 0.75)):
                        point = etree.SubElement(cache, etree.QName(NS['c'], 'pt'), idx=str(point_index))
                        etree.SubElement(point, etree.QName(NS['c'], 'v')).text = str(value)
                if index == 4:
                    axis.find('c:axPos', NS).set('val', 'r')
                    cat = xml.find('.//c:ser/c:cat', NS)
                    cat.find('.//c:f', NS).text = 'Other!A2:A5'
                    for point, label in zip(cat.findall('.//c:pt/c:v', NS), ('External A', 'External B', 'External C', 'Long external category ' * 12)):
                        point.text = label
                if index == 5:
                    axis.find('c:delete', NS).set('val', '1')
                # Align original caches with actual blank sheet values too.
                for series, values in zip(xml.findall('.//c:ser', NS), DATA):
                    for point in series.findall('.//c:val/c:numRef/c:numCache/c:pt', NS):
                        if values[int(point.get('idx'))] is None:
                            point.getparent().remove(point)
                content = etree.tostring(xml, xml_declaration=True, encoding='UTF-8')
            output.writestr(entry, content)
    return target.getvalue()


def verify(directory):
    book = load_workbook(directory / 'source.xlsx')
    assert [book.active[f'A{row}'].value for row in range(2, 6)] == ['Alpha', None, 'Gamma', 'Fourth']
    assert [book.active[f'B{row}'].value for row in range(2, 6)] == DATA[0]
    assert [book.active[f'C{row}'].value for row in range(2, 6)] == DATA[1]
    with ZipFile(directory / 'source.xlsx') as source:
        for index in range(1, 7):
            xml = etree.fromstring(source.read(f'xl/charts/chart{index}.xml'))
            if index in (3, 4):
                assert xml.xpath('//c:catAx/c:scaling/c:orientation/@val', namespaces=NS) == ['maxMin']
            if index == 4:
                assert xml.xpath('//c:numCache/c:formatCode/text()', namespaces=NS)[0] == '0%'
            if index == 5:
                assert xml.xpath('//c:ser/c:cat//c:f/text()', namespaces=NS) == ['Other!A2:A5']
            if index == 6:
                assert xml.xpath('//c:catAx/c:delete/@val', namespaces=NS) == ['1']
    image = Image.open(directory / 'charts.png').convert('RGB')
    geometry = run_path(str(Path(__file__).with_name('canvas_chart_pixels.py')))['chart_pixels'](image, (BLUE, ORANGE))
    (directory / 'pixel-geometry.json').write_text(json.dumps(geometry, indent=2))
    assert len(geometry['frames']) == 6
    def ink(box):
        return sum(max(rgb) < 100 for rgb in image.crop(box).getdata())
    results = []
    for index, frame in enumerate(geometry['frames']):
        x, y, right, bottom = frame['x'], frame['y'], frame['x'] + frame['width'], frame['y'] + frame['height']
        marks = [r for r in geometry['bars'] if x <= r['x'] and r['x'] + r['width'] <= right and y <= r['y'] and r['y'] + r['height'] <= bottom]
        assert len(marks) == (6 if index < 3 else 3), (index, marks)
        horizontal = index not in (1, 3)
        data_top = y + (40 if index == 3 else 20)
        data_height = frame['height'] + 1 - 48
        for series_index, values in enumerate(DATA[:2 if index < 3 else 1]):
            bars = sorted((r for r in marks if r['color'] == (BLUE, ORANGE)[series_index]), key=lambda r: r['y'] if horizontal else r['x'], reverse=index in (0, 4, 5) or index == 3)
            actual = [(point_index, value) for point_index, value in enumerate(values) if value is not None]
            assert len(bars) == len(actual)
            if horizontal:
                band = data_height / 4
                for bar, (point_index, value) in zip(bars, actual):
                    slot = point_index if index == 2 else 3 - point_index
                    group_series = series_index if index == 2 else (1 - series_index if index == 0 else 0)
                    thickness = band * 0.7 / (2 if index < 3 else 1)
                    expected_y = data_top + band * slot + band * 0.15 + thickness * group_series
                    assert abs(bar['y'] - expected_y) <= 2, (index, point_index, bar, expected_y)
                    if index in (0, 2):
                        assert abs(bar['width'] - (right - 8 - bar['x']) * value / 10) <= 2
            else:
                for bar, (_point_index, value) in zip(bars, actual):
                    assert abs(bar['height'] - data_height * value / 10) <= 2, (index, bar)
        if horizontal:
            start = min(r['x'] for r in marks)
            category_box = (right - 260, data_top, right - 8, data_top + data_height) if index == 4 else (x + 8, data_top, max(x + 24, start - 2), data_top + data_height)
            category_ink = ink(category_box)
            assert category_ink == 0 if index == 5 else category_ink >= 20, (index, category_ink)
            if index == 0:
                # Blank category index 1 stays a genuinely empty label slot.
                slot = 2
                assert ink((x + 8, data_top + slot * band, start - 2, data_top + (slot + 1) * band)) == 0
        else:
            category_ink = ink((x + 40, y + 20, right - 8, y + 40)) if index == 3 else ink((x + 40, bottom - 27, right - 8, bottom - 8))
            assert category_ink >= 20, (index, category_ink)
        results.append({'chart': index + 1, 'bars': len(marks), 'categoryInk': category_ink, 'sourceCategoryAndSeriesOrder': True})
    return {'ok': True, 'charts': results, 'sourceOOXMLAndCellsIndependentlyRead': True}


if __name__ == '__main__':
    if sys.argv[1] == 'create':
        Path(sys.argv[2]).write_bytes(create())
    else:
        print(json.dumps(verify(Path(sys.argv[2])), indent=2))
