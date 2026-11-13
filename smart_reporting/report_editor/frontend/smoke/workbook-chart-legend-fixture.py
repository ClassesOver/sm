"""Independent OOXML and screenshot checks for common automatic legends."""
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

POSITIONS = ('right', 'bottom', 'left', 'top', 'none')
COLORS = ('#126B3A', '#A02040')


def create():
    book = Workbook()
    for row in [['Quarter', 'Live Revenue', 'Costs & tax'], ['Q1', 3, 2], ['Q2', 6, 4]]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    additions = []
    for index, position in enumerate(POSITIONS):
        row = 1 + index * 9
        additions.append({'worksheetSheetName': 'Sheet', 'anchor': {
            'fromRow': row, 'fromColumn': 4, 'fromRowOffset': 0, 'fromColumnOffset': 0,
            'toRow': row + 6, 'toColumn': 13, 'toRowOffset': 0, 'toColumnOffset': 0},
            'chart': {'chartType': 'bar', 'title': 'Legend ' + position, 'legend': position, 'series': [
                {'name': 'Revenue', 'categories': ['Q1', 'Q2'], 'values': [3, 6], 'valuesRef': "'Sheet'!$B$2:$B$3", 'color': COLORS[0]},
                {'name': 'Costs & tax', 'categories': ['Q1', 'Q2'], 'values': [2, 4], 'valuesRef': "'Sheet'!$C$2:$C$3", 'color': COLORS[1]},
            ]}})
    output = patch_office('xlsx', stream.getvalue(), [{'kind': 'applyChartAdditions', 'additions': additions}])
    target = BytesIO()
    with ZipFile(BytesIO(output)) as source, ZipFile(target, 'w') as result:
        for entry in source.infolist():
            raw = source.read(entry.filename)
            if entry.filename.startswith('xl/charts/chart'):
                raw = raw.replace(b'<c:tx><c:v>Revenue</c:v></c:tx>', b'<c:tx><c:strRef><c:f>\'Sheet\'!$B$1</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>STALE</c:v></c:pt></c:strCache></c:strRef></c:tx>')
            result.writestr(entry, raw)
    return target.getvalue()


def verify(directory):
    book = load_workbook(directory / 'source.xlsx')
    assert book.active['B1'].value == 'Live Revenue'
    assert [book.active[f'B{r}'].value for r in (2, 3)] == [3, 6]
    assert [book.active[f'C{r}'].value for r in (2, 3)] == [2, 4]
    ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart', 'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with ZipFile(directory / 'source.xlsx') as source:
        for index, position in enumerate(('r', 'b', 'l', 't', None), 1):
            xml = etree.fromstring(source.read(f'xl/charts/chart{index}.xml'))
            assert xml.xpath('//c:legend/c:legendPos/@val', namespaces=ns) == ([position] if position else [])
            assert xml.xpath('//c:ser/c:spPr/a:solidFill/a:srgbClr/@val', namespaces=ns) == [c[1:] for c in COLORS]
            assert xml.xpath('//c:ser/c:tx/c:strRef/c:f/text()', namespaces=ns) == ["'Sheet'!$B$1"]
    image = Image.open(directory / 'charts.png').convert('RGB')
    evidence = run_path(str(Path(__file__).with_name('canvas_chart_pixels.py')))['chart_pixels'](image, COLORS)
    (directory / 'pixel-geometry.json').write_text(json.dumps(evidence, indent=2))
    assert len(evidence['frames']) == 5
    results = []
    for frame, position in zip(evidence['frames'], POSITIONS):
        marks = [r for r in evidence['bars'] if frame['x'] <= r['x'] and r['x'] + r['width'] <= frame['x'] + frame['width']
                 and frame['y'] <= r['y'] and r['y'] + r['height'] <= frame['y'] + frame['height']]
        swatches = [r for r in marks if 6 <= r['width'] <= 9 and 6 <= r['height'] <= 9]
        bars = [r for r in marks if r not in swatches]
        assert len(bars) == 4, (position, bars)
        assert len(swatches) == (0 if position == 'none' else 2), (position, swatches)
        for color in COLORS:
            assert sum(r['color'] == color for r in bars) == 2
        for swatch in swatches:
            if position == 'right':
                assert swatch['x'] >= max(b['x'] + b['width'] for b in bars) + 4
            elif position == 'left':
                assert swatch['x'] + swatch['width'] <= min(b['x'] for b in bars) - 4
            elif position == 'bottom':
                assert swatch['y'] >= max(b['y'] + b['height'] for b in bars) + 4
            else:
                assert swatch['y'] + swatch['height'] <= min(b['y'] for b in bars) - 4
            ink = sum(max(rgb) < 100 for rgb in image.crop((swatch['x'] + 12, swatch['y'] - 5,
                min(swatch['x'] + 180, frame['x'] + frame['width'] - 1), swatch['y'] + 12)).getdata())
            assert ink >= 15, (position, ink)
        results.append({'position': position, 'bars': len(bars), 'swatches': len(swatches), 'legendTextPixels': True})
    return {'ok': True, 'charts': results, 'sourceOOXMLIndependentlyRead': True}


if __name__ == '__main__':
    if sys.argv[1] == 'create':
        Path(sys.argv[2]).write_bytes(create())
    else:
        print(json.dumps(verify(Path(sys.argv[2])), indent=2))
