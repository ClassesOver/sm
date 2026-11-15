import { expect, it } from 'vitest'
import JSZip from 'jszip'
import { applyCellEdits, applySheetHyperlinks, applySheetNotes, createBlankWorkbook, protectSheet, readPackageSheetHyperlinks, readWorkbook, sortRangeRows } from '../src'

it('requires both sort permission and unlocked cells throughout a protected sort range', async () => {
  const bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 20 }, style: { protectionLocked: false } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 10 }, style: { protectionLocked: false } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 'locked' } },
  ])
  const spec = { range: 'A1:A2', byColumn: 'A', ascending: true, hasHeader: false }
  const denied = await protectSheet(bytes, 'Sheet1', true)
  await expect(sortRangeRows(denied, 'Sheet1', spec)).rejects.toThrow('未授权排序')
  const allowed = await protectSheet(bytes, 'Sheet1', true, { sort: true })
  await expect(sortRangeRows(allowed, 'Sheet1', { ...spec, range: 'A1:B2' })).rejects.toThrow('排序范围包含锁定单元格')
  const sorted = await sortRangeRows(allowed, 'Sheet1', spec)
  const saved = (await readWorkbook(sorted)).sheets[0]!
  expect(saved.cells.A1?.value).toBe(10)
  expect(saved.cells.A2?.value).toBe(20)
  expect(saved.cells.B2?.value).toBe('locked')
  expect(saved.protection).toMatchObject({ protected: true, allow: { sort: true } })
  const noted = await applySheetNotes(bytes, 'Sheet1', [{ row: 0, column: 0, author: 'Alice', text: 'anchored' }])
  await expect(sortRangeRows(await protectSheet(noted, 'Sheet1', true, { sort: true }), 'Sheet1', spec))
    .rejects.toThrow('排序范围包含批注')
})

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

it('sorts a protected range by multiple keys while preserving the header and ties', async () => {
  const values = [['Group', 'Score', 'Record'], ['B', 3, 'B3'], ['A', 1, 'A1'], ['A', 4, 'A4-first'], ['A', 4, 'A4-second'], ['A', null, 'blank']]
  const bytes = await applyCellEdits(await createBlankWorkbook(), values.flatMap((cells, row) => cells.map((value, column) => ({
    sheetName: 'Sheet1', row, column, writeValue: true, cell: { value }, style: { protectionLocked: false },
  }))))
  const source = await protectSheet(bytes, 'Sheet1', true, { sort: true })
  const spec = { range: 'A1:C6', byColumn: 'A', ascending: true, hasHeader: true, thenBy: [{ byColumn: 'B', ascending: false }] }
  const sorted = await sortRangeRows(source, 'Sheet1', spec)
  const sheet = (await readWorkbook(sorted)).sheets[0]!
  expect([1, 2, 3, 4, 5, 6].map(row => sheet.cells[`C${row}`]?.value))
    .toEqual(['Record', 'A4-first', 'A4-second', 'A1', 'blank', 'B3'])
  await expect(sortRangeRows(source, 'Sheet1', { ...spec, thenBy: [{ byColumn: 'D', ascending: true }] }))
    .rejects.toThrow('outside the range')
})

it('keeps inherited cell styles attached to rows moved by a protected sort', async () => {
  let bytes = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 2 }, style: { protectionLocked: false, bold: true } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 1 }, style: { protectionLocked: false, italic: true } },
  ])
  bytes = await protectSheet(bytes, 'Sheet1', true, { sort: true })
  const before = (await readWorkbook(bytes)).sheets[0]!
  const bold = before.cells.A1!.styleIndex!, italic = before.cells.A2!.styleIndex!
  const zip = await JSZip.loadAsync(bytes)
  const worksheet = (await zip.file(before.path)!.async('string'))
    .replace('<row r="1">', `<row r="1" s="${bold}" customFormat="1">`)
    .replace('<row r="2">', `<row r="2" s="${italic}" customFormat="1">`)
    .replace(/(<c r="A[12]") s="\d+"/g, '$1')
  zip.file(before.path, worksheet)
  const inherited = await zip.generateAsync({ type: 'uint8array' })
  const sorted = await sortRangeRows(inherited, 'Sheet1', { range: 'A1:A2', byColumn: 'A', ascending: true, hasHeader: false })
  const result = (await readWorkbook(sorted)).sheets[0]!
  expect(result.cells.A1).toMatchObject({ value: 1, styleIndex: italic })
  expect(result.cells.A2).toMatchObject({ value: 2, styleIndex: bold })
  expect(result.rows.map(row => row.styleIndex)).toEqual([bold, italic])
})

