"""Independent openpyxl/lxml checks of downloaded chart revisions."""
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from openpyxl import load_workbook


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
        assert xml.xpath('//c:title//a:t/text()', namespaces=ns) == ['Updated']
        assert xml.xpath('//c:barDir/@val', namespaces=ns) == ['bar']
        assert xml.xpath('//c:legendPos/@val', namespaces=ns) == ['b']
        assert xml.xpath('//c:numCache/c:pt/c:v/text()', namespaces=ns) == ['10', '20']
        assert xml.xpath('//c:ser//c:f/text()', namespaces=ns) == ["'Sheet'!$A$2:$A$3", "'Sheet'!$B$2:$B$3"]
        assert 'xl/charts/chart1.xml' not in second.namelist()
    for output, count in ((source, 2), (edited, 2), (deleted, 1)):
        sheet = load_workbook(BytesIO(output)).active
        assert len(sheet._charts) == count
        assert [sheet[f'B{row}'].value for row in (2, 3)] == [10, 20]
        assert sheet['A1'].font.bold is (output != source)
    return {'ok': True, 'sourceSha256': hashlib.sha256(source).hexdigest(),
            'editedSha256': hashlib.sha256(edited).hexdigest(), 'deletedSha256': hashlib.sha256(deleted).hexdigest(),
            'editedTitle': 'Updated', 'editedType': 'bar', 'editedLegend': 'bottom',
            'chartCounts': [2, 2, 1], 'otherChartByteIdentical': True, 'manualBoldRetained': True}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
