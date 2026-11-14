import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, formatAddress, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotEntrySource } from '@sheets-web/xlsx-engine/pivot-source'
import { createPivotPlan, readWorkbookPivots } from './workbook-pivot'

it('computes and persists the five supported aggregations and three percent Show As modes', async () => {
  const rows = [['Region', 'Amount'], ['East', 10], ['East', 20], ['West', 30]]
  const source = await applyCellEdits(await createBlankWorkbook(), rows.flatMap((row, r) => row.map((value, column) => ({ sheetName: 'Sheet1', row: r, column, writeValue: true, cell: { value } }))))
  const aggs = ['sum', 'count', 'average', 'max', 'min'] as const
  for (const agg of aggs) {
    const plan = await createPivotPlan(source, { name: `P-${agg}`, sourceSheetName: 'Sheet1', sourceRange: 'A1:B4', targetSheetName: 'Sheet1', targetCell: 'D1', rowFields: ['Region'], columnFields: [], values: [{ field: 'Amount', agg }] })
    const saved = await applyWorkbookOperations(source, plan.operations)
    expect((await readWorkbookPivots(saved))[0]!.values[0]!.agg).toBe(agg)
    expect((await readWorkbook(saved)).sheets[0]!.cells[formatAddress(1, 4)]?.value).toBe(agg === 'count' ? 2 : agg === 'average' ? 15 : agg === 'max' ? 20 : agg === 'min' ? 10 : 30)
  }
  for (const showDataAs of ['percentOfTotal', 'percentOfRow', 'percentOfCol'] as const) {
    const plan = await createPivotPlan(source, { name: `P-${showDataAs}`, sourceSheetName: 'Sheet1', sourceRange: 'A1:B4', targetSheetName: 'Sheet1', targetCell: 'D1', rowFields: ['Region'], columnFields: [], values: [{ field: 'Amount', agg: 'sum', showDataAs }] })
    const saved = await applyWorkbookOperations(source, plan.operations)
    expect((await readWorkbookPivots(saved))[0]!.values[0]!.showDataAs).toBe(showDataAs)
    expect((await readWorkbook(saved)).sheets[0]!.cells.E2?.value).toBeCloseTo(showDataAs==='percentOfRow'?1:0.5)
    const entries=await createPivotEntrySource(saved),path=(await entries.paths()).find(path=>/^xl\/pivotTables\/[^/]+\.xml$/.test(path))!
    expect(await entries.readText(path)).toContain('showDataAs="'+showDataAs+'"')
  }
})