it('preserves compatible merge layouts and rejects a sort that would split a merge', async () => {
  let bytes = await applyCellEdits(await createBlankWorkbook(), ['Header', 2, 1].map((value, row) => ({
    sheetName: 'Sheet1', row, column: 0, writeValue: true, cell: { value },
  })))
  const path = (await readWorkbook(bytes)).sheets[0]!.path
  const zip = await JSZip.loadAsync(bytes)
  const worksheet = await zip.file(path)!.async('string')
  const withMerges = async (merges: readonly string[]) => {
    zip.file(path, worksheet.replace('</worksheet>', `<mergeCells count="${merges.length}">${merges.map(ref => `<mergeCell ref="${ref}"/>`).join('')}</mergeCells></worksheet>`))
    return zip.generateAsync({ type: 'uint8array' })
  }
  const spec = { range: 'A1:B3', byColumn: 'A', ascending: true, hasHeader: true }
  bytes = await withMerges(['A1:B1', 'A2:B2', 'A3:B3'])
  const valid = (await readWorkbook(await sortRangeRows(bytes, 'Sheet1', spec))).sheets[0]!
  expect(valid.merges).toEqual(['A1:B1', 'A2:B2', 'A3:B3'])
  expect(valid.cells.A2?.value).toBe(1)
  await expect(sortRangeRows(await withMerges(['A1:B1', 'A2:B2']), 'Sheet1', spec)).rejects.toThrow('合并单元格')
  await expect(sortRangeRows(await withMerges(['A2:C2']), 'Sheet1', spec)).rejects.toThrow('合并单元格')
})

it('moves hyperlinks with sorted cells and leaves the remaining coverage in place', async () => {
  const bytes = await applyCellEdits(await createBlankWorkbook(), ['Header', 3, 1, 2].map((value, row) => ({
    sheetName: 'Sheet1', row, column: 0, writeValue: true, cell: { value }, style: { protectionLocked: false },
  })))
  const linked = await applySheetHyperlinks(bytes, 'Sheet1', [
    { ref: 'A1', expectedTarget: null, target: '#Sheet1!D5' },
    { ref: 'A2', expectedTarget: null, target: 'https://example.com/group' },
    { ref: 'A4', expectedTarget: null, target: '#Sheet1!D6' },
  ])
  const input = await protectSheet(linked, 'Sheet1', true, { sort: true })
  const path = (await readWorkbook(input)).sheets[0]!.path
  const zip = await JSZip.loadAsync(input)
  const xml = (await zip.file(path)!.async('string'))
    .replace(/(<hyperlink\b[^>]*\bref=)"A2"([^>]*)\/>/, "$1'A2:B3'$2></hyperlink>")
  zip.file(path, xml)
  const before = await zip.generateAsync({ type: 'uint8array' })
  const after = await sortRangeRows(before, 'Sheet1', { range: 'A1:A4', byColumn: 'A', ascending: true, hasHeader: true })
  const refs = (await readPackageSheetHyperlinks(after, 'Sheet1')).sort((a, b) => a.ref.localeCompare(b.ref))
  expect(refs.map(link => link.ref)).toEqual(['A1', 'A2', 'A3', 'A4', 'B2:B3'])
  expect(refs.slice(0, 4).map(link => link.target)).toEqual([
    '#Sheet1!D5', 'https://example.com/group', '#Sheet1!D6', 'https://example.com/group',
  ])
  const output = await JSZip.loadAsync(after)
  const rels = path.replace(/\/([^/]+)$/, '/_rels/$1.rels')
  expect(await output.file(rels)!.async('string')).toBe(await zip.file(rels)!.async('string'))
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
