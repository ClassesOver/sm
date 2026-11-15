import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage } from '@sheets-web/xlsx-engine/zip'
import { refreshPivotCaches } from '@sheets-web/xlsx-engine/pivot-refresh'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, readWorkbookPivots, refreshWorkbookPivotsPlan } from './workbook-pivot'

const cases=[['sum',5],['count',5],['countNums',2],['average',2.5],['product',6],['min',2],['max',3],['var',.5],['varp',.25],['stdDev',Math.sqrt(.5)],['stdDevp',.5]] as const
async function fixture(){
 const rows:(string|number|boolean|null)[][]=[['Region','Amount'],['East',true],['East',false],['East',2],['East','3'],['East','text'],['East',null],['East','']]
 return applyCellEdits(await createBlankWorkbook(),rows.flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
}
it.each(cases)('preserves mixed boolean source types and domain %s results through save/refresh',(async(agg,expected)=>{
 const input=await fixture(),config={name:'Report',sourceSheetName:'Sheet1',sourceRange:'A1:B8',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Region'],columnFields:[],values:[{field:'Amount',agg}]}
 const saved=await applyWorkbookOperations(input,(await createPivotPlan(input,config)).operations),model=await readWorkbook(saved)
 expect(model.sheets[0]!.cells.E2!.value).toBeCloseTo(expected)
 expect(model.sheets[0]!.cells.B2!.value).toBe(true);expect(model.sheets[0]!.cells.B3!.value).toBe(false)
 const records=await(await createBufferEntrySource(saved)).readText('xl/pivotCache/pivotCacheRecords1.xml')
 expect(records).toContain('<b v="1"/>');expect(records).toContain('<b v="0"/>')
 const refreshed=await applyWorkbookOperations(saved,(await refreshWorkbookPivotsPlan(saved)).operations)
 expect((await readWorkbook(refreshed)).sheets[0]!.cells.E2!.value).toBeCloseTo(expected)
}))

it('retains boolean record types in a cache-only refresh without owned metadata',async()=>{
 const input=await fixture(),saved=await applyWorkbookOperations(input,(await createPivotPlan(input,{name:'Report',sourceSheetName:'Sheet1',sourceRange:'A1:B8',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Region'],columnFields:[],values:[{field:'Amount',agg:'count'}]})).operations),pivot=(await readWorkbookPivots(saved))[0]!,source=await createBufferEntrySource(saved)
 const foreign=(await assemblePackage(saved,{replaced:new Map([[pivot.tablePath,(await source.readText(pivot.tablePath)).replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[pivot.tablePath]})).buffer
 const refreshed=await refreshPivotCaches(foreign),records=await(await createBufferEntrySource(refreshed)).readText('xl/pivotCache/pivotCacheRecords1.xml')
 expect(records).toContain('<b v="1"/>');expect(records).toContain('<b v="0"/>')
})
