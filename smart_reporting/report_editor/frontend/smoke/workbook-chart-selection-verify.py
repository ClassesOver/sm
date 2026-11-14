"""独立 openpyxl/lxml/ZIP 回读，避免使用被测 XLSX 引擎自证。"""
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from lxml import etree
from openpyxl import load_workbook

directory = Path(sys.argv[1])
ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
source = ZipFile(directory / 'source.xlsx')
results = []
for name, count in [('edited', 2), ('deleted', 1)]:
    data = (directory / f'{name}.xlsx').read_bytes()
    workbook = load_workbook(BytesIO(data))
    sheet = workbook.active
    assert sheet['A1'].value == 'Quarter' and sheet['A1'].font.bold is True
    assert sheet['B2'].value == 10 and sheet['B3'].value == 20
    assert len(sheet._charts) == count
    with ZipFile(BytesIO(data)) as archive:
        assert archive.read('xl/charts/chart1.xml') == source.read('xl/charts/chart1.xml')
        if name == 'edited':
            chart = etree.fromstring(archive.read('xl/charts/chart2.xml'))
            assert chart.xpath('string(c:chart/c:title//a:t)', namespaces=ns) == 'Selected'
            assert chart.find('.//c:pieChart', ns) is not None
            assert chart.xpath('string(.//c:legendPos/@val)', namespaces=ns) == 't'
            assert chart.xpath('string(.//c:dLbls/c:showPercent/@val)', namespaces=ns) == '1'
            assert chart.xpath('string(.//c:dLbls/c:showCatName/@val)', namespaces=ns) == '1'
            assert chart.xpath('.//c:dPt/c:spPr/a:solidFill/a:srgbClr/@val', namespaces=ns) == ['375623', '548235']
        else:
            assert 'xl/charts/chart2.xml' not in archive.namelist()
    results.append({'file': name, 'charts': count, 'untouchedChartExactBytes': True, 'manualBoldPreserved': True})
print(json.dumps(results, ensure_ascii=False))
