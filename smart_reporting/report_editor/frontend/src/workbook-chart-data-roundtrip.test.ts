import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { chartAdditionFromGrid } from './workbook-chart-add'

it('keeps Select Data literal series readable after the existing writer replaces the complete series set', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Q1' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 7 } },
  ])
  const original = await applyWorkbookOperations(source, [{ kind: 'applyChartAdditions', additions: [chartAdditionFromGrid({ sheetName: 'Sheet1', chartType: 'column', range: { startRow: 0, endRow: 0, startColumn: 0, endColumn: 1 }, values: [['Q1', 7]] })] }])
  const chart = (await readWorkbook(original)).sheets[0]!.charts![0]!
  const saved = await applyWorkbookOperations(original, [{ kind: 'applyChartEdits', edits: [{ chartPath: chart.chartPath, seriesSet: [{ name: 'Literal', categories: ['A', 'B'], values: [10, 20] }] }] }])
  expect((await readWorkbook(saved)).sheets[0]!.charts![0]!.series).toMatchObject([{ name: 'Literal', valuesRef: '', categories: ['A', 'B'], values: [10, 20] }])
})
