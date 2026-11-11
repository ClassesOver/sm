import { expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, LocaleType, Univer, UniverInstanceType, type Workbook } from '@univerjs/core'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { ISuperTableService, SetSuperTableMutation, UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { SetSheetTableMutation, TableManager, UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import { withWorkbookTables, workbookTableConfig } from './workbook-tables'
import { installTableFormulaReferences } from './workbook-table-formulas'

it('excludes totals from formula registration across load, rename, resize and workbook recreation', () => {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  try {
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverFormulaEnginePlugin)
    univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
    const range = { startRow: 0, endRow: 3, startColumn: 0, endColumn: 0 }
    const model = { sheets: [{ name: 'Data', tables: [{ id: '1', name: 'Staff', displayName: 'Staff', range,
      headerRowCount: 1, totalsRowCount: 1, columns: [{ id: '1', name: 'Qty' }] }] }] }
    const data = { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.EN_US,
      sheetOrder: ['data'], sheets: { data: { id: 'data', name: 'Data', rowCount: 20, columnCount: 20,
        cellData: { 0: { 0: { v: 'Qty' } }, 1: { 0: { v: 1 } }, 2: { 0: { v: 2 } }, 3: { 0: { f: '=SUBTOTAL(109,A2:A3)' } } } } } }
    univer.createUnit<object, Workbook>(UniverInstanceType.UNIVER_SHEET, withWorkbookTables(structuredClone(data), model as any))
    const installed = installTableFormulaReferences({ univer })
    const injector = univer.__getInjector(), registry = injector.get(ISuperTableService), commands = injector.get(ICommandService)
    const tables = injector.get(TableManager)
    expect(registry.getTable('book', 'Staff')!.range.endRow).toBe(2)
    expect(tables.getTable('book', 'file-table-data-1')!.getRange().endRow).toBe(3)
    expect(commands.syncExecuteCommand(SetSheetTableMutation.id, { unitId: 'book', tableId: 'file-table-data-1', config: { name: 'People' } })).toBe(true)
    expect(registry.getTable('book', 'People')!.range.endRow).toBe(2)
    tables.updateTableRange('book', 'file-table-data-1', { newRange: { ...range, endRow: 6 } })
    expect(registry.getTable('book', 'People')!.range.endRow).toBe(5)
    expect(commands.syncExecuteCommand(SetSuperTableMutation.id, { unitId: 'book', tableName: 'People',
      reference: { range: { ...range, endRow: 6 }, sheetId: 'data', titleMap: new Map([['Cost', 0]]) } })).toBe(true)
    expect(registry.getTable('book', 'People')!.titleMap.get('Cost')).toBe(0)
    expect(registry.getTable('book', 'People')!.range.endRow).toBe(5)
    injector.get(IUniverInstanceService).disposeUnit('book')
    univer.createUnit<object, Workbook>(UniverInstanceType.UNIVER_SHEET, withWorkbookTables(structuredClone(data), model as any))
    expect(registry.getTable('book', 'Staff')!.range.endRow).toBe(2)
    expect(tables.getTable('book', 'file-table-data-1')!.getRange().endRow).toBe(3)
    installed.dispose()
  } finally { univer.dispose() }
})

it('resolves real headerless data, all, headers and totals without inventing a header row', async () => {
  const { IFormulaCurrentConfigService, IFormulaRuntimeService, ReferenceNodeFactory } = await import('@univerjs/engine-formula')
  const { resolveTableListSource } = await import('./workbook-tables')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  await import('@univerjs/sheets/facade'); await import('@univerjs/sheets-table/facade')
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  let installed: ReturnType<typeof installTableFormulaReferences> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin)
    univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
    const range = { startRow: 0, endRow: 3, startColumn: 0, endColumn: 0 }
    const { applyCellEdits, createBlankWorkbook, readWorkbook } = await import('@sheets-web/xlsx-engine')
    const { applyWorkbookOperations } = await import('../../../reporting/workbook_engine/bridge/operations')
    const cells = await applyCellEdits(await createBlankWorkbook(), [10, 20, 30].map((value, row) => ({
      sheetName: 'Sheet1', row, column: 0, writeValue: true, cell: { value },
    })))
    const source = await applyWorkbookOperations(cells, [
      { kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Sheet1', area: range, name: 'Staff', columnNames: ['Qty'], bandedRows: true, headerRow: false }] },
      { kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', totalsRow: true }] },
    ])
    const model = await readWorkbook(source)
    expect(model.sheets[0]!.tables?.[0]).toMatchObject({ headerRowCount: 0, totalsRowCount: 1, columns: [{ name: 'Qty' }] })
    univer.createUnit<object, Workbook>(UniverInstanceType.UNIVER_SHEET, withWorkbookTables({ id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.EN_US,
      sheetOrder: ['data'], sheets: { data: { id: 'data', name: 'Sheet1', rowCount: 20, columnCount: 20,
        cellData: { 0: { 0: { v: 10 } }, 1: { 0: { v: 20 } }, 2: { 0: { v: 30 } }, 3: { 0: { f: '=SUM(A1:A3)' } } } } } }, model as any))
    installed = installTableFormulaReferences({ univer })
    const injector = univer.__getInjector(), config = injector.get(IFormulaCurrentConfigService), factory = injector.get(ReferenceNodeFactory)
    config.setExecuteUnitId('book'); config.setExecuteSubUnitId('data')
    const node = (token: string) => factory.checkAndCreateNodeType(token) as any
    const bounds = (token: string) => node(token)._tableReferenceObject.getRangeData()
    expect(bounds('Staff[Qty]')).toMatchObject({ startRow: 0, endRow: 2 })
    expect(bounds('Staff[#Data]')).toMatchObject({ startRow: 0, endRow: 2 })
    config.loadDataLite()
    injector.get(IFormulaRuntimeService).setCurrent(5, 5, 20, 20, 'data', 'book')
    const dataNode = node('Staff[Qty]'); dataNode.execute()
    expect(dataNode.getValue().toArrayValueObject().getArrayValue().map((row: any[]) => row.map(cell => cell.getValue()))).toEqual([[10], [20], [30]])
    expect(bounds('Staff[[#Data],[Qty]]')).toMatchObject({ startRow: 0, endRow: 2 })
    for (const row of [0, 1, 2]) {
      injector.get(IFormulaRuntimeService).setCurrent(row, 1, 20, 20, 'data', 'book')
      const current = node('Staff[[#This Row],[Qty]]'); current.execute()
      expect(current.getValue().toArrayValueObject().getArrayValue()[0][0].getValue()).toBe((row + 1) * 10)
    }
    expect(bounds('Staff[#All]')).toMatchObject({ startRow: 0, endRow: 3 })
    expect(bounds('Staff[#Totals]')).toMatchObject({ startRow: 3, endRow: 3 })
    const noHeader = node('Staff[#Headers]'); noHeader.execute()
    expect(noHeader.getValue().getValue()).toBe('#REF!')
    const workbook = FUniver.newAPI(univer).getActiveWorkbook()!
    expect(resolveTableListSource('=Staff[Qty]', workbook)).toBe("='Sheet1'!$A$1:$A$3")
    const table = injector.get(TableManager).getTable('book', 'file-table-data-1')!
    expect(table.getRange()).toEqual(range)
    // 同一张表切换为有表头，注册时保持真实范围，数据首行向下移一格。
    table.setShowHeader(true)
    injector.get(ICommandService).syncExecuteCommand(SetSuperTableMutation.id, { unitId: 'book', tableName: 'Staff',
      reference: { range, sheetId: 'data', titleMap: new Map([['Qty', 0]]) } })
    expect(bounds('Staff[Qty]')).toMatchObject({ startRow: 1, endRow: 2 })
    expect(bounds('Staff[#Headers]')).toMatchObject({ startRow: 0, endRow: 0 })
    expect(bounds('Staff[#All]')).toMatchObject({ startRow: 0, endRow: 3 })
    expect(resolveTableListSource('=Staff[Qty]', workbook)).toBe("='Sheet1'!$A$2:$A$3")
    table.setShowHeader(false)
    table.getTableMeta().nativeTotalsRowCount = 0
    injector.get(ICommandService).syncExecuteCommand(SetSuperTableMutation.id, { unitId: 'book', tableName: 'Staff',
      reference: { range, sheetId: 'data', titleMap: new Map([['Qty', 0]]) } })
    expect(bounds('Staff[Qty]')).toMatchObject({ startRow: 0, endRow: 3 })
    const noTotals = node('Staff[#Totals]'); noTotals.execute()
    expect(noTotals.getValue().getValue()).toBe('#REF!')
    expect(table.getRange()).toEqual(range)
  } finally { installed?.dispose(); univer.dispose() }
})
