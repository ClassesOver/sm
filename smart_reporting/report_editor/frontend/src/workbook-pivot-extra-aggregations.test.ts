import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage } from '@sheets-web/xlsx-engine/zip'
import { readPivotState } from '@sheets-web/xlsx-engine/pivot-add'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, editPivotPlan, readWorkbookPivots, refreshWorkbookPivotsPlan } from './workbook-pivot'

const cases = [
  ['product', 8, 32], ['countNums', 2, 2], ['stdDev', Math.sqrt(2), Math.sqrt(8)],
  ['stdDevp', 1, 2], ['var', 2, 8], ['varp', 1, 4],
] as const
async function source() {
  return applyCellEdits(await createBlankWorkbook(), [['Region', 'Amount'], ['East', 2], ['East', 4], ['West', 5]].flatMap((row, r) => row.map((value, column) => ({ sheetName: 'Sheet1', row: r, column, writeValue: true, cell: { value } }))))
}
it.each(cases)('creates, imports, refreshes and edits actual %s pivot OOXML', async (agg, expected, refreshed) => {
  const input = await source(), config = { name: 'Report', sourceSheetName: 'Sheet1', sourceRange: 'A1:B4', targetSheetName: 'Sheet1', targetCell: 'D1', rowFields: ['Region'], columnFields: [], values: [{ field: 'Amount', agg }] }
  const saved = await applyWorkbookOperations(input, (await createPivotPlan(input, config)).operations)
  const pivot = (await readWorkbookPivots(saved))[0]!, entries = await createBufferEntrySource(saved), xml = await entries.readText(pivot.tablePath)
  expect(pivot.readonlyReason).toBeUndefined()
  expect(pivot.values[0]!.agg).toBe(agg)
  expect(readPivotState(xml)!.values[0]!.agg).toBe(agg)
  expect(xml).toContain(`subtotal="${agg}"`)
  expect((await readWorkbook(saved)).sheets[0]!.cells.E2!.value).toBeCloseTo(expected)
  // Strip local metadata to exercise the foreign OOXML reader, not our state.
  const foreign = (await assemblePackage(saved, { replaced: new Map([[pivot.tablePath, xml.replace(/<ext uri="\{AIO-PIVOT-STATE\}"[\s\S]*?<\/ext>/, '')]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [pivot.tablePath] })).buffer
  expect(readPivotState(await (await createBufferEntrySource(foreign)).readText(pivot.tablePath))).toBeUndefined()
  const imported = (await readWorkbookPivots(foreign))[0]!
  expect(imported.readonlyReason).toBeUndefined()
  expect(imported.values[0]!.agg).toBe(agg)
  const changed = await applyCellEdits(foreign, [{ sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 8 } }])
  const output = await applyWorkbookOperations(changed, (await refreshWorkbookPivotsPlan(changed)).operations)
  expect((await readWorkbook(output)).sheets[0]!.cells.E2!.value).toBeCloseTo(refreshed)
  const edited = await applyWorkbookOperations(output, (await editPivotPlan(output, pivot.tablePath, { ...imported, values: [{ field: 'Amount', agg: 'sum' }] })).operations)
  expect((await readWorkbookPivots(edited))[0]!.values[0]!.agg).toBe('sum')
  expect((await readWorkbook(edited)).sheets[0]!.cells.E2!.value).toBe(12)
})
