import { expect, it } from 'vitest'
import { resolveTableListSource, workbookTableOperations } from './workbook-tables'
import { applyCellEdits, applyTableAdditions, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'

const table = { name: 'Staff', columns: [{ displayName: 'Name' }], range: { startRow: 2, endRow: 5, startColumn: 1, endColumn: 1 }, showHeader: true, meta: { nativeTotalsRowCount: 1 }, subUnitId: 'data' }
const workbook = (tables = [table]) => ({ getTableList: () => tables, getSheetBySheetId: () => ({ getSheetName: () => "Staff's data" }) })
it.each(['=Staff[Name]', '=staff[[NAME]]'])('resolves the data rows and quotes the sheet for %s', formula => {
  expect(resolveTableListSource(formula, workbook())).toBe("='Staff''s data'!$B$4:$B$5")
})
it.each(['\\People', 'People\\Data', '员工表'])('resolves validation lists after renaming the table to %s', name => {
  expect(resolveTableListSource(`=${name}[Name]`, workbook([{ ...table, name }]))).toBe("='Staff''s data'!$B$4:$B$5")
})
it.each(['=Staff[[Name]', '=Staff[Name]]', '=Staff[Name', '=Staff[[#Data],[Name]]', '=SUM(A1:A3)'])('keeps unsupported or incomplete syntax unchanged: %s', formula => {
  expect(resolveTableListSource(formula, workbook())).toBe(formula)
})
it('rejects missing or ambiguous table and column identities', () => {
  expect(resolveTableListSource('=Staff[Missing]', workbook())).toBe('=#NAME?')
  expect(resolveTableListSource('=Missing[Name]', workbook())).toBe('=#NAME?')
  expect(resolveTableListSource('=Staff[Name]', workbook([table, { ...table, name: 'STAFF' }]))).toBe('=#NAME?')
})
it('does not produce a reversed range for an empty data body', () => {
  expect(resolveTableListSource('=Staff[Name]', workbook([{ ...table, range: { ...table.range, endRow: 3 } }]))).toBe('=#NAME?')
})

const sourceTable = { id: '7', name: 'StaffInternal', displayName: 'Staff', range: table.range,
  columns: [{ id: '1', name: 'Name' }], headerRowCount: 1, totalsRowCount: 1 }
const sourceModel = { sheets: [{ name: 'Data', tables: [sourceTable] }] } as any
const liveTable = { ...table, id: 'file-table-data-7', name: 'Staff' }
const liveWorkbook = (tables: any[]) => ({ getTableList: () => tables,
  getSheets: () => [{ getSheetId: () => 'data', getSheetName: () => 'Data' }],
  getSheetBySheetId: (id: string) => id === 'data' ? { getSheetName: () => 'Data' } : undefined })

it('persists name and range changes against the source identity together with column changes', () => {
  const changed = { ...liveTable, name: 'People', range: { ...table.range, endRow: 8 }, columns: [{ displayName: 'Employee' }] }
  expect(workbookTableOperations(sourceModel, liveWorkbook([changed]))).toEqual([{ kind: 'applyTableEdits', edits: [{
    worksheetSheetName: 'Data', tableName: 'StaffInternal', name: 'People', area: changed.range, columnNames: ['Employee'],
  }] }])
  expect(workbookTableOperations(sourceModel, liveWorkbook([liveTable]))).toEqual([])
})

it('persists header visibility with the real range and retains source column names', () => {
  const changed = { ...liveTable, showHeader: false, range: { ...table.range, startRow: table.range.startRow + 1 } }
  expect(workbookTableOperations(sourceModel, liveWorkbook([changed]))).toEqual([{ kind: 'applyTableEdits', edits: [{
    worksheetSheetName: 'Data', tableName: 'StaffInternal', area: changed.range, headerRow: false,
  }] }])
  const hiddenSource = { sheets: [{ name: 'Data', tables: [{ ...sourceTable, headerRowCount: 0, range: changed.range }] }] } as any
  expect(workbookTableOperations(hiddenSource, liveWorkbook([changed]))).toEqual([])
  expect(workbookTableOperations(hiddenSource, liveWorkbook([liveTable]))).toEqual([{ kind: 'applyTableEdits', edits: [{
    worksheetSheetName: 'Data', tableName: 'StaffInternal', area: table.range, headerRow: true,
  }] }])
})

it('saves a newly created headerless table containing a single data row without a synthetic header', async () => {
  const original = await applyCellEdits(await createBlankWorkbook(), [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Ada' } }])
  const baseline = await readWorkbook(original)
  const current = { id: 'native-new-table:single', name: 'People', subUnitId: 'data', showHeader: false,
    range: { startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 }, columns: [{ displayName: 'Name' }],
    meta: { nativeCreatedTable: true, nativeTotalsRowCount: 0, nativeTableStyle: { name: 'TableStyleMedium2', showRowStripes: true } } }
  const workbook = { getSheets: () => [{ getSheetId: () => 'data', getSheetName: () => 'Sheet1' }], getTableList: () => [current] }
  const operations = workbookTableOperations(baseline, workbook)
  expect(operations).toEqual([{ kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Sheet1', name: 'People', area: current.range,
    columnNames: ['Name'], style: 'TableStyleMedium2', bandedRows: true, headerRow: false }] }])
  const reopened = await readWorkbook(await applyWorkbookOperations(original, operations))
  expect(reopened.sheets[0]!.tables![0]).toMatchObject({ headerRowCount: 0, range: current.range, columns: [{ name: 'Name' }] })
  expect(reopened.sheets[0]!.cells).toEqual(baseline.sheets[0]!.cells)
})

it('persists removal only on surviving writable sheets and restores the baseline after undo', () => {
  expect(workbookTableOperations(sourceModel, liveWorkbook([]))).toEqual([{ kind: 'applyTableEdits', edits: [{
    worksheetSheetName: 'Data', tableName: 'StaffInternal', remove: true,
  }] }])
  expect(workbookTableOperations(sourceModel, liveWorkbook([liveTable]))).toEqual([])
  expect(workbookTableOperations({ sheets: [{ ...sourceModel.sheets[0], tablesReadOnlyReason: 'unsupported' }] } as any, liveWorkbook([]))).toEqual([])
  expect(workbookTableOperations(sourceModel, { ...liveWorkbook([]), getSheets: () => [] })).toEqual([])
  expect(workbookTableOperations(sourceModel, {})).toEqual([])
})

it('persists totals and explicitly changed style options while leaving unmodified source options alone', () => {
  const model = { sheets: [{ ...sourceModel.sheets[0], tables: [{ ...sourceTable,
    style: { name: 'TableStyleMedium4', showRowStripes: true } }] }] } as any
  const changed = { ...liveTable, meta: { nativeTotalsRowCount: 0, nativeTableStyleName: 'TableStyleDark3' } }
  expect(workbookTableOperations(model, liveWorkbook([changed]))).toEqual([{ kind: 'applyTableEdits', edits: [{
    worksheetSheetName: 'Data', tableName: 'StaffInternal', totalsRow: false, style: 'TableStyleDark3',
  }] }])
  expect(workbookTableOperations(model, liveWorkbook([{ ...liveTable, meta: { ...liveTable.meta, nativeTableStyleName: '' } }]))).toEqual([{ kind: 'applyTableEdits', edits: [{
    worksheetSheetName: 'Data', tableName: 'StaffInternal', style: '',
  }] }])
  expect(workbookTableOperations(model, liveWorkbook([liveTable]))).toEqual([])
  expect(workbookTableOperations(model, liveWorkbook([{ ...liveTable, meta: { ...liveTable.meta, nativeTableStyleName: 'TableStyleMedium4' } }]))).toEqual([])
})

it('round-trips the generated rename resize and removal edits through the real workbook engine', async () => {
  const original = await applyTableAdditions(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' } },
  ]), [{ worksheetSheetName: 'Sheet1', name: 'Staff', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, columnNames: ['Name'], style: 'TableStyleDark3', bandedRows: true }])
  const baseline = await readWorkbook(original), before = baseline.sheets[0]!.tables![0]!
  const sheet = { getSheetId: () => 'data', getSheetName: () => 'Sheet1' }
  const current = { ...liveTable, id: `file-table-data-${before.id}`, name: 'Employees',
    range: { ...before.range, endRow: 4 }, columns: [{ displayName: 'Name' }], meta: { nativeTotalsRowCount: before.totalsRowCount } }
  const workbook = { getSheets: () => [sheet], getTableList: () => [current] }
  const operations = workbookTableOperations(baseline, workbook)
  const reopened = await readWorkbook(await applyWorkbookOperations(original, operations))
  expect(reopened.sheets[0]!.tables![0]).toMatchObject({ name: 'Employees', displayName: 'Employees',
    range: current.range, style: { name: 'TableStyleDark3', showRowStripes: true } })
  expect(reopened.sheets[0]!.cells).toEqual(baseline.sheets[0]!.cells)
  expect(workbookTableOperations(baseline, { ...workbook, getTableList: () => [{ ...current, name: before.displayName, range: before.range }] })).toEqual([])
  const removal = workbookTableOperations(baseline, { ...workbook, getTableList: () => [] })
  const converted = await readWorkbook(await applyWorkbookOperations(original, removal))
  expect(converted.sheets[0]!.tables ?? []).toEqual([])
  expect(converted.sheets[0]!.cells).toEqual(baseline.sheets[0]!.cells)
})

