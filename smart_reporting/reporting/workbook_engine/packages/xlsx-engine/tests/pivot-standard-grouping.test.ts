import { describe, expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, readWorkbook, type PivotAddition } from '../src'
import { addPivotTable, readPivotState } from '../src/pivot-add'
import { buildPivotLayout, pivotOutputArea } from '../src/pivot-layout'
import { refreshPivotCaches } from '../src/pivot-refresh'
import { createBufferEntrySource } from '../src/zip'
import { extractElements, sectionInner, readXmlAttribute } from '../src/xml'

async function fixture(values:(string|number|null)[],grouping:NonNullable<PivotAddition['groupings']>[number]){
 const grid=[['Dimension','Amount'],...values.map((value,index)=>[value,index+1])]
 const bytes=await applyCellEdits(await createBlankWorkbook(),grid.flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
 const {fieldIndex:_,...rule}=grouping,layout=buildPivotLayout(grid,{rowFields:['Dimension'],values:[{field:'Amount',agg:'sum'}],groupings:[{field:'Dimension',...rule}]})
 const addition:PivotAddition={worksheetSheetName:'Sheet1',sourceSheetName:'Sheet1',sourceArea:{startRow:0,startColumn:0,endRow:values.length,endColumn:1},location:pivotOutputArea({row:0,column:4},layout),name:'Grouped',fieldNames:layout.definition.fieldNames,rowFieldIndices:[0],rowLevelItems:layout.definition.rowLevelItems,rowLines:layout.definition.rowLines,values:layout.definition.values,groupings:layout.definition.groupings}
 return addPivotTable(bytes,addition)
}
async function parts(bytes:Uint8Array){const zip=await createBufferEntrySource(bytes);return {cache:await zip.readText('xl/pivotCache/pivotCacheDefinition1.xml'),table:await zip.readText('xl/pivotTables/pivotTable1.xml'),records:await zip.readText('xl/pivotCache/pivotCacheRecords1.xml')}}

describe('standard range grouping',()=>{
 it('keeps numeric source items and records separate from full group items and pivot indices',async()=>{
  const {cache,table,records}=await parts(await fixture([-1,0,9.9,10,20],{fieldIndex:0,kind:'range',rangeStep:10}))
  expect(cache).toContain('<fieldGroup base="0">')
  expect(cache).toContain('groupBy="range"')
  expect(cache).toContain('startNum="-10"');expect(cache).toContain('endNum="30"')
  const field=extractElements(sectionInner(cache,'cacheFields')!,'cacheField')[0]!
  expect(sectionInner(field,'sharedItems')).toContain('<n v="9.9"/>')
  expect(sectionInner(field,'sharedItems')).not.toContain('0-10')
  expect(sectionInner(field,'groupItems')).toContain('v="0-10"')
  expect(records).toContain('<r><x v="2"/><n v="3"/></r>')
  const pivot=extractElements(sectionInner(table,'pivotFields')!,'pivotField')[0]!
  expect(extractElements(sectionInner(pivot,'items')!,'item').slice(0,4).map(item=>readXmlAttribute(item,'x'))).toEqual(['1','2','3','4'])
 })
 it.each(['month','quarter','year'] as const)('writes complete %s date groups and raw date records',async dateUnit=>{
  const {cache,table,records}=await parts(await fixture([45717,46053,46112],{fieldIndex:0,kind:'date',dateUnit}))
  expect(cache).toContain('<fieldGroup base="0">')
  expect(cache).toContain(`groupBy="${dateUnit==='month'?'months':dateUnit==='quarter'?'quarters':'years'}"`)
  expect(cache).toContain('<d v="2025-03-01T00:00:00"/>')
  expect(cache).toContain(`groupItems count="${dateUnit==='month'?14:dateUnit==='quarter'?6:4}"`)
  expect(records).toContain('<r><x v="2"/><n v="3"/></r>')
  expect(readPivotState(table)?.groupingPersistence?.[0]).toMatchObject({fieldIndex:0,mode:'standard'})
 })
 it('retains explicit compatibility mode for blanks, invalid dates and text numeric fields',async()=>{
  for(const [values,rule] of [[['2026-02-31','2026-03-01'],{kind:'date',dateUnit:'month'}],[[null,10],{kind:'range',rangeStep:10}],[['10','20'],{kind:'range',rangeStep:10}]] as const){
   const {cache,table}=await parts(await fixture([...values],{fieldIndex:0,...rule}))
   expect(cache).not.toContain('<fieldGroup')
   expect(readPivotState(table)?.groupingPersistence?.[0]).toMatchObject({mode:'private',reason:expect.any(String)})
  }
 })
 it('rebuilds standard groups, raw cache records and visible output when grouped source values change',async()=>{
  const created=await fixture([1,9,10],{fieldIndex:0,kind:'range',rangeStep:10}),changed=await applyCellEdits(created,[{sheetName:'Sheet1',row:3,column:0,writeValue:true,cell:{value:20}}]),refreshed=await refreshPivotCaches(changed),{cache,records}=await parts(refreshed)
  expect(cache).toContain('<fieldGroup base="0">');expect(cache).toContain('<n v="20"/>')
  expect(cache).toContain('v="20-30"');expect(records).toContain('<r><x v="2"/><n v="3"/></r>')
  expect(Object.values((await readWorkbook(refreshed)).sheets[0]!.cells).some(cell=>cell.value==='20-30')).toBe(true)
 })
})

it('is independently read by openpyxl with raw numeric/date items, range properties and grouped pivot indices',async()=>{
 const {execFileSync}=await import('node:child_process'),{fileURLToPath}=await import('node:url')
 for(const [values,rule,groupBy] of [[[1,9.9,10,20],{kind:'range',rangeStep:10},'range'],[[45717,46053,46112],{kind:'date',dateUnit:'month'},'months']] as const){
  const bytes=await fixture([...values],{fieldIndex:0,...rule})
  const result=execFileSync(fileURLToPath(new URL('../../../../../../.venv/bin/python',import.meta.url)),['-c',`
from io import BytesIO
from openpyxl import load_workbook
from lxml import etree
import sys,json
book=load_workbook(BytesIO(sys.stdin.buffer.read()))
pivot=book.active._pivots[0]
cache=pivot.cache
field=cache.cacheFields[0]
assert field.fieldGroup.base==0
assert field.fieldGroup.rangePr.groupBy==sys.argv[1]
raw=list(field.sharedItems._fields)
groups=[item.v for item in field.fieldGroup.groupItems.s]
indices=[item.x for item in pivot.pivotFields[0].items if item.t=='data']
assert all(0<=index<len(groups) for index in indices)
assert len(raw)==4 if sys.argv[1]=='range' else len(raw)==3
assert all(isinstance(item.v,(int,float)) for item in raw) if sys.argv[1]=='range' else all(item.v.year>=2025 for item in raw)
assert [record._fields[0].v for record in cache.records.r]==list(range(len(raw)))
print(json.dumps({'groupBy':field.fieldGroup.rangePr.groupBy,'groups':groups,'rawCount':len(raw),'indices':indices}))
`,groupBy],{input:bytes,encoding:'utf8'})
  expect(JSON.parse(result)).toMatchObject({groupBy,rawCount:values.length})
 }
})
