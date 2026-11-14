"""外部链接验收：独立 zipfile/lxml/openpyxl，不调用产品 reader/writer。"""
from __future__ import annotations
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree
from openpyxl import Workbook, load_workbook

S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P='http://schemas.openxmlformats.org/package/2006/relationships'
C='http://schemas.openxmlformats.org/package/2006/content-types'

def fixture(directory:Path):
 directory.mkdir(parents=True,exist_ok=True)
 workbook=Workbook();sheet=workbook.active;sheet.title='Report';sheet.append(['cached','bool','text','survivor']);workbook.create_sheet('Unrelated')['A1']='保持不变'
 stream=BytesIO();workbook.save(stream)
 with ZipFile(BytesIO(stream.getvalue())) as archive:parts={name:archive.read(name) for name in archive.namelist()}
 book=etree.fromstring(parts['xl/workbook.xml']);refs=etree.SubElement(book,f'{{{S}}}externalReferences')
 rels=etree.fromstring(parts['xl/_rels/workbook.xml.rels']);types=etree.fromstring(parts['[Content_Types].xml'])
 for index,target in [(1,'file:///private/old-source.xlsx'),(2,'https://must-not-fetch.invalid/forbidden.xlsx')]:
  etree.SubElement(refs,f'{{{S}}}externalReference',{f'{{{R}}}id':f'ext{index}'})
  etree.SubElement(rels,f'{{{P}}}Relationship',Id=f'ext{index}',Type=f'{R}/externalLink',Target=f'externalLinks/externalLink{index}.xml')
  etree.SubElement(types,f'{{{C}}}Override',PartName=f'/xl/externalLinks/externalLink{index}.xml',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml')
  parts[f'xl/externalLinks/externalLink{index}.xml']=(f'<externalLink xmlns="{S}" xmlns:r="{R}"><externalBook r:id="rId1"><sheetNames><sheetName val="Data"/></sheetNames></externalBook></externalLink>').encode()
  parts[f'xl/externalLinks/_rels/externalLink{index}.xml.rels']=(f'<Relationships xmlns="{P}"><Relationship Id="rId1" Type="{R}/externalLinkPath" Target="{target}" TargetMode="External"/></Relationships>').encode()
 parts['xl/workbook.xml']=etree.tostring(book);parts['xl/_rels/workbook.xml.rels']=etree.tostring(rels);parts['[Content_Types].xml']=etree.tostring(types)
 parts['xl/worksheets/sheet1.xml']=(f'<worksheet xmlns="{S}"><sheetData><row r="1"><c r="A1"><f>[1]Data!A1*2</f><v>6</v></c><c r="B1" t="b"><f>[1]Data!B1</f><v>1</v></c><c r="C1" t="str"><f>[1]Data!C1</f><v>old text</v></c><c r="D1"><f>[2]Data!A1</f><v>90</v></c><c r="E1"><f>OFFSET([1]Data!A1,0,0)</f><v>11</v></c></row></sheetData></worksheet>').encode()
 parts['customXml/keep.bin']=bytes([1,2,3,255])
 with ZipFile(directory/'fixture.xlsx','w',ZIP_DEFLATED) as archive:
  for name,value in parts.items():archive.writestr(name,value)
 source=Workbook();source.active.title='Data';source.active.append([12,False,'new text']);source.save(directory/'replacement.xlsx')
 return {'sourceSha256':hashlib.sha256((directory/'fixture.xlsx').read_bytes()).hexdigest()}

def verify(directory:Path):
 before=ZipFile(directory/'fixture.xlsx');after=ZipFile(directory/'external-links.xlsx')
 removed={'xl/externalLinks/externalLink1.xml','xl/externalLinks/_rels/externalLink1.xml.rels'}
 assert set(before.namelist())-set(after.namelist())==removed
 changed={name for name in after.namelist() if name in before.namelist() and before.read(name)!=after.read(name)}
 assert changed=={'xl/workbook.xml','xl/_rels/workbook.xml.rels','[Content_Types].xml','xl/worksheets/sheet1.xml'}
 sheet=etree.fromstring(after.read('xl/worksheets/sheet1.xml'));ns={'s':S};cells={cell.get('r'):cell for cell in sheet.findall('.//s:c',ns)}
 assert cells['A1'].find('s:f',ns) is None and cells['A1'].findtext('s:v',namespaces=ns)=='24'
 assert cells['B1'].get('t')=='b' and cells['B1'].findtext('s:v',namespaces=ns)=='0'
 assert cells['C1'].findtext('s:is/s:t',namespaces=ns)=='new text'
 assert cells['D1'].findtext('s:f',namespaces=ns)=='[1]Data!A1'
 assert cells['E1'].find('s:f',ns) is None and cells['E1'].findtext('s:v',namespaces=ns)=='11'
 parsed=load_workbook(directory/'external-links.xlsx',data_only=True)
 assert [parsed['Report'].cell(1,col).value for col in range(1,6)]==[24,False,'new text',90,11]
 assert parsed['Unrelated']['A1'].value=='保持不变'
 for name in after.namelist():
  if name.endswith(('.xml','.rels')):etree.fromstring(after.read(name))
 return {'changedParts':sorted(changed),'removedParts':sorted(removed),'values':[24,False,'new text',90,11],'survivorFormula':'[1]Data!A1','openpyxl':True}

if __name__=='__main__':
 directory=Path(sys.argv[1]);print(json.dumps(fixture(directory) if '--fixture' in sys.argv else verify(directory),ensure_ascii=False))
