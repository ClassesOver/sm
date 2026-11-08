import { expect, it } from 'vitest'
import JSZip from 'jszip'
import { applyCellEdits, applySheetNotes, createBlankWorkbook, readWorkbook, sortRangeRows } from '../src'

it('sortRangeRows permutes full cell records so styles move with values', async () => {
  let bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'b乙' }, style: { bold: true, fillColor: '#FFF2CC' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'a甲' }, style: { italic: true, fontColor: '#0B4F8A' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 20 }, style: { numberFormat: '#,##0.00' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 3, column: 2, writeValue: true, cell: { value: 'range外' } },
  ])
  const before = (await readWorkbook(bytes)).sheets[0]!
  bytes = await sortRangeRows(bytes, 'Sheet1', { range: 'A1:B2', byColumn: 'A', ascending: true, hasHeader: false })
  const sheet = (await readWorkbook(bytes)).sheets[0]!
  // 文本比较走宿主默认 locale（zh-CN 按拼音、en-US 按码位），ASCII 前缀使顺序与环境无关。
  expect(sheet.cells.A1?.value).toBe('a甲')
  expect(sheet.cells.A2?.value).toBe('b乙')
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

it('sortRangeRows splices rows absent from sheetData in ascending order instead of dropping them', async () => {
  // A1 不存在于 sheetData；升序后 1 移到第 1 行（空白排最后）。旧实现在不含
  // </sheetData> 的 body 中查找结束标签，新行被静默丢弃，值 1 丢失。
  const bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 1 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 2 } },
    { sheetName: 'Sheet1', row: 4, column: 0, writeValue: true, cell: { value: 'range外' } },
  ])
  const sorted = await sortRangeRows(bytes, 'Sheet1', { range: 'A1:A3', byColumn: 'A', ascending: true, hasHeader: false })
  const sheet = (await readWorkbook(sorted)).sheets[0]!
  expect(sheet.cells.A1?.value).toBe(1)
  expect(sheet.cells.A2?.value).toBe(2)
  expect(sheet.cells.A3).toBeUndefined()
  expect(sheet.cells.A5?.value).toBe('range外')
  const xml = await (await JSZip.loadAsync(sorted)).file('xl/worksheets/sheet1.xml')!.async('string')
  const rows = [...xml.matchAll(/<row\b[^>]*\br="([0-9]+)"/g)].map(match => Number(match[1]))
  expect(rows).toEqual([...rows].sort((left, right) => left - right))
  expect(rows[0]).toBe(1)
})
