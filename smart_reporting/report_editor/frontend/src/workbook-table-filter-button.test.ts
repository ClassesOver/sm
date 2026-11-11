import { expect, it } from 'vitest'
import { applyCellEdits, applyTableAdditions, applyTableEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { withWorkbookTables, workbookTableOperations } from './workbook-tables'

async function source(filterButton: boolean) {
  const bytes = await applyTableAdditions(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' } },
  ]), [{ worksheetSheetName: 'Sheet1', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, name: 'Staff', columnNames: ['Name'], bandedRows: true }])
  return readWorkbook(await applyTableEdits(bytes, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', filterButton }]))
}

it('projects the file filter-button state without changing its table range', async () => {
  for (const filterButton of [true, false]) {
    const model = await source(filterButton)
    expect(model.sheets[0]?.tables?.[0]).toMatchObject({ filterButton, range: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 } })
    const loaded = withWorkbookTables({ sheets: { data: { id: 'data', name: 'Sheet1' } } }, model)
    const tables = JSON.parse(loaded.resources.find(item => item.name === 'SHEET_TABLE_PLUGIN')!.data)
    expect(tables.data.tables[0].meta.nativeFilterButton).toBe(filterButton)
  }
})

it('saves only filter-button changes for a file table', async () => {
  const model = await source(true), before = model.sheets[0]!.tables![0]!
  const table = { id: 'file-table-data-' + before.id, name: before.displayName, subUnitId: 'data', range: before.range,
    columns: before.columns.map(column => ({ id: column.id, displayName: column.name })), showHeader: true,
    meta: { nativeTotalsRowCount: 0, nativeFilterButton: false } }
  const workbook = { getTableList: () => [table], getSheets: () => [{ getSheetName: () => 'Sheet1', getSheetId: () => 'data' }] }
  expect(workbookTableOperations(model, workbook)).toEqual([{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', filterButton: false }] }])
})

it('persists a new table with disabled filter buttons through a table edit', () => {
  const table = { id: 'created', name: 'Staff', subUnitId: 'data', range: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 },
    columns: [{ id: '1', displayName: 'Name' }], showHeader: true, meta: { nativeCreatedTable: true, nativeFilterButton: false } }
  const workbook = { getTableList: () => [table], getSheets: () => [{ getSheetName: () => 'Sheet1', getSheetId: () => 'data' }] }
  expect(workbookTableOperations({ sheets: [{ name: 'Sheet1' }] } as any, workbook)).toEqual([
    { kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Sheet1', area: table.range, name: 'Staff', columnNames: ['Name'], style: '', bandedRows: false }] },
    { kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', filterButton: false }] },
  ])
})

it('hides real table buttons, clears criteria, restores filtered rows in one undo and keeps manual hidden rows', async () => {
  const { Univer, LocaleType, IUniverInstanceService } = await import('@univerjs/core')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverSheetsTablePlugin, TableManager, TableColumnFilterTypeEnum } = await import('@univerjs/sheets-table')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  await import('@univerjs/sheets/facade')
  await import('@univerjs/sheets-table/facade')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { loadWorkbookData } = await import('./workbook-vendor/grid/sync')
  const { installTableFilterButton } = await import('./workbook-table-filter-button')
  const { workbookTableConfig } = await import('./workbook-tables')
  const bytes = await applyTableAdditions(await applyCellEdits(await createBlankWorkbook(), ['Name', 'Ada', 'Bob'].map((value, row) => ({
    sheetName: 'Sheet1', row, column: 0, writeValue: true, cell: { value },
  }))), [{ worksheetSheetName: 'Sheet1', area: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, name: 'Staff', columnNames: ['Name'], bandedRows: true }])
  const model = await readWorkbook(bytes), univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  let installed: ReturnType<typeof installTableFilterButton> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
    const api = FUniver.newAPI(univer), runtime = { univer, univerAPI: api }
    const injector = univer.__getInjector()
    loadWorkbookData(runtime as any, withWorkbookTables(buildWorkbookData(model, 'filter-book', 'filter'), model))
    injector.get(IUniverInstanceService).focusUnit('filter-book')
    const manager = injector.get(TableManager)
    let protectedState = false
    installed = installTableFilterButton(runtime, () => protectedState)
    const workbook = api.getActiveWorkbook()!, sheet = workbook.getActiveSheet()!, core = sheet.getSheet()
    const id = workbook.getTableList()[0]!.id, table = () => manager.getTable('filter-book', id)!
    sheet.hideRows(1)
    manager.addFilter('filter-book', id, 0, { filterType: TableColumnFilterTypeEnum.manual, values: ['Ada'], isAllSelected: false })
    expect(core.isRowFiltered(2)).toBe(true)
    protectedState = true
    expect(() => installed!.setFilterButton(id, false)).toThrow('受保护')
    protectedState = false
    const before = structuredClone(table().toJSON()), cells = structuredClone(core.getCellMatrix().getData())
    expect(manager.getSheetFilterRangeWithState('filter-book', sheet.getSheetId())).toHaveLength(1)
    expect(injector.get((await import('@univerjs/core')).ICommandService).syncExecuteCommand('sheet.mutation.native-table-filter-button', { unitId: 'filter-book', tableId: id, state: {} })).toBe(false)
    installed.setFilterButton(id, false)
    expect(manager.getSheetFilterRangeWithState('filter-book', sheet.getSheetId())).toEqual([])
    expect(core.isRowFiltered(2)).toBe(false)
    expect(core.getRowVisible(1)).toBe(false)
    expect(table().getRange()).toEqual(before.range)
    expect(core.getCellMatrix().getData()).toEqual(cells)
    await api.undo()
    expect(table().toJSON()).toEqual(before)
    expect(core.isRowFiltered(2)).toBe(true)
    expect(manager.getSheetFilterRangeWithState('filter-book', sheet.getSheetId())).toHaveLength(1)
    await api.redo()
    expect(core.isRowFiltered(2)).toBe(false)
    expect(core.getRowVisible(1)).toBe(false)
    const { applyWorkbookOperations } = await import('../../../reporting/workbook_engine/bridge/operations')
    const saved = await applyWorkbookOperations(bytes, workbookTableOperations(model, workbook))
    expect((await readWorkbook(saved)).sheets[0]!.tables![0]).toMatchObject({ filterButton: false, range: before.range })
    // 同一安装实例在核心重建后继续使用当前workbook，不保留旧表对象。
    loadWorkbookData(runtime as any, withWorkbookTables(buildWorkbookData(await readWorkbook(saved), 'filter-book', 'filter'), await readWorkbook(saved)))
    injector.get(IUniverInstanceService).focusUnit('filter-book')
    expect(manager.getSheetFilterRangeWithState('filter-book', 'sheet-0')).toEqual([])
    installed.setFilterButton(id, true)
    expect(manager.getSheetFilterRangeWithState('filter-book', 'sheet-0')).toHaveLength(1)
    expect(installed.setFilterButton(id, true)).toBe(false)
    installed.setFilterButton(id, false)
    const { installTableHeaderRow } = await import('./workbook-table-header-row')
    const header = installTableHeaderRow(runtime)
    try {
      header.setHeaderRow(id, false)
      expect(table().getTableMeta().nativeFilterButton).toBe(false)
      expect(() => installed!.setFilterButton(id, true)).toThrow('标题行')
      expect(manager.getSheetFilterRangeWithState('filter-book', 'sheet-0')).toEqual([])
      header.setHeaderRow(id, true)
      expect(table().getTableMeta().nativeFilterButton).toBe(true)
      expect(manager.getSheetFilterRangeWithState('filter-book', 'sheet-0')).toHaveLength(1)
      const reopened = await readWorkbook(await applyWorkbookOperations(saved, workbookTableOperations(await readWorkbook(saved), api.getActiveWorkbook()!)))
      expect(reopened.sheets[0]!.tables![0]).toMatchObject({ headerRowCount: 1, filterButton: true })
      await api.undo()
      expect(table().isShowHeader()).toBe(false)
      expect(table().getTableMeta().nativeFilterButton).toBe(false)
      await api.undo()
      expect(table().isShowHeader()).toBe(true)
      expect(table().getTableMeta().nativeFilterButton).toBe(false)
    } finally { header.dispose() }
  } finally { installed?.dispose(); univer.dispose() }
})

it('keeps disabled source filters unchanged and reads headerless tables without filter buttons', async () => {
  const disabled = await source(false)
  const loaded = withWorkbookTables({ sheets: { data: { id: 'data', name: 'Sheet1' } } }, disabled)
  const tables = JSON.parse(loaded.resources.find(item => item.name === 'SHEET_TABLE_PLUGIN')!.data)
  const table = tables.data.tables[0]
  expect(table.meta.nativeFilterButton).toBe(false)
  const workbook = { getTableList: () => [{ ...table, subUnitId: 'data', showHeader: table.options.showHeader }],
    getSheets: () => [{ getSheetName: () => 'Sheet1', getSheetId: () => 'data' }] }
  expect(workbookTableOperations(disabled, workbook)).toEqual([])
  const bytes = await applyTableAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, name: 'NoHeader', columnNames: ['Name'], headerRow: false, bandedRows: false }])
  expect((await readWorkbook(bytes)).sheets[0]!.tables![0]).toMatchObject({ headerRowCount: 0, filterButton: false })
})
