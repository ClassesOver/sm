"""Independent paste-special fixture/readback, outside the JS writer."""
import hashlib,json,sys
from pathlib import Path
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill
p=Path(sys.argv[1])
if '--fixture' in sys.argv:
 b=Workbook();s=b.active;s.title='Sheet'
 for row in [[2,3,'=A1+B1','保留原文'],[4,6,'=A2+B2']]:s.append(row)
 for cell in ['A1','A2','B1','B2']:s[cell].number_format='0.00';s[cell].font=Font(bold=True);s[cell].fill=PatternFill('solid',fgColor='FFFF00')
 for cell,value in {'D4':10,'E4':20,'D5':30,'E5':40,'N1':'保持邻接'}.items():s[cell]=value
 s['J1'].font=Font(italic=True);b.create_sheet('原件保留')['A1']='不改工作表';b.save(p/'fixture.xlsx');print('{}');sys.exit()
b=load_workbook(p/'paste-special.xlsx');s=b['Sheet']
for cell,value in {'D4':12,'E4':23,'D5':34,'E5':46,'G1':2,'H1':4,'G2':3,'H2':6,'J1':2,'P1':2,'L1':'=A1','D1':'保留原文','N1':'保持邻接'}.items():assert s[cell].value==value,(cell,s[cell].value,value)
assert s['J1'].number_format=='0.00';assert s['J1'].font.i and not s['J1'].font.b
assert s['C1'].value=='=A1+B1' and b['原件保留']['A1'].value=='不改工作表'
with ZipFile(p/'source.xlsx') as old,ZipFile(p/'paste-special.xlsx') as new:
 assert set(old.namelist())==set(new.namelist());changed=[n for n in old.namelist() if old.read(n)!=new.read(n)];assert set(changed)<={'xl/worksheets/sheet1.xml','xl/styles.xml'},changed
print(json.dumps({'ok':True,'changedParts':changed,'sha256':hashlib.sha256((p/'paste-special.xlsx').read_bytes()).hexdigest(),'numericTransposeLinkNumfmtPreserved':True},ensure_ascii=False))
