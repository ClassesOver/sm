import { expect, it } from 'vitest'
import {
  applyCellEdits, applyTableAdditions, createBlankWorkbook, inventoryXlsx, readWorkbook,
} from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from './operations'

it('roundtrips merge and unmerge while retaining content, formatting and other package parts', async () => {
  const source = await applyCellEdits(await createBlankWorkbook('汇总'), [{
    sheetName: '汇总', row: 0, column: 0, writeValue: true, cell: { value: '标题' }, style: { bold: true },
  }])
  const merged = await applyWorkbookOperations(source, [{
    kind: 'applySheetMerges', sheetName: '汇总', ranges: ['A1:C1', 'A3:B4'],
  }])
  const model = await readWorkbook(merged)
  expect(model.sheets[0]!.merges).toEqual(['A1:C1', 'A3:B4'])
  expect(model.sheets[0]!.cells.A1).toEqual((await readWorkbook(source)).sheets[0]!.cells.A1)
  const before = new Map((await inventoryXlsx(source)).map(entry => [entry.path, entry.sha256]))
  expect((await inventoryXlsx(merged)).filter(entry => before.get(entry.path) !== entry.sha256).map(entry => entry.path))
    .toEqual(['xl/worksheets/sheet1.xml'])
  const unmerged = await applyWorkbookOperations(merged, [{ kind: 'applySheetMerges', sheetName: '汇总', ranges: [] }])
  expect((await readWorkbook(unmerged)).sheets[0]!.merges).toEqual([])
  expect((await readWorkbook(source)).sheets[0]!.merges).toEqual([])
})

it.each([
  ['A1'], ['A0:B2'], ['XFE1:XFF2'], ['A1048576:B1048577'], ['A1:B2', 'B2:C3'],
].map(ranges => ({ ranges })))('rejects invalid or overlapping merged ranges $ranges', async ({ ranges }) => {
  await expect(applyWorkbookOperations(await createBlankWorkbook('汇总'), [{
    kind: 'applySheetMerges', sheetName: '汇总', ranges,
  }])).rejects.toThrow(/workbook_merge/)
})

it('rejects merging across a structured table', async () => {
  const source = await applyTableAdditions(await createBlankWorkbook('汇总'), [{
    worksheetSheetName: '汇总', area: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 1 },
    name: 'Revenue', columnNames: ['部门', '收入'], bandedRows: true,
  }])
  await expect(applyWorkbookOperations(source, [{ kind: 'applySheetMerges', sheetName: '汇总', ranges: ['A1:B2'] }]))
    .rejects.toThrow(/workbook_merge_table_conflict/)
})

it('keeps saved merged ranges in step with sheet renames and row insertions', async () => {
  const source = await applyCellEdits(await createBlankWorkbook('汇总'), [{
    sheetName: '汇总', row: 1, column: 0, writeValue: true, cell: { value: '标题' },
  }])
  const result = await applyWorkbookOperations(source, [
    { kind: 'applySheetMerges', sheetName: '汇总', ranges: ['A2:B3'] },
    { kind: 'applyRowColumnOps', sheetName: '汇总', ops: [{ kind: 'insert-rows', index: 0, count: 1 }] },
    { kind: 'applySheetEdits', plan: { renames: [{ sheetName: '汇总', newName: '摘要' }], additions: [], removals: [], order: ['摘要'] } },
  ])
  const sheet = (await readWorkbook(result)).sheets[0]!
  expect(sheet.name).toBe('摘要')
  expect(sheet.merges).toEqual(['A3:B4'])
})
