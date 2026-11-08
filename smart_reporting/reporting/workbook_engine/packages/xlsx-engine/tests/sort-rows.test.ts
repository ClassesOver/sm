import { expect, it } from 'vitest'
import { applyCellEdits, applySheetNotes, createBlankWorkbook, readWorkbook, sortRangeRows } from '../src'

it('sortRangeRows permutes full cell records so styles move with values', async () => {
  let bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '乙' }, style: { bold: true, fillColor: '#FFF2CC' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: '甲' }, style: { italic: true, fontColor: '#0B4F8A' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 20 }, style: { numberFormat: '#,##0.00' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 3, column: 2, writeValue: true, cell: { value: 'range外' } },
  ])
  const before = (await readWorkbook(bytes)).sheets[0]!
  bytes = await sortRangeRows(bytes, 'Sheet1', { range: 'A1:B2', byColumn: 'A', ascending: true, hasHeader: false })
  const sheet = (await readWorkbook(bytes)).sheets[0]!
  expect(sheet.cells.A1?.value).toBe('甲')
  expect(sheet.cells.A2?.value).toBe('乙')
  expect(sheet.cells.B1?.value).toBe(10)
  expect(sheet.cells.B2?.value).toBe(20)
  // 样式随行整体迁移：甲的斜体/蓝色样式到第 1 行，乙的粗体/填充/千分位到第 2 行。
  expect(sheet.cells.A1?.styleIndex).toBe(before.cells.A2?.styleIndex)
  expect(sheet.cells.A2?.styleIndex).toBe(before.cells.A1?.styleIndex)
  expect(sheet.cells.B1?.styleIndex).toBeUndefined()
  expect(sheet.cells.B2?.styleIndex).toBe(before.cells.B1?.styleIndex)
  expect(sheet.cells.C4?.value).toBe('range外')
})

it('sortRangeRows fails closed on formulas and notes inside the range', async () => {
  let bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 2 } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: null, formula: '=A1*2' } },
  ])
  await expect(sortRangeRows(bytes, 'Sheet1', { range: 'A1:A2', byColumn: 'A', ascending: true, hasHeader: false }))
    .rejects.toThrow('formula at A2')
  let noted = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 2 } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 1 } },
  ])
  noted = await applySheetNotes(noted, 'Sheet1', [{ row: 0, column: 0, author: 'Alice', text: 'anchored' }])
  await expect(sortRangeRows(noted, 'Sheet1', { range: 'A1:A2', byColumn: 'A', ascending: true, hasHeader: false }))
    .rejects.toThrow('排序范围包含批注')
  // 范围外批注不阻塞。
  const outside = await applySheetNotes(noted, 'Sheet1', [{ row: 5, column: 5, author: 'Bob', text: 'outside' }])
  await expect(sortRangeRows(outside, 'Sheet1', { range: 'B1:C2', byColumn: 'B', ascending: true, hasHeader: false })).resolves.toBeInstanceOf(Uint8Array)
})
