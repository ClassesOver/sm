import {expect, it} from 'vitest'
import {createBlankWorkbook, readWorkbook} from '@sheets-web/xlsx-engine'
import {applyWorkbookOperations} from './operations'

const source = {kind: 'applyTableSource', sheetName: 'Sheet1', range: 'A1:C2', bandedRows: false, style: 'TableStyleDark2'}
const cell = (row: number, column: number, value: string | number) => ({
  sheetName: 'Sheet1', row, column, writeValue: true, cell: {value},
})

it('creates an Excel table from current header cells including blank and duplicate labels', async () => {
  const initialized = await createBlankWorkbook()
  const after = await applyWorkbookOperations(initialized, [
    {kind: 'applyCellEdits', edits: [cell(0, 0, 'Region'), cell(0, 2, 'region'), cell(1, 1, 42)]},
    source,
  ])
  const sheet = (await readWorkbook(after)).sheets[0]!
  expect(sheet.tables?.[0]).toMatchObject({
    name: 'Table1', range: {startRow: 0, endRow: 1, startColumn: 0, endColumn: 2},
    style: {name: 'TableStyleDark2', showRowStripes: false},
    columns: [{name: 'Region'}, {name: 'Column2'}, {name: 'region2'}],
  })
  expect([sheet.cells.A1?.value, sheet.cells.B1?.value, sheet.cells.C1?.value]).toEqual(['Region', 'Column2', 'region2'])
  expect(sheet.cells.B2?.value).toBe(42)
})

it('allocates the next workbook-wide table name and rejects overlapping areas', async () => {
  const before = await applyWorkbookOperations(await createBlankWorkbook(), [source])
  await expect(applyWorkbookOperations(before, [source])).rejects.toThrow()
  const after = await applyWorkbookOperations(before, [{...source, range: 'D1:E2'}])
  expect((await readWorkbook(after)).sheets[0]!.tables?.map(table => table.name)).toEqual(['Table1', 'Table2'])
})

it('keeps a formula header intact when its calculated text cannot be verified', async () => {
  const before = await applyWorkbookOperations(await createBlankWorkbook(), [
    {kind: 'applyCellEdits', edits: [{...cell(0, 0, 0), cell: {value: null, formula: '"Region"'}}]},
  ])
  await expect(applyWorkbookOperations(before, [source])).rejects.toThrow('formula_header')
  expect((await readWorkbook(before)).sheets[0]!.cells.A1?.formula).toBe('="Region"')
})
