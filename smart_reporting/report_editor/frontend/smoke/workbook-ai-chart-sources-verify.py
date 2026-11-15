"""Independent read-back of actual source-driven AI chart downloads."""
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from openpyxl import load_workbook


def verify(directory: Path):
    source, added, rebound = [(directory / name).read_bytes() for name in ('source.xlsx', 'added.xlsx', 'rebound.xlsx')]
    ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with ZipFile(BytesIO(source)) as original, ZipFile(BytesIO(added)) as first, ZipFile(BytesIO(rebound)) as second:
        for path in ('xl/charts/chart1.xml', 'xl/charts/chart2.xml'):
            assert original.read(path) == first.read(path) == second.read(path)
        for package, points, title, refs in (
            (first, ['10', '20'], '实际来源收入', ["'Sheet'!$A$2:$A$3", "'Sheet'!$B$2:$B$3"]),
            (second, ['20'], '第二季度收入', ["'Sheet'!$A$3:$A$3", "'Sheet'!$B$3:$B$3"]),
        ):
            xml = etree.fromstring(package.read('xl/charts/chart3.xml'))
            assert xml.xpath('//c:numCache/c:pt/c:v/text()', namespaces=ns) == points
            assert xml.xpath('//c:title//a:t/text()', namespaces=ns) == [title]
            assert xml.xpath('//c:ser//c:f/text()', namespaces=ns) == refs
        assert first.namelist() == second.namelist()
        changed = [name for name in first.namelist() if first.read(name) != second.read(name)]
        assert changed == ['xl/charts/chart3.xml'], changed
    for content, count, bold in ((source, 2, False), (added, 3, True), (rebound, 3, True)):
        sheet = load_workbook(BytesIO(content)).active
        assert len(sheet._charts) == count and sheet['A1'].font.bold is bold
        assert [sheet['B2'].value, sheet['B3'].value] == [10, 20]
    assert load_workbook(BytesIO(added)).active._charts[2].anchor._from.col == 4
    assert load_workbook(BytesIO(added)).active._charts[2].anchor._from.row == 19
    return {'ok': True, 'chartCounts': [2, 3, 3], 'rebindChangedParts': changed,
            'sha256': [hashlib.sha256(content).hexdigest() for content in (source, added, rebound)]}


if __name__ == '__main__':
    directory = Path(sys.argv[1])
    if '--sparkline' in sys.argv[2:]:
        source, saved = [(directory / name).read_bytes() for name in ('source.xlsx', 'sparkline.xlsx')]
        ns = {
            'x14': 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main',
            'xm': 'http://schemas.microsoft.com/office/excel/2006/main',
        }
        with ZipFile(BytesIO(source)) as original, ZipFile(BytesIO(saved)) as result:
            for part in ('xl/charts/chart1.xml', 'xl/charts/chart2.xml', 'xl/drawings/drawing1.xml'):
                assert original.read(part) == result.read(part)
            sheet = etree.fromstring(result.read('xl/worksheets/sheet1.xml'))
            groups = sheet.xpath('//x14:sparklineGroup', namespaces=ns)
            assert len(groups) == 1 and groups[0].get('type') == 'column'
            assert groups[0].xpath('./x14:colorSeries/@rgb', namespaces=ns) == ['FF214365']
            hosts = groups[0].xpath('.//xm:sqref/text()', namespaces=ns)
            references = groups[0].xpath('.//xm:f/text()', namespaces=ns)
            assert hosts == ['B8', 'B9']
            assert references == ["'Sheet'!$B$2:$C$2", "'Sheet'!$B$3:$C$3"]
        sheet = load_workbook(BytesIO(saved)).active
        assert len(sheet._charts) == 2 and sheet['A1'].font.bold
        assert [sheet[address].value for address in ('B2', 'C2', 'B3', 'C3')] == [10, 15, 20, -5]
        assert [sheet[address].value for address in hosts] == [None, None]
        print(json.dumps({'ok': True, 'hosts': hosts, 'references': references,
                          'sha256': hashlib.sha256(saved).hexdigest()}))
    else:
        print(json.dumps(verify(directory), ensure_ascii=False))
