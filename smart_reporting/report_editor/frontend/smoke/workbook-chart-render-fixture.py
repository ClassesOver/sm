"""Create real mixed-sign charts and independently inspect painted screenshots."""
import json
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from openpyxl import Workbook, load_workbook
from PIL import Image

from smart_reporting.report_editor.native_office import patch_office


def create():
    book = Workbook()
    for row in [['Category', 'First', 'Second', 'Zeros'], ['A', 3, 1, 0],
                ['B', -5, None, 0], ['C', 0, -2, 0], ['D', None, 6, 0]]:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    additions = []
    for index, kind in enumerate(('bar', 'column', 'bar')):
        series = [{'name': 'First', 'values': [3, -5, 0, 0], 'valuesRef': "'Sheet'!$B$2:$B$5"},
                  {'name': 'Second', 'values': [1, 0, -2, 6], 'valuesRef': "'Sheet'!$C$2:$C$5"}]
        if index == 2:
            series = [{'name': 'Zeros', 'values': [0, 0, 0, 0], 'valuesRef': "'Sheet'!$D$2:$D$5"}]
        series = [{**item, 'categories': ['A', 'B', 'C', 'D'], 'categoriesRef': "'Sheet'!$A$2:$A$5"} for item in series]
        row = 1 + index * 11
        additions.append({'worksheetSheetName': 'Sheet', 'anchor': {
            'fromRow': row, 'fromColumn': 4, 'fromRowOffset': 0, 'fromColumnOffset': 0,
            'toRow': row + 8, 'toColumn': 12, 'toRowOffset': 0, 'toColumnOffset': 0},
            'chart': {'chartType': kind, 'title': f'{kind} {index + 1}', 'legend': 'none', 'series': series}})
    output = patch_office('xlsx', stream.getvalue(), [{'kind': 'applyChartAdditions', 'additions': additions}])
    # Match actual missing sheet cells in the OOXML caches, rather than writing
    # invented zero values at those point indices.
    ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
    target = BytesIO()
    with ZipFile(BytesIO(output)) as source, ZipFile(target, 'w') as edited:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename in {'xl/charts/chart1.xml', 'xl/charts/chart2.xml'}:
                xml = etree.fromstring(content)
                for series, missing in zip(xml.xpath('//c:ser', namespaces=ns), (3, 1)):
                    for point in series.xpath(f'.//c:numCache/c:pt[@idx="{missing}"]', namespaces=ns):
                        point.getparent().remove(point)
                content = etree.tostring(xml, xml_declaration=True, encoding='UTF-8')
            edited.writestr(entry, content)
    return target.getvalue()


