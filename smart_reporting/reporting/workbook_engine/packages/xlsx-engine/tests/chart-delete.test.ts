import { describe, expect, it } from 'vitest'
import { applyCellEdits, applyChartAdditions, createBlankWorkbook, readWorkbook } from '../src'
import { applyChartDeletions } from '../src/chart-delete'
import { createBufferEntrySource } from '../src/zip'

const addition = (sheetName = 'Sheet1') => ({
  worksheetSheetName: sheetName,
  anchor: { fromRow: 0, fromColumn: 3, fromRowOffset: 0, fromColumnOffset: 0, toRow: 15, toColumn: 10, toRowOffset: 0, toColumnOffset: 0 },
  chart: { chartType: 'column' as const, title: 'Sales', series: [{ name: 'Sales', categories: ['Q1'], values: [1] }] },
})

async function seed() {
  let bytes = await applyCellEdits(await createBlankWorkbook(), [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Q1' } }])
  return applyChartAdditions(bytes, [addition()])
}

describe('chart deletion', () => {
  it('removes the owned anchor, relationship, chart part and override', async () => {
    const before = await seed()
    const after = await applyChartDeletions(before, [{ sheetName: 'Sheet1', chartPath: 'xl/charts/chart1.xml' }])
    expect((await readWorkbook(after)).sheets[0]?.charts ?? []).toEqual([])
    const source = await createBufferEntrySource(after)
    expect(await source.has('xl/charts/chart1.xml')).toBe(false)
    expect(await source.readText('xl/drawings/_rels/drawing1.xml.rels')).not.toContain('chart1.xml')
    expect(await source.readText('[Content_Types].xml')).not.toContain('/xl/charts/chart1.xml')
  })

  it('rejects a chart path owned by another sheet', async () => {
    const before = await applyChartAdditions(await createBlankWorkbook('Sheet1'), [addition('Sheet1')])
    await expect(applyChartDeletions(before, [{ sheetName: 'Other', chartPath: 'xl/charts/chart1.xml' }])).rejects.toThrow()
  })

  it('removes multiple charts from one drawing without losing earlier XML edits', async () => {
    const before = await applyChartAdditions(await createBlankWorkbook(), [addition(), addition()])
    const after = await applyChartDeletions(before, [
      { sheetName: 'Sheet1', chartPath: 'xl/charts/chart1.xml' },
      { sheetName: 'Sheet1', chartPath: 'xl/charts/chart2.xml' },
    ])
    expect((await readWorkbook(after)).sheets[0]?.charts ?? []).toEqual([])
    const source = await createBufferEntrySource(after)
    const drawing = await source.readText('xl/drawings/drawing1.xml')
    const rels = await source.readText('xl/drawings/_rels/drawing1.xml.rels')
    const types = await source.readText('[Content_Types].xml')
    expect(drawing).not.toContain('<c:chart')
    expect(rels).not.toContain('/chart')
    expect(types).not.toContain('/xl/charts/chart')
  })
})
