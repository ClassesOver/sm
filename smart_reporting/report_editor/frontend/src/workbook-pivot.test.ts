import { assemblePackage } from '@sheets-web/xlsx-engine/zip'
import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, editPivotPlan, readWorkbookPivots } from './workbook-pivot'

async function source() {
  const rows = [['区域','团队','年份','收入','数量'],['华东','A',2025,10,2],['华东','A',2026,20,4],['华东','B',2025,30,6],['华西','A',2026,40,8]]
  return applyCellEdits(await createBlankWorkbook(), rows.flatMap((row,r) => row.map((value,c) => ({ sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value} }))))
}
const config = { name:'区域分析',sourceSheetName:'Sheet1',sourceRange:'A1:E5',targetSheetName:'Sheet1',targetCell:'H1',rowFields:['区域','团队'],columnFields:['年份'],values:[{field:'收入',agg:'sum' as const}] }
it('creates a real multi-level multi-value pivot package with cache records and visible output', async () => {
  const original=await source(), plan=await createPivotPlan(original,config)
  expect(plan.operation.kind).toBe('addPivot')
  const edited=await applyWorkbookOperations(original,[plan.operation]), pivots=await readWorkbookPivots(edited)
  expect(pivots).toHaveLength(1);expect(pivots[0]).toMatchObject({name:'区域分析',sourceSheetName:'Sheet1',rowFields:['区域','团队'],columnFields:['年份'],values:[{field:'收入',agg:'sum'}]})
  const zip=await createBufferEntrySource(edited), paths=await zip.paths()
  expect(paths.filter(path=>/^xl\/pivotTables\/pivotTable\d+\.xml$/.test(path))).toHaveLength(1)
  expect(await zip.readText(pivots[0]!.tablePath)).toContain('pivotTableDefinition')
  expect(await zip.readText(pivots[0]!.cachePath)).toContain('recordCount="4"')
  expect(await zip.readText(paths.find(path=>/^xl\/pivotCache\/pivotCacheRecords\d+\.xml$/.test(path))!)).toContain('count="4"')
  expect((await readWorkbook(edited)).sheets[0]!.cells.H1).toBeDefined()
  expect((await readWorkbook(original)).sheets[0]!.cells.H1).toBeUndefined()
})
it('edits layout and aggregation in place, retaining the pivot identity and rebuilding cache/output', async () => {
  const original=await source(), created=await applyWorkbookOperations(original,[(await createPivotPlan(original,config)).operation]), before=(await readWorkbookPivots(created))[0]!
  const next={...config,rowFields:['区域'],columnFields:[],values:[{field:'收入',agg:'average' as const},{field:'数量',agg:'count' as const},{field:'收入',agg:'max' as const},{field:'收入',agg:'min' as const}]}
  const plan=await editPivotPlan(created,before.tablePath,next), edited=await applyWorkbookOperations(created,plan.operations), after=(await readWorkbookPivots(edited))[0]!
  expect(after).toMatchObject({name:before.name,tablePath:before.tablePath,cachePath:before.cachePath,rowFields:['区域'],columnFields:[],values:next.values})
  const zip=await createBufferEntrySource(edited),xml=await zip.readText(after.tablePath)
  expect(xml).toContain('subtotal="average"');expect(xml).toContain('subtotal="count"');expect(xml).toContain('subtotal="max"');expect(xml).toContain('subtotal="min"')
  expect(Object.values((await readWorkbook(edited)).sheets[0]!.cells).some(cell=>cell.value===25)).toBe(true)
})
it('rejects invalid headers, occupied output and moving an existing pivot without changing source bytes', async () => {
  const original=await source(), snapshot=original.slice()
  await expect(createPivotPlan(original,{...config,targetCell:'A1'})).rejects.toThrow()
  await expect(createPivotPlan(original,{...config,rowFields:['不存在']})).rejects.toThrow()
  expect(original).toEqual(snapshot)
  const created=await applyWorkbookOperations(original,[(await createPivotPlan(original,config)).operation]),pivot=(await readWorkbookPivots(created))[0]!
  await expect(editPivotPlan(created,pivot.tablePath,{...config,targetCell:'Z10'})).rejects.toThrow()
})

