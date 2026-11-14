import { expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/index'
import { assemblePackage } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/zip'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { PivotAddError } from '@sheets-web/xlsx-engine/pivot-add'
import { createPivotPlan, readWorkbookPivots, refreshWorkbookPivotsPlan } from './workbook-pivot'

const config = { name:'区域分析',sourceSheetName:'Sheet1',sourceRange:'A1:B5',targetSheetName:'Sheet1',targetCell:'E1',rowFields:['区域'],columnFields:[],values:[{field:'收入',agg:'sum' as const}] }
it('rewrites actual output in an imported multi-sheet package with absolute pivot cache targets',async()=>{
 const bytes=new Uint8Array(readFileSync('smoke/fixtures/pivot-refresh-import.xlsx')),pivots=await readWorkbookPivots(bytes)
 expect(pivots[0]!.targetSheetName).toBe('Pivot');expect(pivots[0]!.worksheetPath).toBe('xl/worksheets/sheet2.xml')
 const draft=await applyCellEdits(bytes,[{sheetName:'Data',row:1,column:1,writeValue:true,cell:{value:90}},{sheetName:'Data',row:2,column:0,writeValue:true,cell:{value:'South'}}])
 const result=await applyWorkbookOperations(draft,(await refreshWorkbookPivotsPlan(draft)).operations),after=(await readWorkbookPivots(result))[0]!,book=await readWorkbook(result),cells=book.sheets.find(sheet=>sheet.name==='Pivot')!.cells
 expect(after.location.endRow).toBe(4);expect(cells.B5?.value).toBe(180)
 expect(cells.A3?.value).toBe('South');expect(book.sheets.find(sheet=>sheet.name==='Data')!.cells.B2?.value).toBe(90)
})
it('rejects unresolved cache targets and missing records without returning a successful no-op',async()=>{
 const bytes=new Uint8Array(readFileSync('smoke/fixtures/pivot-refresh-import.xlsx')),zip=await createBufferEntrySource(bytes),path='xl/pivotTables/_rels/pivotTable1.xml.rels'
 const missing=(await assemblePackage(bytes,{replaced:new Map([[path,(await zip.readText(path)).replace('pivotCacheDefinition1.xml','missing.xml')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 await expect(refreshWorkbookPivotsPlan(missing)).rejects.toThrow()
 const valid=await refreshWorkbookPivotsPlan(bytes),operation=valid.operations[0]!
 if(operation.kind!=='applyPivotLayoutExpansions')throw new Error('Expected pivot layout refresh')
 const updates=operation.updates as readonly import('../../../reporting/workbook_engine/packages/xlsx-engine/src/pivot-expand').PivotRefreshUpdate[]
 await expect(applyWorkbookOperations(bytes,[{...operation,updates:updates.map(update=>({...update,cachePath:'xl/pivotCache/missing.xml'}))}])).rejects.toBeInstanceOf(PivotAddError)
 const cache='xl/pivotCache/pivotCacheDefinition1.xml',noRecords=(await assemblePackage(bytes,{replaced:new Map([[cache,(await zip.readText(cache)).replace(/ r:id="[^"]+"/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[cache]})).buffer,snapshot=noRecords.slice()
 await expect(refreshWorkbookPivotsPlan(noRecords)).rejects.toThrow('records relationship')
 expect(noRecords).toEqual(snapshot)
})
async function fixture(){
 const rows=[['区域','收入'],['华东',10],['华东',20],['华西',30],['华西',40]]
 const original=await applyCellEdits(await createBlankWorkbook(),rows.flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value}}))))
 return applyWorkbookOperations(original,(await createPivotPlan(original,config)).operations)
}
it('refreshes actual output and records from the current draft, growing persisted location',async()=>{
 const created=await fixture(),before=(await readWorkbookPivots(created))[0]!
 const draft=await applyCellEdits(created,[{sheetName:'Sheet1',row:1,column:1,writeValue:true,cell:{value:90}},{sheetName:'Sheet1',row:2,column:0,writeValue:true,cell:{value:'华南'}}]),snapshot=draft.slice()
 const plan=await refreshWorkbookPivotsPlan(draft),result=await applyWorkbookOperations(draft,plan.operations),after=(await readWorkbookPivots(result))[0]!
 expect(plan.count).toBe(1);expect(draft).toEqual(snapshot)
 expect(after.location.endRow).toBeGreaterThan(before.location.endRow)
 expect(after.tablePath).toBe(before.tablePath);expect(after.cachePath).toBe(before.cachePath)
 const cells=(await readWorkbook(result)).sheets[0]!.cells
 expect(Object.values(cells).some(cell=>cell.value===180)).toBe(true)
 expect(Object.values(cells).some(cell=>cell.value==='华南')).toBe(true)
 expect(await (await createBufferEntrySource(result)).readText(after.cachePath)).toContain('recordCount="4"')
 expect(await (await createBufferEntrySource(result)).readText('xl/pivotCache/pivotCacheRecords1.xml')).toContain('<n v="90"/>')
})
it('clears the old visible tail when categories shrink',async()=>{
 const original=await fixture(),before=(await readWorkbookPivots(original))[0]!
 const draft=await applyCellEdits(original,[3,4].map(row=>({sheetName:'Sheet1',row,column:0,writeValue:true,cell:{value:'华东'}})))
 const result=await applyWorkbookOperations(draft,(await refreshWorkbookPivotsPlan(draft)).operations),after=(await readWorkbookPivots(result))[0]!,cells=(await readWorkbook(result)).sheets[0]!.cells
 expect(after.location.endRow).toBeLessThan(before.location.endRow)
 for(let row=after.location.endRow+1;row<=before.location.endRow;row++)expect(cells[`E${row+1}`]?.value??null).toBeNull()
})
it('refreshes imported OOXML actual output without refreshOnLoad',async()=>{
 const bytes=await fixture(),pivot=(await readWorkbookPivots(bytes))[0]!,zip=await createBufferEntrySource(bytes)
 const foreign=(await assemblePackage(bytes,{replaced:new Map([[pivot.tablePath,(await zip.readText(pivot.tablePath)).replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[pivot.tablePath]})).buffer
 const draft=await applyCellEdits(foreign,[{sheetName:'Sheet1',row:1,column:1,writeValue:true,cell:{value:110}}])
 const result=await applyWorkbookOperations(draft,(await refreshWorkbookPivotsPlan(draft)).operations)
 expect(Object.values((await readWorkbook(result)).sheets[0]!.cells).some(cell=>cell.value===200)).toBe(true)
 expect(await (await createBufferEntrySource(result)).readText(pivot.cachePath)).not.toContain('refreshOnLoad')
})
it('rejects unsupported pivots, occupied growth and empty workbooks atomically',async()=>{
 await expect(refreshWorkbookPivotsPlan(await createBlankWorkbook())).rejects.toThrow('没有可刷新')
 const bytes=await fixture(),pivot=(await readWorkbookPivots(bytes))[0]!,zip=await createBufferEntrySource(bytes)
 const unsupported=(await assemblePackage(bytes,{replaced:new Map([[pivot.tablePath,(await zip.readText(pivot.tablePath)).replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/,'').replace('</pivotTableDefinition>','<pageFields count="1"/></pivotTableDefinition>')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[pivot.tablePath]})).buffer,snapshot=unsupported.slice()
 await expect(refreshWorkbookPivotsPlan(unsupported)).rejects.toThrow('无法刷新')
 expect(unsupported).toEqual(snapshot)
 const occupied=await applyCellEdits(bytes,[{sheetName:'Sheet1',row:2,column:0,writeValue:true,cell:{value:'华南'}},{sheetName:'Sheet1',row:pivot.location.endRow+1,column:4,writeValue:true,cell:{value:'人工备注'}}])
 await expect(refreshWorkbookPivotsPlan(occupied)).rejects.toThrow()
})
it('refreshes every independent pivot and does not submit a successful prefix when a later pivot fails',async()=>{
 const first=await fixture(),secondConfig={...config,name:'第二分析',targetCell:'I1'}
 const both=await applyWorkbookOperations(first,(await createPivotPlan(first,secondConfig)).operations)
 const draft=await applyCellEdits(both,[{sheetName:'Sheet1',row:1,column:1,writeValue:true,cell:{value:110}}])
 const plan=await refreshWorkbookPivotsPlan(draft),result=await applyWorkbookOperations(draft,plan.operations)
 expect(plan.count).toBe(2);expect(plan.operations).toHaveLength(2)
 const cells=(await readWorkbook(result)).sheets[0]!.cells
 expect(cells.F4?.value).toBe(200);expect(cells.J4?.value).toBe(200)
 const pivots=await readWorkbookPivots(both),occupied=await applyCellEdits(both,[{sheetName:'Sheet1',row:2,column:0,writeValue:true,cell:{value:'华南'}},{sheetName:'Sheet1',row:pivots[1]!.location.endRow+1,column:8,writeValue:true,cell:{value:'第二表下方备注'}}]),snapshot=occupied.slice()
 await expect(refreshWorkbookPivotsPlan(occupied)).rejects.toThrow()
 expect(occupied).toEqual(snapshot)
})
it.each([true,false,'shared'] as const)('rejects formula sources even with a potentially stale cached result: %s',async cached=>{
 const bytes=await fixture(),zip=await createBufferEntrySource(bytes),path='xl/worksheets/sheet1.xml'
 let xml=(await zip.readText(path)).replace(/<c\b[^>]*\br="B2"[^>]*>[\s\S]*?<\/c>/,`<c r="B2">${cached==='shared'?'<f t="shared" si="0"/>':'<f>B3+80</f>'}${cached?'<v>90</v>':''}</c>`)
 // A real shared follower needs a master. Keep it outside the source area
 // so this case tests cache freshness rather than malformed-group rejection.
 if(cached==='shared')xml=xml.replace('</row>','<c r="X1"><f t="shared" si="0">Z1+80</f><v>90</v></c></row>')
 const formula=(await assemblePackage(bytes,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer,snapshot=formula.slice()
 await expect(refreshWorkbookPivotsPlan(formula)).rejects.toThrow('当前入口无法确认公式结果为最新值，请先将来源计算结果转换为值')
 expect(formula).toEqual(snapshot)
})
it('preflights every pivot source before returning a plan when only a later source has formulas',async()=>{
 const first=await fixture(),extra=await applyCellEdits(first,[{sheetName:'Sheet1',row:0,column:12,writeValue:true,cell:{value:'区域'}},{sheetName:'Sheet1',row:0,column:13,writeValue:true,cell:{value:'收入'}},{sheetName:'Sheet1',row:1,column:12,writeValue:true,cell:{value:'华东'}},{sheetName:'Sheet1',row:1,column:13,writeValue:true,cell:{value:20}}])
 const both=await applyWorkbookOperations(extra,(await createPivotPlan(extra,{...config,name:'后表',sourceRange:'M1:N2',targetCell:'I1'})).operations),zip=await createBufferEntrySource(both),path='xl/worksheets/sheet1.xml'
 const formula=(await assemblePackage(both,{replaced:new Map([[path,(await zip.readText(path)).replace(/<c\b[^>]*\br="N2"[^>]*>[\s\S]*?<\/c>/,'<c r="N2"><f>B2*2</f><v>20</v></c>')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer,snapshot=formula.slice()
 await expect(refreshWorkbookPivotsPlan(formula)).rejects.toThrow('当前入口无法确认公式结果为最新值')
 expect(formula).toEqual(snapshot)
})
