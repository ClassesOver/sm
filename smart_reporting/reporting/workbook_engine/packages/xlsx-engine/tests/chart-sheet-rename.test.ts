import {execFileSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {expect,it} from 'vitest'
import {applySheetEdits} from '../src'
import {assemblePackage,createBufferEntrySource} from '../src/zip'
import {readChartFormulas,renameSheetReferencesInChart} from '../src/sheets-edit'
const uri='http://schemas.openxmlformats.org/drawingml/2006/chart'
const plan={renames:[{sheetName:'Source',newName:"New & O'Brien"}],additions:[],removals:[],order:["New & O'Brien",'Other']}
function fixture(){return new Uint8Array(execFileSync(fileURLToPath(new URL('../../../../../../.venv/bin/python',import.meta.url)),['-c',`
from io import BytesIO
import sys
from openpyxl import Workbook
from openpyxl.chart import BarChart,Reference
b=Workbook();s=b.active;s.title='Source';o=b.create_sheet('Other')
for i in range(1,6):s.cell(i,1,i)
c=BarChart();c.add_data(Reference(s,min_col=1,min_row=1,max_row=5));o.add_chart(c,'D2')
f=BytesIO();b.save(f);sys.stdout.buffer.write(f.getvalue())
`]))}
it.each(['default','alias'])('renames actual openpyxl chart with %s namespace and preserves other parts',async mode=>{
 let bytes:Uint8Array=fixture();const path='xl/charts/chart1.xml';let xml=await(await createBufferEntrySource(bytes)).readText(path)
 if(mode==='alias')xml=xml.replace(`xmlns="${uri}"`,`xmlns:q="${uri}"`).replace(/<(\/?)([A-Za-z][\w]*)(?=[\s/>])/g,'<$1q:$2')
 bytes=(await assemblePackage(bytes,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const result=await applySheetEdits(bytes,plan),before=await createBufferEntrySource(bytes),after=await createBufferEntrySource(result)
 expect(readChartFormulas(await after.readText(path))).toEqual(["'New & O''Brien'!$A$1:$A$5"])
 expect(await after.readText(path)).toBe(xml.replace("'Source'!$A$1:$A$5","'New &amp; O''Brien'!$A$1:$A$5"))
 for(const entry of ['xl/styles.xml','xl/worksheets/sheet2.xml','xl/drawings/drawing1.xml','xl/drawings/_rels/drawing1.xml.rels'])expect(await after.readText(entry)).toBe(await before.readText(entry))
})
it.each(['','q:'])('handles CDATA and escaped formula text under %s namespace',prefix=>{
 const xml=`<${prefix}root xmlns${prefix?':q':''}="${uri}" a="中文😀"><${prefix}f><![CDATA[IF(Source!A1<1,]]>Source!B1&amp;"x")</${prefix}f><${prefix}f>&quot;Source!A1&quot;</${prefix}f></${prefix}root>`
 const result=renameSheetReferencesInChart(xml,'Source',"New & O'Brien")
 expect(readChartFormulas(result)).toEqual(["IF('New & O''Brien'!A1<1,'New & O''Brien'!B1&\"x\")",'"Source!A1"'])
 expect(result).toContain(`<${prefix}f>&quot;Source!A1&quot;</${prefix}f>`)
 expect(result).toContain('a="中文😀"')
})
it('preserves foreign c:f and rebound prefixes exactly',()=>{
 const foreign='<c:root xmlns:c="urn:foreign"><c:f>Source!A1</c:f></c:root>'
 expect(renameSheetReferencesInChart(foreign,'Source','New')).toBe(foreign)
 const scoped=`<q:root xmlns:q="${uri}"><q:f>Source!A1</q:f><n xmlns:q="urn:foreign"><q:f>Source!B1</q:f></n></q:root>`
 expect(renameSheetReferencesInChart(scoped,'Source','New')).toBe(scoped.replace('Source!A1','New!A1'))
})
it.each(['<c:root><c:f>Source!A1</c:f></c:root>',`<root xmlns="${uri}"><f>Source!A1</root>`])('rejects malformed chart XML before returning edits',xml=>{
 expect(()=>renameSheetReferencesInChart(xml,'Source','New')).toThrow()
})
it('preserves external references, formula literals, entities and empty formulas byte for byte',()=>{
 const xml=`<root xmlns="${uri}"><f/><f><![CDATA[[book.xlsx]Source!A1]]></f><f>&quot;Source!A1&quot;</f><f>Other!A1&lt;2</f></root>`
 expect(renameSheetReferencesInChart(xml,'Source','New')).toBe(xml)
})
it('handles c:f attributes, scoped default bindings, numeric entities and multiple changed formulas',()=>{
 const xml=`<?xml version="1.0"?><c:root xmlns:c="${uri}"><!--中文😀--><c:f xml:space="preserve">&#83;ource!A1</c:f><x xmlns="${uri}"><f>Source!B1</f><y xmlns="urn:foreign"><f>Source!C1</f></y></x><c:f/></c:root>`
 const result=renameSheetReferencesInChart(xml,'Source','New')
 expect(result).toBe(xml.replace('&#83;ource!A1','New!A1').replace('Source!B1','New!B1'))
})
it('rejects nested markup inside a formula without rewriting the chart',()=>{
 expect(()=>renameSheetReferencesInChart(`<root xmlns="${uri}"><f>Source!A1<x/></f></root>`,'Source','New')).toThrow('嵌套')
})
