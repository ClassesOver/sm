import {execFileSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {expect,it} from 'vitest'
import {applySheetEdits,readWorkbook} from '../src'
import {assemblePackage,createBufferEntrySource} from '../src/zip'
import {chartReferencesSheet,readChartFormulas} from '../src/sheets-edit'

function fixture(owner='Other'){
 return new Uint8Array(execFileSync(fileURLToPath(new URL('../../../../../../.venv/bin/python',import.meta.url)),['-c',`
from io import BytesIO
import sys
from openpyxl import Workbook
from openpyxl.chart import BarChart,Reference
b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other')
for i in range(1,6):s.cell(i,1,i);other.cell(i,2,i)
chart=BarChart();chart.add_data(Reference(s,min_col=1,min_row=1,max_row=5));b[${JSON.stringify(owner)}].add_chart(chart,'D2')
f=BytesIO();b.save(f);sys.stdout.buffer.write(f.getvalue())
`]))
}
it.each(['default','c-prefixed'])('refuses sheet removal referenced by actual chart series with %s namespace',async mode=>{
 let bytes:Uint8Array=fixture();const source=await createBufferEntrySource(bytes),path='xl/charts/chart1.xml',xml=await source.readText(path)
 expect(xml).toContain("'Source'!$A$1:$A$5")
 if(mode==='c-prefixed'){
  const prefixed=xml.replace('xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"','xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"').replace(/<(\/?)([A-Za-z][\w]*)(?=[\s/>])/g,'<$1c:$2')
  bytes=(await assemblePackage(bytes,{replaced:new Map([[path,prefixed]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 }
 expect((await readWorkbook(bytes)).sheets.map(sheet=>sheet.name)).toEqual(['Source','Other'])
 const result=applySheetEdits(bytes,{renames:[],additions:[],removals:['Source'],order:['Other']})
 await expect(result).rejects.toThrow('仍有图表引用')
})
it.each([
 ['chart alias','<q:chartSpace xmlns:q="http://schemas.openxmlformats.org/drawingml/2006/chart"><q:f>Source!A1</q:f></q:chartSpace>',true],
 ['drawing main','<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:f>Source!A1</a:f></a:graphic>',false],
 ['foreign c prefix','<c:root xmlns:c="urn:foreign"><c:f>Source!A1</c:f></c:root>',false],
])('resolves chart namespace semantics instead of prefix spelling: %s',(_name,xml,referenced)=>{
 expect(chartReferencesSheet(xml,'Source')).toBe(referenced)
})
it('follows fixed-source owned-drawing cascade when the removed sheet owns its only chart',async()=>{
 const bytes=fixture('Source')
 const result=applySheetEdits(bytes,{renames:[],additions:[],removals:['Source'],order:['Other']})
 await expect(result).resolves.toBeInstanceOf(Uint8Array)
})
it.each([
 ['<chartSpace xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"><f>source!a1</f></chartSpace>',true],
 ['<c:root xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><foreign xmlns:c="urn:foreign"><c:f>Source!A1</c:f></foreign></c:root>',false],
 ['<root xmlns="urn:foreign"><f xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart">Source!A1</f></root>',true],
 ['<root xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"><f><![CDATA[Source!A1]]></f></root>',true],
 ...['&quot;Source!A1&quot;','[book.xlsx]Source!A1',"'[book.xlsx]Source'!A1"].map(formula=>[`<root xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"><f>${formula}</f></root>`,false]),
])('protects scoped bindings and formula literal/external boundaries %#', (xml,referenced)=>{
 expect(chartReferencesSheet(String(xml),'Source')).toBe(referenced)
})
it('exposes decoded formulas, accepts empty charts and rejects malformed namespace XML',()=>{
 expect(readChartFormulas('<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"/>')).toEqual([])
 expect(readChartFormulas('<root xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"><f>IF(Source!A1&lt;1,0,1)</f><f><![CDATA[Other!A1]]></f></root>')).toEqual(['IF(Source!A1<1,0,1)','Other!A1'])
 expect(()=>readChartFormulas('<c:chartSpace><c:f>Source!A1</c:f></c:chartSpace>')).toThrow()
 expect(()=>readChartFormulas('<root><f>Source!A1</root>')).toThrow()
})