it('emits only changed table style flags and returns to an empty diff at the source values', () => {
  const style = { name: 'TableStyleMedium4', showFirstColumn: true, showLastColumn: false, showRowStripes: true, showColumnStripes: false }
  const model = { sheets: [{ ...sourceModel.sheets[0], tables: [{ ...sourceTable, style }] }] } as any
  for (const [option, field] of [['showFirstColumn', 'firstColumn'], ['showLastColumn', 'lastColumn'], ['showRowStripes', 'bandedRows'], ['showColumnStripes', 'bandedColumns']] as const) {
    const changed = { ...liveTable, meta: { ...liveTable.meta, nativeTableStyle: { ...style, [option]: !style[option] } } }
    expect(workbookTableOperations(model, liveWorkbook([changed]))).toEqual([{ kind: 'applyTableEdits', edits: [{
      worksheetSheetName: 'Data', tableName: 'StaffInternal', [field]: !style[option],
    }] }])
  }
  expect(workbookTableOperations(model, liveWorkbook([{ ...liveTable, meta: { ...liveTable.meta, nativeTableStyle: style } }]))).toEqual([])
  expect(workbookTableOperations(model, liveWorkbook([liveTable]))).toEqual([])
})

it('persists new tables from their final live state including options and totals, and drops undone creations', async () => {
  const original = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: null, formula: '=SUBTOTAL(103,A2:A2)' } },
  ])
  const baseline = await readWorkbook(original)
  const current = { id: 'native-new-table:1', subUnitId: 'data', name: 'Employees', showHeader: true,
    range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columns: [{ displayName: 'Name' }],
    meta: { nativeCreatedTable: true, nativeTotalsRowCount: 1,
      nativeTableStyle: { name: 'TableStyleDark3', showRowStripes: false, showFirstColumn: true, showLastColumn: true, showColumnStripes: true } } }
  const workbook = { getSheets: () => [{ getSheetId: () => 'data', getSheetName: () => 'Sheet1' }], getTableList: () => [current] }
  const operations = workbookTableOperations(baseline, workbook)
  expect(operations).toEqual([
    { kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Sheet1', name: 'Employees', area: current.range, columnNames: ['Name'], style: 'TableStyleDark3', bandedRows: false }] },
    { kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Employees', totalsRow: true, firstColumn: true, lastColumn: true, bandedColumns: true }] },
  ])
  const reopened = await readWorkbook(await applyWorkbookOperations(original, operations))
  expect(reopened.sheets[0]!.tables![0]).toMatchObject({ name: 'Employees', totalsRowCount: 1,
    range: current.range, style: current.meta.nativeTableStyle })
  expect(reopened.sheets[0]!.cells).toEqual(baseline.sheets[0]!.cells)
  expect(workbookTableOperations(baseline, { ...workbook, getTableList: () => [] })).toEqual([])
  expect(workbookTableOperations(baseline, { ...workbook, getTableList: () => [{ ...current, meta: {} }] })).toEqual([])
})

