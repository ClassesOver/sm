"""独立 openpyxl/lxml/ZIP 校验真实浏览器几何编辑下载产物。"""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from lxml import etree
from openpyxl import load_workbook


directory = Path(sys.argv[1])
expected = json.loads((directory / 'expected.json').read_text())
namespaces = {'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
              'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
              'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


def anchors(archive):
    result = {}
    for path in archive.namelist():
        if not path.startswith('xl/drawings/drawing') or not path.endswith('.xml'):
            continue
        root = etree.fromstring(archive.read(path))
        rel_path = path.rsplit('/', 1)[0] + '/_rels/' + path.rsplit('/', 1)[1] + '.rels'
        relations = etree.fromstring(archive.read(rel_path))
        targets = {item.get('Id'): item.get('Target').rsplit('/', 1)[-1] for item in relations}
        for anchor in root:
            charts = anchor.xpath('.//c:chart', namespaces=namespaces)
            if not charts:
                continue
            assert len(charts) == 1
            chart = 'xl/charts/' + targets[charts[0].get('{%s}id' % namespaces['r'])]
            marker = {}
            for side, prefix in [('from', 'from'), ('to', 'to')]:
                for tag, key in [('row', 'Row'), ('col', 'Column'), ('rowOff', 'RowOffset'), ('colOff', 'ColumnOffset')]:
                    marker[prefix + key] = int(anchor.find(f'xdr:{side}/xdr:{tag}', namespaces).text)
            result[chart] = (marker, etree.tostring(anchor))
    return result


with ZipFile(directory / 'source.xlsx') as source, ZipFile(directory / 'geometry.xlsx') as edited:
    source_anchors, edited_anchors = anchors(source), anchors(edited)
    assert edited_anchors['xl/charts/chart2.xml'][0] == expected['anchor']
    assert edited_anchors['xl/charts/chart2.xml'][0] != source_anchors['xl/charts/chart2.xml'][0]
    assert edited_anchors['xl/charts/chart1.xml'][1] == source_anchors['xl/charts/chart1.xml'][1]
    for path in ['xl/charts/chart1.xml', 'xl/charts/chart2.xml']:
        assert edited.read(path) == source.read(path), path
    allowed = {'xl/worksheets/sheet1.xml', 'xl/drawings/drawing1.xml', 'xl/styles.xml', 'xl/workbook.xml'}
    assert set(edited.namelist()) == set(source.namelist())
    unchanged = []
    for path in source.namelist():
        if path not in allowed:
            assert edited.read(path) == source.read(path), path
            unchanged.append(path)
    workbook = load_workbook(BytesIO((directory / 'geometry.xlsx').read_bytes()))
    sheet = workbook.active
    assert sheet['A1'].value == 'Manual geometry'
    assert sheet['A1'].font.bold is True
    assert sheet['B2'].value == 10 and sheet['B3'].value == 20
    assert len(sheet._charts) == 2
    actual = sheet._charts[1].anchor
    for side, prefix in [('_from', 'from'), ('to', 'to')]:
        marker = getattr(actual, side)
        for field, key in [('row', 'Row'), ('col', 'Column'), ('rowOff', 'RowOffset'), ('colOff', 'ColumnOffset')]:
            assert getattr(marker, field) == expected['anchor'][prefix + key]
    print(json.dumps({'ok': True, 'manualA1': sheet['A1'].value, 'manualBold': True,
        'chartCount': 2, 'anchor': edited_anchors['xl/charts/chart2.xml'][0],
        'originalChartAnchorExact': True, 'bothChartPartsExact': True,
        'unchangedZipEntryCount': len(unchanged),
        'sha256': hashlib.sha256((directory / 'geometry.xlsx').read_bytes()).hexdigest()}, ensure_ascii=False))
