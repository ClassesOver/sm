import { describe, expect, it } from 'vitest'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { chartAdditionFromGrid } from './workbook-chart-add'

describe('workbook chart insertion', () => {
  it('keeps numeric years as categories exactly like the recommendation preview', () => {
    const addition = chartAdditionFromGrid({ sheetName: 'Sheet1', chartType: 'line',
      range: { startRow: 0, endRow: 3, startColumn: 0, endColumn: 1 },
      values: [['Year', 'Sales'], [2023, 10], [2024, 20], [2025, 30]] })
    expect(addition.chart.series).toHaveLength(1)
    expect(addition.chart.series[0]).toMatchObject({ name: 'Sales', categories: ['2023', '2024', '2025'], values: [10, 20, 30],
      categoriesRef: "'Sheet1'!$A$2:$A$4", valuesRef: "'Sheet1'!$B$2:$B$4" })
  })
  it('maps selected tabular data to a chart addition and saves/reopens it', async () => {
    const addition = chartAdditionFromGrid({
      sheetName: 'Sales Data',
      chartType: 'column',
      title: 'Quarterly sales',
      range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 1 },
      values: [['Quarter', 'Sales'], ['Q1', 10], ['Q2', 20]],
    })
    expect(addition.chart.series[0]).toMatchObject({
      name: 'Sales', categories: ['Q1', 'Q2'], values: [10, 20],
      categoriesRef: "'Sales Data'!$A$2:$A$3", valuesRef: "'Sales Data'!$B$2:$B$3",
    })

    let bytes = await createBlankWorkbook('Sales Data')
    bytes = await applyWorkbookOperations(bytes, [{ kind: 'applyChartAdditions', additions: [addition] }])
    const reopened = await readWorkbook(bytes)
    expect(reopened.sheets[0]?.charts).toEqual([expect.objectContaining({
      kind: 'column', title: 'Quarterly sales',
      series: [expect.objectContaining({ categoriesRef: "'Sales Data'!$A$2:$A$3", valuesRef: "'Sales Data'!$B$2:$B$3" })],
    })])
  })

  it('maps row-oriented series and quotes apostrophes in sheet references', () => {
    const addition = chartAdditionFromGrid({
      sheetName: "Owner's Data", chartType: 'bar', title: 'By owner',
      range: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 2 },
      values: [['', 'Q1', 'Q2'], ['North', 4, 8]],
    })
    expect(addition.chart.series[0]).toMatchObject({
      name: 'North', categories: ['Q1', 'Q2'], values: [4, 8],
      categoriesRef: "'Owner''s Data'!$B$1:$C$1", valuesRef: "'Owner''s Data'!$B$2:$C$2",
    })
  })

  it('edits a trusted chart path and reads the edited title/type back', async () => {
    const addition = chartAdditionFromGrid({ sheetName: 'Sheet1', chartType: 'column', title: 'Before',
      range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 1 }, values: [['Q', 'Sales'], ['Q1', 10], ['Q2', 20]] })
    let bytes = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'applyChartAdditions', additions: [addition] }])
    const path = (await readWorkbook(bytes)).sheets[0]?.charts?.[0]?.chartPath
    expect(path).toBe('xl/charts/chart1.xml')
    bytes = await applyWorkbookOperations(bytes, [{ kind: 'applyChartEdits', edits: [{ chartPath: path, title: 'After', chartType: 'bar', legend: 'right' }] }])
    expect((await readWorkbook(bytes)).sheets[0]?.charts?.[0]).toMatchObject({ kind: 'bar', title: 'After', chartPath: path })
  })

  it('deletes the sole chart through the staged operation protocol and reopens without it', async () => {
    const addition = chartAdditionFromGrid({ sheetName: 'Sheet1', chartType: 'column', title: 'Delete me',
      range: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 1 }, values: [['Q', 'Sales'], ['Q1', 10]] })
    const original = await createBlankWorkbook()
    const staged = await applyWorkbookOperations(original, [{ kind: 'applyChartAdditions', additions: [addition] }])
    const chartPath = (await readWorkbook(staged)).sheets[0]?.charts?.[0]?.chartPath
    const saved = await applyWorkbookOperations(staged, [{ kind: 'applyChartDeletions', deletions: [{ sheetName: 'Sheet1', chartPath }] }])
    expect((await readWorkbook(saved)).sheets[0]?.charts ?? []).toEqual([])
  })
})
