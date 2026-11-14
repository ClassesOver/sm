import { expect, it } from 'vitest'
import { createBlankWorkbook } from '../src/blank'
import { applyCellEdits } from '../src/workbook-write'
import { createBufferEntrySource } from '../src/zip'

it('expands worksheet dimensions so streaming readers see newly added cells', async () => {
  const bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 3, column: 2, writeValue: true, cell: { value: '落款' } },
  ])
  const xml = await (await createBufferEntrySource(bytes)).readText('xl/worksheets/sheet1.xml')
  expect(xml).toContain('<dimension ref="A1:C4"/>')
})

it('keeps previously used bounds when writing a cell within the range', async () => {
  let bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 9, column: 5, writeValue: true, cell: { value: 42 } },
  ])
  bytes = await applyCellEdits(bytes, [
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: '说明' } },
  ])
  const xml = await (await createBufferEntrySource(bytes)).readText('xl/worksheets/sheet1.xml')
  expect(xml).toContain('<dimension ref="A1:F10"/>')
})
