import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage } from '@sheets-web/xlsx-engine/zip'
import { extractElements, sectionInner } from '@sheets-web/xlsx-engine/xml'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, readWorkbookPivots, refreshWorkbookPivotsPlan } from './workbook-pivot'
import { pivotPaneConfig, pivotPaneModel } from './workbook-pivot-pane'

const cases=[['percentOf',2],['difference',10],['percentDiff',1],['percentOfParent',.4],['runTotal',30],['percentOfRunningTotal',.6],['rankAscending',2],['rankDescending',1]] as const
it.each(['percentOf','percentOfParent'] as const)('preserves explicit General on %s through foreign import and refresh',async showDataAs=>{
 const input=await applyCellEdits(await createBlankWorkbook(),[['Region','Amount'],['East',10],['West',20]].flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
 const config={name:'Report',sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Region'],columnFields:[],values:[{field:'Amount',agg:'sum' as const,showDataAs,baseField:'Region',...(showDataAs==='percentOf'?{baseItem:'East'}:{}),numFmt:'General'}]}
 const saved=await applyWorkbookOperations(input,(await createPivotPlan(input,config)).operations),pivot=(await readWorkbookPivots(saved))[0]!,entries=await createBufferEntrySource(saved),xml=await entries.readText(pivot.tablePath)
 expect(xml.match(/<dataField\b[^>]*>/)![0]).toContain('numFmtId="0"')
 const foreign=(await assemblePackage(saved,{replaced:new Map([[pivot.tablePath,xml.replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[pivot.tablePath]})).buffer
 expect((await readWorkbookPivots(foreign))[0]!.values[0]!.numFmt).toBe('General')
 const refreshed=await applyWorkbookOperations(foreign,(await refreshWorkbookPivotsPlan(foreign)).operations),model=await readWorkbook(refreshed)
 expect(model.styles.cellXfs[model.sheets[0]!.cells.E2!.styleIndex??0]!.numFmtId).toBe(0)
})
it('accepts explicit General formatting for a non-percent mode',async()=>{
 const input=await applyCellEdits(await createBlankWorkbook(),[['Region','Amount'],['East',10],['West',20]].flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
 const config={name:'Report',sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Region'],columnFields:[],values:[{field:'Amount',agg:'sum' as const,showDataAs:'rankAscending' as const,baseField:'Region',numFmt:'General'}]}
 const saved=await applyWorkbookOperations(input,(await createPivotPlan(input,config)).operations),model=await readWorkbook(saved)
 expect(model.styles.cellXfs[model.sheets[0]!.cells.E2!.styleIndex??0]!.numFmtId).toBe(0)
 expect((await readWorkbookPivots(saved))[0]!.values[0]!.numFmt).toBe('General')
})
it.each(['runTotal','percentOfRunningTotal','difference'] as const)('preserves foreign permuted member order and base-item indirection for %s',async showDataAs=>{
 const input=await applyCellEdits(await createBlankWorkbook(),[['Region','Amount'],['X',10],['Y',20]].flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
 const config={name:'Report',sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Region'],columnFields:[],values:[{field:'Amount',agg:'sum' as const,showDataAs,baseField:'Region',...(showDataAs==='difference'?{baseItem:'X'}:{})}]}
 const saved=await applyWorkbookOperations(input,(await createPivotPlan(input,config)).operations),pivot=(await readWorkbookPivots(saved))[0]!,source=await createBufferEntrySource(saved),xml=await source.readText(pivot.tablePath)
 const field=extractElements(sectionInner(xml,'pivotFields')!,'pivotField')[0]!,permuted=field.replace(/\bx="([01])"/g,(_match,n:string)=>`x="${n==='0'?1:0}"`)
 const foreign=(await assemblePackage(saved,{replaced:new Map([[pivot.tablePath,xml.replace(field,permuted).replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[pivot.tablePath]})).buffer
 const imported=(await readWorkbookPivots(foreign))[0]!
 expect(imported.readonlyReason).toBeUndefined()
 if(showDataAs==='difference')expect(imported.values[0]!.baseItem).toBe('Y')
 const refreshed=await applyWorkbookOperations(foreign,(await refreshWorkbookPivotsPlan(foreign)).operations),cells=(await readWorkbook(refreshed)).sheets[0]!.cells
 expect(cells.D2!.value).toBe('Y');expect(cells.D3!.value).toBe('X')
 if(showDataAs==='difference'){expect(cells.E2?.value??null).toBeNull();expect(cells.E3!.value).toBe(-10)}
 else{expect(cells.E2!.value).toBeCloseTo(showDataAs==='runTotal'?20:2/3);expect(cells.E3!.value).toBe(showDataAs==='runTotal'?30:1)}
})
it.each(cases)('preserves %s base parameters through pane, owned/foreign save and refresh',async(showDataAs,expected)=>{
 const rows=[['Group','Item','Amount'],['G1','A',10],['G1','B',20],['G1','C',20]],fields=[{label:'Group',colIndex:0},{label:'Item',colIndex:1},{label:'Amount',colIndex:2,numeric:true}]
 const input=await applyCellEdits(await createBlankWorkbook(),rows.flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
 const needsItem=['percentOf','difference','percentDiff'].includes(showDataAs),config={name:'Report',sourceSheetName:'Sheet1',sourceRange:'A1:C4',targetSheetName:'Sheet1',targetCell:'E1',rowFields:['Group','Item'],columnFields:[],values:[{field:'Amount',agg:'sum' as const,showDataAs,baseField:'Item',...(needsItem?{baseItem:'A'}:{})}]}
 expect(pivotPaneConfig(config,fields,pivotPaneModel(config,fields)).values).toEqual(config.values)
 const saved=await applyWorkbookOperations(input,(await createPivotPlan(input,config)).operations),pivot=(await readWorkbookPivots(saved))[0]!,entries=await createBufferEntrySource(saved),xml=await entries.readText(pivot.tablePath)
 expect(pivot.values[0]).toMatchObject(config.values[0]!)
 expect((await readWorkbook(saved)).sheets[0]!.cells.G3!.value).toBeCloseTo(expected)
 expect(xml).toContain('baseField="1"')
 if(needsItem)expect(xml).toContain('baseItem="0"')
 const native=['percentOf','difference','percentDiff','runTotal'].includes(showDataAs)
 if(native)expect(xml).toContain(`showDataAs="${showDataAs==='percentOf'?'percent':showDataAs}"`)
 else expect(xml).toContain(`pivotShowAs="${showDataAs}"`)
 const foreign=(await assemblePackage(saved,{replaced:new Map([[pivot.tablePath,xml.replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[pivot.tablePath]})).buffer
 const imported=(await readWorkbookPivots(foreign))[0]!
 expect(imported.readonlyReason).toBeUndefined()
 expect(imported.values[0]).toMatchObject(config.values[0]!)
 const refreshed=await applyWorkbookOperations(foreign,(await refreshWorkbookPivotsPlan(foreign)).operations)
 expect((await readWorkbook(refreshed)).sheets[0]!.cells.G3!.value).toBeCloseTo(expected)
})