it('applies existing table removal or renaming before adding a table that reuses its name and area', async () => {
  const original = await applyTableAdditions(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' } },
  ]), [{ worksheetSheetName: 'Sheet1', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, name: 'Staff', columnNames: ['Name'], bandedRows: true }])
  const baseline = await readWorkbook(original), source = baseline.sheets[0]!.tables![0]!
  const newTable = { id: 'native-new-table:1', subUnitId: 'data', name: 'Staff', range: source.range, columns: [{ displayName: 'Name' }],
    meta: { nativeCreatedTable: true, nativeTotalsRowCount: 0, nativeTableStyle: { name: 'TableStyleMedium2', showRowStripes: true } } }
  const workbook = { getSheets: () => [{ getSheetId: () => 'data', getSheetName: () => 'Sheet1' }], getTableList: () => [newTable] }
  const operations = workbookTableOperations(baseline, workbook)
  expect(operations.map(op => op.kind)).toEqual(['applyTableEdits', 'applyTableAdditions'])
  expect((await readWorkbook(await applyWorkbookOperations(original, operations))).sheets[0]!.tables).toHaveLength(1)
})

it('removes converted source tables before a surviving table reuses their name', async () => {
  const original = await applyTableAdditions(await createBlankWorkbook(), ['First', 'Second'].map((name, index) => ({
    worksheetSheetName: 'Sheet1', area: { startRow: 0, endRow: 1, startColumn: index * 2, endColumn: index * 2 }, name, columnNames: ['Name'], bandedRows: true,
  })))
  const baseline = await readWorkbook(original), before = baseline.sheets[0]!.tables![0]!
  const survivor = { id: `file-table-data-${before.id}`, subUnitId: 'data', name: 'Second', range: before.range,
    columns: [{ displayName: 'Name' }], meta: { nativeTotalsRowCount: before.totalsRowCount } }
  const operations = workbookTableOperations(baseline, { getSheets: () => [{ getSheetId: () => 'data', getSheetName: () => 'Sheet1' }], getTableList: () => [survivor] })
  const reopened = await readWorkbook(await applyWorkbookOperations(original, operations))
  expect(reopened.sheets[0]!.tables!.map(table => table.name)).toEqual(['Second'])
  expect(reopened.sheets[0]!.tables![0]!.range).toEqual(before.range)
})
