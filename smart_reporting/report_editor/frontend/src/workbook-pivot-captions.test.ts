import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { buildPivotLayout } from '@sheets-web/xlsx-engine/pivot-layout'
import { readPivotState } from '@sheets-web/xlsx-engine/pivot-add'
import { assemblePackage } from '@sheets-web/xlsx-engine/zip'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, editPivotPlan, readWorkbookPivots, refreshWorkbookPivotsPlan } from './workbook-pivot'
import { pivotPaneConfig, pivotPaneModel } from './workbook-pivot-pane'

it('trims custom captions, applies source duplicate suffixes, and retains names in definition', () => {
  const layout = buildPivotLayout([['Region','Amount'],['East',2]], { rowFields:'Region', values:[{field:'Amount',agg:'sum',name:'  收入 & "净额"  '},{field:'Amount',agg:'countNums',name:'收入 & "净额"'},{field:'Amount',agg:'sum',name:'  '}] })
  expect(layout.matrix[0]).toEqual(['Region','收入 & "净额"','收入 & "净额"2','Sum of Amount'])
  expect(layout.definition.values.map(value=>value.name)).toEqual(['收入 & "净额"','收入 & "净额"2',undefined])
})

it('keeps custom captions through pane config, actual save, foreign import, refresh and reset', async () => {
  const input = await applyCellEdits(await createBlankWorkbook(), [['Region','Amount'],['East',2],['East',4]].flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
  const name='收入 & "净额" <本年>', config={name:'Report',sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Region'],columnFields:[],values:[{field:'Amount',agg:'sum' as const,name}]},fields=[{label:'Region',colIndex:0},{label:'Amount',colIndex:1,numeric:true}]
  expect(pivotPaneConfig(config,fields,pivotPaneModel(config,fields)).values).toEqual(config.values)
  const saved = await applyWorkbookOperations(input,(await createPivotPlan(input,config)).operations),pivot=(await readWorkbookPivots(saved))[0]!,entries=await createBufferEntrySource(saved),xml=await entries.readText(pivot.tablePath)
  expect(pivot.values[0]!.name).toBe(name)
  expect(readPivotState(xml)!.values[0]!.name).toBe(name)
  expect(xml).toContain('name="收入 &amp; &quot;净额&quot; &lt;本年&gt;"')
  expect((await readWorkbook(saved)).sheets[0]!.cells.E1!.value).toBe(name)
  const foreign=(await assemblePackage(saved,{replaced:new Map([[pivot.tablePath,xml.replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[pivot.tablePath]})).buffer
  expect((await readWorkbookPivots(foreign))[0]!.values[0]!.name).toBe(name)
  const refreshed=await applyWorkbookOperations(foreign,(await refreshWorkbookPivotsPlan(foreign)).operations)
  expect((await readWorkbook(refreshed)).sheets[0]!.cells.E1!.value).toBe(name)
  const regrouped=await applyWorkbookOperations(refreshed,(await editPivotPlan(refreshed,pivot.tablePath,{...config,values:[{field:'Amount',agg:'product',name}]})).operations)
  expect((await readWorkbook(regrouped)).sheets[0]!.cells.E1!.value).toBe(name)
  expect((await readWorkbook(regrouped)).sheets[0]!.cells.E2!.value).toBe(8)
  const restored=await applyWorkbookOperations(regrouped,(await editPivotPlan(regrouped,pivot.tablePath,{...config,values:[{field:'Amount',agg:'sum',name:'  '}]})).operations)
  expect((await readWorkbook(restored)).sheets[0]!.cells.E1!.value).toBe('Sum of Amount')
  expect((await readWorkbookPivots(restored))[0]!.values[0]!.name).toBeUndefined()
})
