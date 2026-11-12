"""Independent openpyxl/lxml checks of downloaded chart revisions."""
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path
from runpy import run_path
from zipfile import ZipFile

from lxml import etree
from openpyxl import load_workbook
from PIL import Image


def verify(directory: Path):
    source = (directory / 'source.xlsx').read_bytes()
    edited = (directory / 'edited.xlsx').read_bytes()
    deleted = (directory / 'deleted.xlsx').read_bytes()
    ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(edited)) as first, ZipFile(BytesIO(deleted)) as second:
        untouched = 'xl/charts/chart2.xml'
        assert before.read(untouched) == first.read(untouched) == second.read(untouched)
        xml = etree.fromstring(first.read('xl/charts/chart1.xml'))
        assert xml.xpath('/c:chartSpace/c:chart/c:title//a:t/text()', namespaces=ns) == ['Updated']
        assert xml.xpath('//c:barDir/@val', namespaces=ns) == ['bar']
        assert xml.xpath('//c:legendPos/@val', namespaces=ns) == ['b']
        assert xml.xpath('//c:numCache/c:pt/c:v/text()', namespaces=ns) == ['10', '20']
        assert xml.xpath('//c:ser/c:cat//c:pt/c:v/text()', namespaces=ns) == ['Q1', 'Q2']
        assert xml.xpath('//c:ser//c:f/text()', namespaces=ns) == ["'Sheet'!$A$2:$A$3", "'Sheet'!$B$2:$B$3"]
        assert 'xl/charts/chart1.xml' not in second.namelist()
        saved_request = json.loads((directory / 'edited-save.json').read_text())['request']
        axis_titles = next((record['axisTitles'] for operation in saved_request['operations']
            if operation['kind'] == 'applyChartEdits' for record in operation['edits'] if 'axisTitles' in record), None)
        if axis_titles:
            assert xml.xpath('//c:catAx/c:title//a:t/text()', namespaces=ns) == [axis_titles['category']]
            assert xml.xpath('//c:valAx/c:title//a:t/text()', namespaces=ns) == [axis_titles['value']]
        value_range = next((record['valueAxis'] for operation in saved_request['operations']
            if operation['kind'] == 'applyChartEdits' for record in operation['edits'] if 'valueAxis' in record), None)
        if value_range:
            assert value_range == {'min': 5, 'max': 25}
            assert xml.xpath('//c:valAx/c:scaling/c:min/@val', namespaces=ns) == ['5']
            assert xml.xpath('//c:valAx/c:scaling/c:max/@val', namespaces=ns) == ['25']
    for output, count in ((source, 2), (edited, 2), (deleted, 1)):
        sheet = load_workbook(BytesIO(output)).active
        assert len(sheet._charts) == count
        assert [sheet[f'B{row}'].value for row in (2, 3)] == [10, 20]
        assert [sheet[f'A{row}'].value for row in (2, 3)] == ['Q1', 'Q2']
        assert sheet['A1'].font.bold is (output != source)
    text_pixels = []
    for name in ('edited', 'deleted'):
        image = Image.open(directory / (name + '-reopened.png')).convert('RGB')
        # This fixed fixture's visible chart is chart1 after edit and chart2
        # after deletion (at the right edge). Find the first long top border,
        # including the partially visible chart2 frame on the second revision.
        pixels = image.load()
        border = None
        for y in range(260, min(360, image.height)):
            run = None
            for x in range(image.width + 1):
                match = x < image.width and pixels[x, y] == (154, 164, 173)
                if match and run is None:
                    run = x
                elif not match and run is not None:
                    if x - run >= 150:
                        border = (run, y)
                        break
                    run = None
            if border:
                break
        assert border is not None, name
        x, y = border
        title_ink = sum(1 for r, g, b in image.crop((x + 4, y + 2, min(x + 250, image.width), y + 18)).getdata() if max(r, g, b) < 100)
        grid_ink = sum(1 for r, g, b in image.crop((50, y - 23, 300, y - 3)).getdata() if max(r, g, b) < 100)
        assert title_ink >= 15 and grid_ink >= 40, (name, title_ink, grid_ink)
        text_pixels.append({'revision': name, 'titleInkPixels': title_ink, 'gridHeaderInkPixels': grid_ink})
        if name == 'edited':
            geometry = run_path(str(Path(__file__).with_name('canvas_chart_pixels.py')))['chart_pixels'](image, ('#4472c4',))
            marks = geometry['bars']
            swatches = [mark for mark in marks if 6 <= mark['width'] <= 9 and 6 <= mark['height'] <= 9]
            bars = [mark for mark in marks if mark not in swatches]
            assert len(swatches) == 1 and len(bars) == 2, (swatches, bars)
            assert swatches[0]['y'] >= max(bar['y'] + bar['height'] for bar in bars) + 4
            text_pixels[-1]['bottomLegendSwatches'] = len(swatches)
            if axis_titles:
                frame = geometry['frames'][0]
                x, y, right, bottom = frame['x'], frame['y'], frame['x'] + frame['width'], frame['y'] + frame['height']
                category_ink = sum(max(rgb) < 100 for rgb in image.crop((x + 8, y + 20, x + 32, bottom - 56)).getdata())
                value_ink = sum(max(rgb) < 100 for rgb in image.crop((x + 32, bottom - 56, right - 8, bottom - 32)).getdata())
                assert category_ink >= 15 and value_ink >= 15, (category_ink, value_ink)
                text_pixels[-1].update(categoryAxisTitleInk=category_ink, valueAxisTitleInk=value_ink)
            if value_range:
                frame = geometry['frames'][0]
                # Recover the actual zero/start from pixels. The category
                # name gutter sits inside the separate title band.
                plot_left = min(bar['x'] for bar in bars)
                plot_width = frame['x'] + frame['width'] - 8 - plot_left
                assert plot_left >= frame['x'] + 8 + (24 if axis_titles else 0)
                ordered = sorted(bars, key=lambda bar: bar['y'], reverse=True)
                for bar, fraction in zip(ordered, (0.25, 0.75)):
                    assert abs(bar['width'] - plot_width * fraction) <= 2, (bar, plot_width)
                auto_image = Image.open(directory / 'auto-range-preview.png').convert('RGB')
                auto_geometry = run_path(str(Path(__file__).with_name('canvas_chart_pixels.py')))['chart_pixels'](auto_image, ('#4472c4',))
                auto_bars = sorted((r for r in auto_geometry['bars'] if r['width'] > 9 or r['height'] > 9), key=lambda bar: bar['y'], reverse=True)
                assert len(auto_bars) == 2
                # Pinned source automatic range: 0..25 (5% headroom,
                # 5 major unit) for the actual data 10/20.
                for bar, fraction in zip(auto_bars, (10 / 25, 20 / 25)):
                    assert abs(bar['width'] - plot_width * fraction) <= 2, (bar, plot_width)
                text_pixels[-1]['manualRangeAndAutoResetPixels'] = True
    return {'ok': True, 'sourceSha256': hashlib.sha256(source).hexdigest(),
            'editedSha256': hashlib.sha256(edited).hexdigest(), 'deletedSha256': hashlib.sha256(deleted).hexdigest(),
            'editedTitle': 'Updated', 'editedType': 'bar', 'editedLegend': 'bottom',
            'chartCounts': [2, 2, 1], 'otherChartByteIdentical': True, 'manualBoldRetained': True, 'categoryLabelsRetained': True,
            'reopenedTextPixels': text_pixels}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
