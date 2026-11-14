"""真实 Ribbon 删除/合并来源及独立 openpyxl/lxml/ZIP 回读。"""
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Font, PatternFill

directory = Path(sys.argv[1])
if '--fixture' in sys.argv:
    book = Workbook()
    sheet = book.active
    sheet.title = 'Data'
    for row in [('Quarter', 'North', 'South'), ('Q1', 10, 20), ('Q2', 30, 40)]:
        sheet.append(row)
    for column, anchor in [(2, 'F6'), (3, 'P6')]:
        chart = BarChart()
        chart.title = 'Same chart title'
        chart.add_data(Reference(sheet, min_col=column, min_row=1, max_row=3), titles_from_data=True)
        chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=3))
        sheet.add_chart(chart, anchor)
    book.save(directory / 'fixture.xlsx')
    incoming = Workbook()
    imported = incoming.active
    imported.title = 'Data'
    imported['A1'] = 'Imported literal'
    imported['A1'].font = Font(bold=True)
    imported['A1'].fill = PatternFill('solid', fgColor='FFFF00')
    imported['B1'] = '=6*2'
    imported['A2'] = 7
    imported.row_dimensions[2].height = 30
    imported.column_dimensions['A'].width = 22
    imported.merge_cells('A3:B3')
    incoming.save(directory / 'incoming-uncached.xlsx')
    with ZipFile(directory / 'incoming-uncached.xlsx') as source, ZipFile(directory / 'incoming.xlsx', 'w', ZIP_DEFLATED) as saved:
        for name in source.namelist():
            data = source.read(name)
            if name == 'xl/worksheets/sheet1.xml':
                xml = data.decode()
                xml = re.sub(r'(<c\b[^>]*\br="B1"[^>]*><f>6\*2</f>)<v></v>', r'\g<1><v>12</v>', xml)
                assert '<f>6*2</f><v>12</v>' in xml
                data = xml.encode()
            if name == 'xl/workbook.xml':
                xml = re.sub(r'<calcPr\b[^>]*/>', '<calcPr fullCalcOnLoad="0" calcCompleted="1"/>', data.decode())
                assert 'calcCompleted="1"' in xml
                data = xml.encode()
            saved.writestr(name, data)
    print(json.dumps({'sourceSha256': hashlib.sha256((directory / 'fixture.xlsx').read_bytes()).hexdigest(), 'incomingSha256': hashlib.sha256((directory / 'incoming.xlsx').read_bytes()).hexdigest()}))
    sys.exit(0)

before = load_workbook(directory / 'source.xlsx')
after = load_workbook(directory / 'ribbon-commands.xlsx')
assert after.sheetnames == ['Data', 'Data (2)']
assert after['Data']['J2'].value == 'Manual command draft'
assert after['Data']['J2'].font.bold is True
for row in range(1, 4):
    for column in range(1, 4):
        assert before['Data'].cell(row, column).value == after['Data'].cell(row, column).value
assert len(after['Data']._charts) == 1
imported = after['Data (2)']
assert imported['A1'].value == 'Imported literal'
assert imported['A1'].font.bold is True
assert imported['A1'].fill.fgColor.rgb[-6:] == 'FFFF00'
assert imported['B1'].value == 12 and imported['B1'].data_type != 'f'
assert imported['A2'].value == 7
assert imported.row_dimensions[2].height == 30
assert imported.column_dimensions['A'].width == 22
assert [str(item) for item in imported.merged_cells] == ['A3:B3']
assert not imported._charts
ns = {'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing', 'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart', 'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
with ZipFile(directory / 'source.xlsx') as source, ZipFile(directory / 'ribbon-commands.xlsx') as saved:
    assert 'xl/charts/chart1.xml' in saved.namelist()
    assert 'xl/charts/chart2.xml' not in saved.namelist()
    assert source.read('xl/charts/chart1.xml') == saved.read('xl/charts/chart1.xml')
    old = etree.fromstring(source.read('xl/drawings/drawing1.xml'))
    new = etree.fromstring(saved.read('xl/drawings/drawing1.xml'))
    assert len(old) == 2 and len(new) == 1
    assert etree.tostring(old[0], method='c14n') == etree.tostring(new[0], method='c14n')
    relationships = etree.fromstring(saved.read('xl/drawings/_rels/drawing1.xml.rels'))
    assert len(relationships) == 1
    assert relationships[0].get('Target').endswith('/chart1.xml')
    assert b'/xl/charts/chart2.xml' not in saved.read('[Content_Types].xml')
    for name in ['xl/theme/theme1.xml', 'docProps/core.xml']:
        assert source.read(name) == saved.read(name)
output = directory / 'ribbon-commands.xlsx'
print(json.dumps({'ok': True, 'bytes': output.stat().st_size, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'sheetNames': after.sheetnames, 'manualBoldPreserved': True, 'selectedSecondChartDeleted': True, 'firstChartAndAnchorExact': True, 'importedValueStyleGeometryPreserved': True, 'formulaImportedAsCachedLiteral': True}, ensure_ascii=False))
