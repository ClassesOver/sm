import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { buildPivotLayout } from '@sheets-web/xlsx-engine/pivot-layout'
import { assemblePackage } from '@sheets-web/xlsx-engine/zip'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, editPivotPlan, readWorkbookPivots, refreshWorkbookPivotsPlan } from './workbook-pivot'

const cases = [['percentOfParentRow', .2, .25], ['percentOfParentCol', 1/3, 1/3], ['index', .25, 5/6]] as const
it('resets inherited percentage cell styles when index has no explicit number format',async()=>{
 const input=await applyCellEdits(await createBlankWorkbook(),[['Region','Amount'],['East',10],['West',20]].flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
 const config={name:'Report',sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Region'],columnFields:[],values:[{field:'Amount',agg:'sum' as const,showDataAs:'percentOfParentRow' as const}]}
 const percent=await applyWorkbookOperations(input,(await createPivotPlan(input,config)).operations),pivot=(await readWorkbookPivots(percent))[0]!
 const changed=await applyWorkbookOperations(percent,(await editPivotPlan(percent,pivot.tablePath,{...config,values:[{field:'Amount',agg:'sum',showDataAs:'index'}]})).operations)
 const model=await readWorkbook(changed),cell=model.sheets[0]!.cells.E2!
 expect(cell.value).toBe(1)
 expect(model.styles.cellXfs[cell.styleIndex??0]!.numFmtId).toBe(0)
})
it.each(cases)('calculates %s against the actual parent scope, with source number format defaults', (showDataAs, expected) => {
  const layout=buildPivotLayout([['Region','Team','Year','Quarter','Amount'],['East','A','2025','Q1',10],['East','A','2025','Q2',20],['East','A','2026','Q1',30],['East','B','2025','Q1',40],['West','A','2025','Q1',50]],{
    rowFields:['Region','Team'],columnField:['Year','Quarter'],values:[{field:'Amount',agg:'sum',showDataAs}],
  })
  expect(layout.matrix.find(row=>row[0]==='East'&&row[1]==='A')![2]).toBeCloseTo(expected)
  expect(layout.definition.values[0]!.numFmt).toBe(showDataAs==='index'?undefined:'0.00%')
  const explicit=buildPivotLayout([['Region','Amount'],['East',10]],{rowFields:'Region',values:[{field:'Amount',agg:'sum',showDataAs,numFmt:'0.00'}]})
  expect(explicit.definition.values[0]!.numFmt).toBe('0.00')
  const zero=buildPivotLayout([['Region','Amount'],['East',0]],{rowFields:'Region',values:[{field:'Amount',agg:'sum',showDataAs}]})
  expect(zero.matrix[1]![1]).toBeNull()
})

it.each(cases)('persists and refreshes %s through owned and foreign OOXML with the correct format', async (showDataAs, _expected, simple) => {
  const rows=[['Region','Category','Amount'],['East','X',10],['East','Y',20],['West','X',30],['West','Y',40]]
  const input=await applyCellEdits(await createBlankWorkbook(),rows.flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
  const config={name:'Report',sourceSheetName:'Sheet1',sourceRange:'A1:C5',targetSheetName:'Sheet1',targetCell:'E1',rowFields:['Region'],columnFields:['Category'],values:[{field:'Amount',agg:'sum' as const,showDataAs}]}
  const saved=await applyWorkbookOperations(input,(await createPivotPlan(input,config)).operations),pivot=(await readWorkbookPivots(saved))[0]!,entries=await createBufferEntrySource(saved),xml=await entries.readText(pivot.tablePath)
  expect(pivot.values[0]!.showDataAs).toBe(showDataAs)
  expect((await readWorkbook(saved)).sheets[0]!.cells.F2!.value).toBeCloseTo(simple)
  const field=xml.match(/<dataField\b[^>]*(?:\/>|>[\s\S]*?<\/dataField>)/)![0]
  if(showDataAs==='index')expect(field).toContain('showDataAs="index"')
  else {
    expect(field).not.toMatch(/\sshowDataAs=/)
    expect(field).toContain(`pivotShowAs="${showDataAs}"`)
    expect(field).toContain('{E15A36E0-9728-4E99-A89B-3F7291B0FE68}')
    expect(field).not.toContain(`showDataAs="${showDataAs}"`)
  }
  if(showDataAs==='index')expect(field).not.toContain('numFmtId=')
  else expect(field).toContain('numFmtId="10"')
  const foreign=(await assemblePackage(saved,{replaced:new Map([[pivot.tablePath,xml.replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[pivot.tablePath]})).buffer
  const imported=(await readWorkbookPivots(foreign))[0]!
  expect(imported.readonlyReason).toBeUndefined()
  expect(imported.values[0]!.showDataAs).toBe(showDataAs)
  const refreshed=await applyWorkbookOperations(foreign,(await refreshWorkbookPivotsPlan(foreign)).operations)
  expect((await readWorkbook(refreshed)).sheets[0]!.cells.F2!.value).toBeCloseTo(simple)
})
