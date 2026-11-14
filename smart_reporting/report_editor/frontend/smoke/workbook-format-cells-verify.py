"""Independent Format Cells fixture/readback; never calls the edited JS engine."""
import hashlib,json,sys
from pathlib import Path
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font, PatternFill, Protection
from openpyxl.chart import BarChart,Reference
from lxml import etree
p=Path(sys.argv[1])
if '--fixture' in sys.argv:
    b=Workbook();s=b.active;s.title='Sheet'
    s.append([12.3,'保留邻接',7]);s.append(['=A1*2','不改文本',8])
    s['A1'].font=Font(name='Calibri',size=11,bold=True);s['A2'].font=Font(name='Arial',size=12)
    s['A1'].fill=PatternFill('solid',fgColor='FFFF00');s['A2'].fill=PatternFill('solid',fgColor='00FFFF')
    s['B1'].font=Font(name='Calibri',size=11,bold=True,color='123456')
    c=BarChart();c.add_data(Reference(s,min_col=3,min_row=1,max_row=2));s.add_chart(c,'F5')
    b.save(p/'fixture.xlsx');print(json.dumps({'sha256':hashlib.sha256((p/'fixture.xlsx').read_bytes()).hexdigest()}));sys.exit()
b=load_workbook(p/'format-cells.xlsx');s=b.active
assert s['A1'].value==12.3 and s['A2'].value=='=A1*2'
for key in ['A1','A2']:
    c=s[key]
    assert c.number_format=='0.000' and c.font.name=='Arial' and c.font.sz==16
    assert c.font.b is False and c.font.i is True and c.font.u=='single' and c.font.strike is True
    assert c.font.color.rgb=='FFC00000',c.font.color
    assert c.alignment.horizontal=='distributed' and c.alignment.vertical=='center'
    assert c.alignment.wrap_text and c.alignment.textRotation==135 and c.alignment.indent==2
    assert c.fill.patternType is None and c.protection.locked is False and c.protection.hidden is True
    assert c.border.left.style=='double' and c.border.right.style=='double'
    assert c.border.left.color.rgb=='FF0070C0'
assert s['A1'].border.top.style=='double' and s['A2'].border.bottom.style=='double'
assert s['B1'].value=='保留邻接' and s['B1'].font.bold and s['B1'].font.color.rgb=='00123456'
assert s['B2'].value=='不改文本' and len(s._charts)==1
with ZipFile(p/'source.xlsx') as before,ZipFile(p/'format-cells.xlsx') as after:
    assert set(before.namelist())==set(after.namelist())
    changed=[name for name in before.namelist() if before.read(name)!=after.read(name)]
    assert set(changed)<= {'xl/worksheets/sheet1.xml','xl/styles.xml'},changed
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    old=etree.fromstring(before.read('xl/worksheets/sheet1.xml'));new=etree.fromstring(after.read('xl/worksheets/sheet1.xml'))
    for addr in ['B1','B2','C1','C2']:
        assert etree.tostring(old.xpath(f'//s:c[@r="{addr}"]',namespaces=ns)[0],method='c14n')==etree.tostring(new.xpath(f'//s:c[@r="{addr}"]',namespaces=ns)[0],method='c14n')
print(json.dumps({'ok':True,'sha256':hashlib.sha256((p/'format-cells.xlsx').read_bytes()).hexdigest(),'changedParts':changed,'allSixTabsPersisted':True,'valuesFormulasNeighboursChartPreserved':True},ensure_ascii=False))