def verify(directory):
    book = load_workbook(directory / 'source.xlsx')
    assert [book.active[f'B{r}'].value for r in range(2, 6)] == [3, -5, 0, None]
    assert [book.active[f'C{r}'].value for r in range(2, 6)] == [1, None, -2, 6]
    assert len(book.active._charts) == 3
    image = Image.open(directory / 'charts.png').convert('RGB')
    pixels = image.load()
    # Recover frames and complete colored components from screenshot pixels,
    # independently of the renderer's geometry or offscreen canvas internals.
    edges = []
    for y in range(image.height):
        start = None
        for x in range(image.width + 1):
            matches = x < image.width and pixels[x, y] == (154, 164, 173)
            if matches and start is None:
                start = x
            elif not matches and start is not None:
                if x - start >= 600:
                    edges.append((start, y, x - start))
                start = None
    assert len(edges) == 6, edges
    frames = [{'x': edges[i][0], 'y': edges[i][1], 'width': edges[i][2],
               'height': edges[i + 1][1] - edges[i][1]} for i in (0, 2, 4)]
    bars = []
    for color in ('#4472c4', '#ed7d31'):
        rgb = tuple(bytes.fromhex(color[1:]))
        points = {(x, y) for frame in frames
                  for y in range(frame['y'] + 1, frame['y'] + frame['height'])
                  for x in range(frame['x'] + 1, frame['x'] + frame['width']) if pixels[x, y] == rgb}
        while points:
            seed = points.pop()
            pending, component = [seed], [seed]
            while pending:
                x, y = pending.pop()
                for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if point in points:
                        points.remove(point)
                        pending.append(point)
                        component.append(point)
            x0, x1 = min(p[0] for p in component), max(p[0] for p in component)
            y0, y1 = min(p[1] for p in component), max(p[1] for p in component)
            bars.append({'x': x0, 'y': y0, 'width': x1 - x0 + 1, 'height': y1 - y0 + 1, 'color': color})
    evidence = {'frames': frames, 'bars': bars}
    (directory / 'pixel-geometry.json').write_text(json.dumps(evidence, indent=2))
    def dark_pixels(box):
        return sum(1 for r, g, b in image.crop(box).getdata() if max(r, g, b) < 100)

    # Presence checks use final pixels, not text widths/DOM labels. The title
    # regions exclude the frame border; the grid region is the source header row.
    title_ink = [dark_pixels((f['x'] + 4, f['y'] + 2, f['x'] + 250, f['y'] + 18)) for f in frames]
    grid_ink = dark_pixels((50, frames[0]['y'] - 23, frames[0]['x'] - 3, frames[0]['y'] - 3))
    assert all(count >= 15 for count in title_ink), title_ink
    assert grid_ink >= 80, grid_ink
    results = []
    for index, frame in enumerate(frames):
        bars = [r for r in evidence['bars'] if (frame['x'] <= r['x'] and r['x'] + r['width'] <= frame['x'] + frame['width'] + 1
                and frame['y'] <= r['y'] and r['y'] + r['height'] <= frame['y'] + frame['height'] + 1)]
        assert len(bars) == (5 if index < 2 else 0), (index, bars)
        for bar in bars:
            point = (round(bar['x'] + bar['width'] / 2), round(bar['y'] + bar['height'] / 2))
            color = tuple(bytes.fromhex(bar['color'].removeprefix('#')))
            assert image.getpixel(point) == color, (point, image.getpixel(point), color)
        if index < 2:
            blue = sorted((b for b in bars if b['color'] == '#4472c4'), key=lambda b: b['y'] if index == 0 else b['x'])
            orange = sorted((b for b in bars if b['color'] == '#ed7d31'), key=lambda b: b['y'] if index == 0 else b['x'])
            assert len(blue) == 2 and len(orange) == 3
            axis = 'width' if index == 0 else 'height'
            # Solid-color components omit antialiased edge pixels. Compare
            # every length against the largest bar with an absolute 2px
            # tolerance; dividing by the shortest (16px) amplifies rounding.
            largest = orange[2][axis]
            for bar, value in zip(blue + orange, (3, 5, 1, 2, 6)):
                assert abs(bar[axis] - largest * value / 6) <= 2, (bar, value)
            if index == 0:
                assert abs(blue[1]['x'] + blue[1]['width'] - blue[0]['x']) <= 2
                assert abs(blue[0]['x'] - orange[0]['x']) <= 2
                assert abs((orange[2]['y'] - orange[0]['y']) / (blue[1]['y'] - blue[0]['y']) - 3) < 0.04
            else:
                assert abs(blue[0]['y'] + blue[0]['height'] - blue[1]['y']) <= 2
                assert abs((orange[2]['x'] - orange[0]['x']) / (blue[1]['x'] - blue[0]['x']) - 3) < 0.04
        results.append({'chart': index + 1, 'bars': len(bars), 'actualPixelsMatch': True})
    assert len(results) == 3
    return {'ok': True, 'charts': results, 'sourceCellsIndependentlyRead': True,
            'titleInkPixels': title_ink, 'gridHeaderInkPixels': grid_ink}


if __name__ == '__main__':
    if sys.argv[1] == 'create':
        Path(sys.argv[2]).write_bytes(create())
    else:
        print(json.dumps(verify(Path(sys.argv[2])), indent=2))