it('edits standard imported OOXML without private state, rebuilding records and clearing the old tail',async()=>{
 const bytes=await source(),created=await applyWorkbookOperations(bytes,[(await createPivotPlan(bytes,config)).operation]),pivot=(await readWorkbookPivots(created))[0]!
 const zip=await createBufferEntrySource(created),xml=await zip.readText(pivot.tablePath)
 const foreign=(await assemblePackage(created,{replaced:new Map([[pivot.tablePath,xml.replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[pivot.tablePath]})).buffer
 const imported=(await readWorkbookPivots(foreign))[0]!
 expect(imported.rowFields).toEqual(['区域','团队']);expect(imported.columnFields).toEqual(['年份'])
 const plan=await editPivotPlan(foreign,pivot.tablePath,{...config,rowFields:['区域'],columnFields:[],values:[{field:'收入',agg:'average'}]})
 const result=await applyWorkbookOperations(foreign,plan.operations),output=(await readWorkbook(result)).sheets[0]!,after=(await readWorkbookPivots(result))[0]!,finalZip=await createBufferEntrySource(result)
 expect(after.tablePath).toBe(pivot.tablePath);expect(after.cachePath).toBe(pivot.cachePath)
 expect(await finalZip.readText(after.cachePath)).toContain('recordCount="4"')
 expect(Object.values(output.cells).some(cell=>cell.value===25)).toBe(true)
 for(let row=after.location.endRow+1;row<=pivot.location.endRow;row++)for(let column=pivot.location.startColumn;column<=pivot.location.endColumn;column++)expect(output.cells[String.fromCharCode(65+column)+(row+1)]?.value??null).toBeNull()
})
it('persists multiple values beneath a column axis with a values pseudo-field',async()=>{
 const bytes=await source(), next={...config,rowFields:['区域'],values:[{field:'收入',agg:'sum' as const},{field:'数量',agg:'count' as const}]}
 const result=await applyWorkbookOperations(bytes,(await createPivotPlan(bytes,next)).operations),pivot=(await readWorkbookPivots(result))[0]!
 expect(pivot.values).toEqual(next.values)
 const xml=await (await createBufferEntrySource(result)).readText(pivot.tablePath)
 expect(xml).toContain('<field x="-2"/>')
 expect(xml).toContain('<colFields count="2">')
 expect(xml).toContain('<colItems count="6">')
 const output=(await readWorkbook(result)).sheets[0]!.cells
 expect(['I3','J3','K3','L3','M3','N3'].map(address=>output[address]?.value)).toEqual([40,2,20,1,60,3])
 expect(Object.values((await readWorkbook(result)).sheets[0]!.cells).some(cell=>cell.value===100)).toBe(true)
})
it('persists multiple ordered column levels using the existing engine',async()=>{
 const bytes=await source(),next={...config,rowFields:['区域'],columnFields:['年份','团队']},plan=await createPivotPlan(bytes,next)
 const result=await applyWorkbookOperations(bytes,plan.operations),pivot=(await readWorkbookPivots(result))[0]!
 expect(pivot.columnFields).toEqual(['年份','团队']);expect(pivot.rowFields).toEqual(['区域'])
 expect(Object.values((await readWorkbook(result)).sheets[0]!.cells).some(cell=>cell.value===100)).toBe(true)
})
it('rejects duplicate source headers and unsupported number format without changing the workbook',async()=>{
 const bytes=await source(),duplicate=await applyCellEdits(bytes,[{sheetName:'Sheet1',row:0,column:1,writeValue:true,cell:{value:'区域'}}])
 await expect(createPivotPlan(duplicate,config)).rejects.toThrow('unique')
 await expect(createPivotPlan(bytes,{...config,values:[{field:'收入',agg:'sum',numFmt:'some made up format'}]})).rejects.toThrow('数字格式')
})

it('binds the relationship prefix when creating a pivot in a worksheet without xmlns:r',async()=>{
 const bytes=await source(),zip=await createBufferEntrySource(bytes),path='xl/worksheets/sheet1.xml'
 const ordinary=(await assemblePackage(bytes,{replaced:new Map([[path,(await zip.readText(path)).replace(/ xmlns:r="[^"]+"/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const result=await applyWorkbookOperations(ordinary,(await createPivotPlan(ordinary,config)).operations),xml=await (await createBufferEntrySource(result)).readText(path)
 expect(xml.match(/<worksheet\b[^>]*>/)?.[0]).toContain('xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
 expect(xml).toContain('<pivotTablePart r:id=')
})

it('preserves calculated values, numeric grouping and label filters through editing and refresh',async()=>{
 const bytes=await source(), advanced={...config,rowFields:['年份'],columnFields:[],groupings:[{field:'年份',kind:'range' as const,rangeStep:2,rangeStart:2025}],filters:[{kind:'label' as const,field:'年份',op:'equal' as const,value:'2025-2027'}],values:[{field:'单价',agg:'sum' as const,formula:'收入/数量'}]}
 const result=await applyWorkbookOperations(bytes,(await createPivotPlan(bytes,advanced)).operations),pivot=(await readWorkbookPivots(result))[0]!
 expect(pivot.readonlyReason).toBeUndefined()
 expect(pivot).toMatchObject({groupings:advanced.groupings,filters:advanced.filters,values:advanced.values})
 const edited=await applyWorkbookOperations(result,(await editPivotPlan(result,pivot.tablePath,pivot)).operations)
 const zip=await createBufferEntrySource(edited)
 expect(await zip.readText(pivot.cachePath)).toContain('databaseField="0"')
 expect(Object.values((await readWorkbook(edited)).sheets[0]!.cells).some(cell=>cell.value===5)).toBe(true)
})

it('tracks a named Excel table when its data range grows',async()=>{
 const bytes=await source(),table={kind:'applyTableAdditions',additions:[{worksheetSheetName:'Sheet1',area:{startRow:0,startColumn:0,endRow:4,endColumn:4},name:'Sales',columnNames:['区域','团队','年份','收入','数量'],style:'TableStyleMedium4',bandedRows:true}]}
 const tabular=await applyWorkbookOperations(bytes,[table]),next={...config,rowFields:['区域'],columnFields:[],sourceTableName:'Sales'}
 const created=await applyWorkbookOperations(tabular,(await createPivotPlan(tabular,next)).operations),pivot=(await readWorkbookPivots(created))[0]!
 expect(pivot.sourceTableName).toBe('Sales')
 expect(await (await createBufferEntrySource(created)).readText(pivot.cachePath)).toContain('name="Sales"')
 const grown=await applyWorkbookOperations(created,[{kind:'applyCellEdits',edits:['华北','C',2026,50,10].map((value,column)=>({sheetName:'Sheet1',row:5,column,writeValue:true,cell:{value}}))},{kind:'applyTableEdits',edits:[{worksheetSheetName:'Sheet1',tableName:'Sales',area:{startRow:0,startColumn:0,endRow:5,endColumn:4}}]}])
 const {refreshWorkbookPivotsPlan}=await import('./workbook-pivot')
 const refreshed=await applyWorkbookOperations(grown,(await refreshWorkbookPivotsPlan(grown)).operations)
 expect((await readWorkbookPivots(refreshed))[0]!.sourceRange).toBe('A1:E6')
 expect(Object.values((await readWorkbook(refreshed)).sheets[0]!.cells).some(cell=>cell.value===150)).toBe(true)
})

it('persists a report filter on a non-axis source field and keeps all cache records',async()=>{
 const bytes=await source(),next={...config,rowFields:['区域'],columnFields:[],pageFilters:[{field:'团队',selected:['A']}]}
 const result=await applyWorkbookOperations(bytes,(await createPivotPlan(bytes,next)).operations),pivot=(await readWorkbookPivots(result))[0]!
 expect(pivot.pageFilters).toEqual(next.pageFilters)
 const zip=await createBufferEntrySource(result),xml=await zip.readText(pivot.tablePath)
 expect(xml).toContain('axis="axisPage"');expect(xml).toContain('<pageFields count="1">')
 expect(await zip.readText(pivot.cachePath)).toContain('recordCount="4"')
 expect(Object.values((await readWorkbook(result)).sheets[0]!.cells).some(cell=>cell.value===70)).toBe(true)
 const updated=await applyWorkbookOperations(result,(await editPivotPlan(result,pivot.tablePath,{...pivot,pageFilters:[{field:'团队',selected:['B']}]})).operations)
 expect((await readWorkbook(updated)).sheets[0]!.cells.I2?.value).toBe(30)
})

it('isolates a shared cache when reordering one pivot and leaves its sibling definitions unchanged',async()=>{
 const bytes=await source(),first=await applyWorkbookOperations(bytes,(await createPivotPlan(bytes,{...config,targetCell:'H1'})).operations)
 const both=await applyWorkbookOperations(first,(await createPivotPlan(first,{...config,name:'第二张',targetCell:'P1'})).operations),pivots=await readWorkbookPivots(both),zip=await createBufferEntrySource(both),a=pivots[0]!,b=pivots[1]!
 const relPath=b.tablePath.replace('/pivotTables/','/pivotTables/_rels/')+'.rels',rels=await zip.readText(relPath),xml=await zip.readText(b.tablePath),firstXml=await zip.readText(a.tablePath)
 const shared=(await assemblePackage(both,{replaced:new Map([[relPath,rels.replace(/pivotCacheDefinition2.xml/g,'pivotCacheDefinition1.xml')],[b.tablePath,xml.replace(/cacheId="\d+"/,firstXml.match(/cacheId="\d+"/)![0])]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[relPath,b.tablePath]})).buffer
 const before=await createBufferEntrySource(shared),target=(await readWorkbookPivots(shared))[1]!
 expect(target.readonlyReason).toBeUndefined()
 const result=await applyWorkbookOperations(shared,(await editPivotPlan(shared,target.tablePath,{...target,rowFields:['团队','区域']})).operations),after=await readWorkbookPivots(result),final=await createBufferEntrySource(result)
 expect(after.find(pivot=>pivot.tablePath===target.tablePath)!.rowFields).toEqual(['团队','区域'])
 expect(after[0]!.cachePath).not.toBe(after[1]!.cachePath)
 expect(await final.readText(a.tablePath)).toBe(await before.readText(a.tablePath))
 expect(await final.readText(a.cachePath)).toBe(await before.readText(a.cachePath))
})

it('keeps hidden members attached to their field when axes are reordered or removed',async()=>{
 const bytes=await source(),next={...config,rowFields:['区域','团队'],columnFields:[],hiddenMembers:{row:[[],['B']]},groupings:[{field:'区域',kind:'date' as const,dateUnit:'year' as const}]}
 const created=await applyWorkbookOperations(bytes,(await createPivotPlan(bytes,next)).operations),pivot=(await readWorkbookPivots(created))[0]!
 const swapped=await applyWorkbookOperations(created,(await editPivotPlan(created,pivot.tablePath,{...pivot,rowFields:['团队','区域']})).operations),reordered=(await readWorkbookPivots(swapped))[0]!
 expect(reordered.hiddenMembers?.row).toEqual([['B'],[]])
 expect(Object.values((await readWorkbook(swapped)).sheets[0]!.cells).some(cell=>cell.value===70)).toBe(true)
 const removed=await applyWorkbookOperations(swapped,(await editPivotPlan(swapped,reordered.tablePath,{...reordered,rowFields:['团队']})).operations),remaining=(await readWorkbookPivots(removed))[0]!
 expect(remaining.groupings??[]).toEqual([])
 expect(remaining.hiddenMembers?.row).toEqual([['B']])
})

it('groups numeric dates with the workbook 1904 epoch through save and refresh',async()=>{
 const bytes=await applyCellEdits(await source(),[0,366,0,366].map((value,index)=>({sheetName:'Sheet1',row:index+1,column:2,writeValue:true,cell:{value}}))),zip=await createBufferEntrySource(bytes),workbook=await zip.readText('xl/workbook.xml')
 const dated=(await assemblePackage(bytes,{replaced:new Map([['xl/workbook.xml',workbook.replace('</workbook>','<workbookPr date1904="1"/></workbook>')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:['xl/workbook.xml']})).buffer
 const next={...config,rowFields:['年份'],columnFields:[],groupings:[{field:'年份',kind:'date' as const,dateUnit:'year' as const}]}
 const result=await applyWorkbookOperations(dated,(await createPivotPlan(dated,next)).operations),pivot=(await readWorkbookPivots(result))[0]!
 expect((await readWorkbook(result)).sheets[0]!.cells.H2?.value).toBe('1904')
 const refreshed=await applyWorkbookOperations(result,(await editPivotPlan(result,pivot.tablePath,pivot)).operations)
 expect((await readWorkbook(refreshed)).sheets[0]!.cells.H2?.value).toBe('1904')
 expect(await (await createBufferEntrySource(refreshed)).readText(pivot.cachePath)).toContain('v="1904"')
})

it('persists manual member selection separately from recalculated label filter hidden items',async()=>{
 const bytes=await source(),next={...config,rowFields:['区域'],columnFields:[],filters:[{kind:'label' as const,field:'区域',op:'contains' as const,value:'华'}],hiddenMembers:{row:[['华西']]}}
 const created=await applyWorkbookOperations(bytes,(await createPivotPlan(bytes,next)).operations),pivot=(await readWorkbookPivots(created))[0]!
 expect(pivot.hiddenMembers?.row).toEqual([['华西']])
 const refreshed=await applyWorkbookOperations(created,(await editPivotPlan(created,pivot.tablePath,pivot)).operations),output=(await readWorkbook(refreshed)).sheets[0]!.cells
 expect((await readWorkbookPivots(refreshed))[0]!.hiddenMembers?.row).toEqual([['华西']])
 expect(output.I3?.value).toBe(60)
})

it('stores basic and advanced create/edit plans in the actual native draft JSON journal',async()=>{
 const {NativeDraft}=await import('./native-draft'),identity={documentId:'pivot-json',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}}
 for(const next of [config,{...config,rowFields:['年份'],columnFields:[],values:[{field:'单价',agg:'sum' as const,formula:'收入/数量'}],groupings:[{field:'年份',kind:'range' as const,rangeStep:10}],pageFilters:[{field:'团队',selected:['A']}]}]){
  const bytes=await source(),create=await createPivotPlan(bytes,next),draft=new NativeDraft(identity,localStorage)
  draft.setOperations(create.operations as import('./native-draft').NativeOperation[])
  expect(draft.operations).toEqual(create.operations)
  const created=await applyWorkbookOperations(bytes,create.operations),pivot=(await readWorkbookPivots(created))[0]!,edit=await editPivotPlan(created,pivot.tablePath,pivot)
  draft.setOperations([...create.operations,...edit.operations] as import('./native-draft').NativeOperation[])
  expect(new NativeDraft(identity,localStorage).operations).toEqual([...create.operations,...edit.operations])
 }
})
