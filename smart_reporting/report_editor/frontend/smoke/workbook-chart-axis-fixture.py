"""Source-linked bar/column axis titles, independently checked in final pixels."""
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


def create():
    book = Workbook()
    for row in [['Quarter', 'Sales', None, 'Group'], ['Q1', 3], ['Q2', 6]]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    additions = []
    for index, kind in enumerate(('column', 'bar', 'column', 'bar')):
        row = 1 + index * 9
        additions.append({'worksheetSheetName': 'Sheet', 'anchor': {
            'fromRow': row, 'fromColumn': 4, 'fromRowOffset': 0, 'fromColumnOffset': 0,
            'toRow': row + 6, 'toColumn': 13, 'toRowOffset': 0, 'toColumnOffset': 0},
            'chart': {'chartType': kind, 'title': ('Column', 'Bar', '', 'Hidden value')[index],
                'axisTitles': {'category': ('Quarter', 'Quarter', 'Year & quarter', 'OLD GROUP')[index],
                               'value': ('Amount (USD)', 'Amount (USD)', 'USD', 'DO NOT DRAW')[index]},
                'legend': 'bottom' if index == 3 else 'none',
                'series': [{'name': 'Sales', 'categories': ['Q1', 'Q2'], 'values': [3, 6],
                            'valuesRef': "'Sheet'!$B$2:$B$3"}]}})
    raw = patch_office('xlsx', stream.getvalue(), [{'kind': 'applyChartAdditions', 'additions': additions}])
    target = BytesIO()
    ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
    with ZipFile(BytesIO(raw)) as source, ZipFile(target, 'w') as result:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename.endswith('chart3.xml'):
                content = content.replace(b'<c:axPos val="b"/>', b'<c:axPos val="t"/>').replace(b'<c:axPos val="l"/>', b'<c:axPos val="r"/>')
                xml = etree.fromstring(content)
                for title in xml.xpath('/c:chartSpace/c:chart/c:title', namespaces=ns):
                    title.getparent().remove(title)
                content = etree.tostring(xml, xml_declaration=True, encoding='UTF-8')
            elif entry.filename.endswith('chart4.xml'):
                xml = etree.fromstring(content)
                xml.xpath('//c:valAx/c:delete', namespaces=ns)[0].set('val', '1')
                old = xml.xpath('//c:catAx/c:title/c:tx', namespaces=ns)[0]
                replacement = etree.fromstring(b'<c:tx xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:strRef><c:f>\'Sheet\'!$D$1</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>OLD GROUP</c:v></c:pt></c:strCache></c:strRef></c:tx>')
                old.getparent().replace(old, replacement)
                content = etree.tostring(xml, xml_declaration=True, encoding='UTF-8')
            result.writestr(entry, content)
    return target.getvalue()


def verify(directory):
    book = load_workbook(directory / 'source.xlsx')
    assert book.active['D1'].value == 'Group'
    assert [book.active[f'B{row}'].value for row in (2, 3)] == [3, 6]
    ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart', 'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with ZipFile(directory / 'source.xlsx') as source:
        third = etree.fromstring(source.read('xl/charts/chart3.xml'))
        fourth = etree.fromstring(source.read('xl/charts/chart4.xml'))
        assert third.xpath('/c:chartSpace/c:chart/c:title', namespaces=ns) == []
        assert third.xpath('//c:catAx/c:axPos/@val', namespaces=ns) == ['t']
        assert third.xpath('//c:valAx/c:axPos/@val', namespaces=ns) == ['r']
        assert fourth.xpath('//c:valAx/c:delete/@val', namespaces=ns) == ['1']
        assert fourth.xpath('//c:catAx/c:title/c:tx/c:strRef/c:f/text()', namespaces=ns) == ["'Sheet'!$D$1"]
        assert fourth.xpath('//c:valAx/c:title//a:t/text()', namespaces=ns) == ['DO NOT DRAW']
    image = Image.open(directory / 'charts.png').convert('RGB')
    geometry = run_path(str(Path(__file__).with_name('canvas_chart_pixels.py')))['chart_pixels'](image, ('#4472c4',))
    (directory / 'pixel-geometry.json').write_text(json.dumps(geometry, indent=2))
    assert len(geometry['frames']) == 4

    def ink(box):
        return sum(max(rgb) < 100 for rgb in image.crop(box).getdata())

    results = []
    for index, frame in enumerate(geometry['frames']):
        x, y, right, bottom = frame['x'], frame['y'], frame['x'] + frame['width'], frame['y'] + frame['height']
        marks = [r for r in geometry['bars'] if x <= r['x'] and r['x'] + r['width'] <= right
                 and y <= r['y'] and r['y'] + r['height'] <= bottom]
        swatches = [r for r in marks if 6 <= r['width'] <= 9 and 6 <= r['height'] <= 9]
        bars = [r for r in marks if r not in swatches]
        assert len(bars) == 2 and len(swatches) == (1 if index == 3 else 0), (index, marks)
        if index == 2:
            vertical = ink((right - 32, y + 32, right - 8, bottom - 8))
            horizontal = ink((x + 8, y + 8, right - 32, y + 32))
            assert ink((x + 4, y + 2, x + 240, y + 10)) == 0  # No promoted main title.
            assert all(r['y'] >= y + 32 and r['x'] + r['width'] <= right - 32 for r in bars)
        else:
            vertical = ink((x + 8, y + 20, x + 32, bottom - 32))
            # With a hidden value title the category name band is adjacent
            # to this empty horizontal region. Start at the independent
            # pixel-recovered data edge, excluding the real Q1 glyph edge.
            horizontal_left = min(r['x'] for r in bars) if index == 3 else x + 32
            horizontal = ink((horizontal_left, bottom - (56 if index == 3 else 32), right - 8, bottom - (32 if index == 3 else 8)))
            assert all(r['x'] >= x + 32 for r in bars)
        assert vertical >= 15, (index, vertical)
        assert horizontal >= 15 if index < 3 else horizontal == 0, (index, horizontal)
        results.append({'chart': index + 1, 'verticalTitleInk': vertical, 'horizontalTitleInk': horizontal,
                        'dataBars': len(bars), 'legendSwatches': len(swatches)})
    return {'ok': True, 'charts': results, 'sourceOOXMLIndependentlyRead': True}


if __name__ == '__main__':
    if sys.argv[1] == 'create':
        Path(sys.argv[2]).write_bytes(create())
    else:
        print(json.dumps(verify(Path(sys.argv[2])), indent=2))
