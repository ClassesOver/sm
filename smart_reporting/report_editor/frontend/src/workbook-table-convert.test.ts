import { afterEach, expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, IUndoRedoService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { SheetRangeThemeModel, UniverSheetsPlugin } from '@univerjs/sheets'
import { IDefinedNamesService, ISuperTableService, UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import { DataValidationFormulaService, UniverSheetsDataValidationPlugin } from '@univerjs/sheets-data-validation'
import { DeleteSheetTableCommand, TableColumnFilterTypeEnum, TableManager, UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-table/facade'
import '@univerjs/sheets-data-validation/facade'
import { withWorkbookTables, workbookTableConfig, workbookTableOperations } from './workbook-tables'
import { withWorkbookDataValidations } from './workbook-data-validation'
import { installNativeTableStyleRendering } from './workbook-table-styles'
import { installTableFormulaReferences } from './workbook-table-formulas'
import { installDataValidationNames } from './workbook-data-validation-names'
import { installTableConvert } from './workbook-table-convert'

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).reverse().forEach(cleanup => cleanup()))
function setup(localListAdapter = false, protectedSheets: string[] = []) {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  const disposables: { dispose(): void }[] = []

    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverFormulaEnginePlugin)
    univer.registerPlugin(UniverSheetsFormulaPlugin)
    univer.registerPlugin(UniverSheetsDataValidationPlugin)
    univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
    const table = (id: string, name: string, column: number) => ({ id, name, displayName: name,
      range: { startRow: 0, endRow: 3, startColumn: column, endColumn: column + 1 }, headerRowCount: 1, totalsRowCount: name === 'Staff' ? 1 : 0,
      columns: [{ id: '11', name: 'Name' }, { id: '22', name: 'Qty' }],
      style: { name: 'TableStyleMedium2', showRowStripes: true, showColumnStripes: false, showFirstColumn: true, showLastColumn: false } })
    const model = { sheets: [{ name: 'Data', tables: [table('1', 'Staff', 0), table('2', 'Other', 5)] },
      { name: 'Consumers', dataValidations: { rules: [
        { ranges: [{ startRow: 2, endRow: 2, startColumn: 0, endColumn: 0 }], rule: { type: 'list', formula1: '=Staff[Qty]', allowBlank: true } },
        { ranges: [{ startRow: 3, endRow: 3, startColumn: 0, endColumn: 0 }], rule: { type: 'list', formula1: '=Employees', allowBlank: true } },
        { ranges: [{ startRow: 4, endRow: 4, startColumn: 0, endColumn: 0 }], rule: { type: 'custom', formula1: '=SUM(Staff[Qty])>0', allowBlank: true } },
      ] } }] }
    const data = { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.EN_US, sheetOrder: ['data', 'consumers'], sheets: {
      data: { id: 'data', name: 'Data', rowCount: 20, columnCount: 20, cellData: {
        0: { 0: { v: 'Name' }, 1: { v: 'Qty' }, 5: { v: 'Name' }, 6: { v: 'Qty' } },
        1: { 0: { f: '=[@Qty]' }, 1: { v: 2, s: { bg: { rgb: '#FF0000' } } }, 5: { f: '=[@Qty]' }, 6: { v: 7 } },
        2: { 0: { f: '=SUM([Qty])' }, 1: { v: 3 } }, 3: { 0: { v: 'Total' }, 1: { f: '=SUBTOTAL(109,B2:B3)' } },
      } }, consumers: { id: 'consumers', name: 'Consumers', rowCount: 20, columnCount: 20, cellData: { 0: {
        0: { f: '=SUM(Staff[Qty])' }, 1: { f: '=SUM(staff[Qty])' }, 2: { f: '=SUM(STAFF[Qty])' },
        3: { f: '=SUM(Other[Qty])' }, 4: { f: '="Staff[Qty]"' },
      } } },
    } }
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookDataValidations(withWorkbookTables(data as any, model as any), model as any))
    const api = FUniver.newAPI(univer), injector = univer.__getInjector(), workbook = api.getActiveWorkbook()!
    injector.get(IUniverInstanceService).focusUnit('book')
    disposables.push(installTableFormulaReferences({ univer }), installNativeTableStyleRendering(injector))
    const names = injector.get(IDefinedNamesService), manager = injector.get(TableManager)
    names.registerDefinedName('book', { id: 'global', name: 'Employees', formulaOrRefString: 'Staff[Qty]', comment: 'global marker' })
    names.registerDefinedName('book', { id: 'local', name: 'LocalEmployees', localSheetId: 'consumers', formulaOrRefString: 'Staff[Qty]', comment: 'local marker' })
    const original = manager.getTable('book', 'file-table-data-1')!
    original.setTableMeta({ ...original.getTableMeta(), probe: { preserve: true } })
    original.setColumns(original.toJSON().columns.map((column: any) => ({ ...column, meta: { probe: column.id }, formula: '=1+1' })))
    manager.addFilter('book', 'file-table-data-1', 1, { filterType: TableColumnFilterTypeEnum.manual, values: ['2'], isAllSelected: false })
    const formulas = injector.get(DataValidationFormulaService), actualAdd = formulas.addRule
    const forwardedListFormulas: string[] = []
    // 只观测实际委托入参，始终执行官方方法，不替换计算结果。
    formulas.addRule = function (unitId, subUnitId, rule) {
      if (rule.type === 'list') forwardedListFormulas.push(rule.formula1 ?? '')
      return actualAdd.call(this, unitId, subUnitId, rule)
    }
    disposables.push({ dispose() { formulas.addRule = actualAdd } })
    if (localListAdapter) disposables.push(installDataValidationNames({ univer, univerAPI: api }))
    const commands = injector.get(ICommandService), registry = injector.get(ISuperTableService), themes = injector.get(SheetRangeThemeModel)
    const sheet = workbook.getSheetBySheetId('data')!, consumer = workbook.getSheetBySheetId('consumers')!
    const snapshot = () => ({
      filtered: [1, 2, 3].map(row => sheet.getSheet().isRowFiltered(row)),
      other: structuredClone(manager.getTable('book', 'file-table-data-2')!.toJSON()),
      rawCells: structuredClone(sheet.getSheet().getCellMatrix().getData()),
      table: structuredClone(manager.getTable('book', 'file-table-data-1')?.toJSON() ?? null),
      explicit: Array.from({ length: 5 }, (_, col) => consumer.getRange(0, col).getFormula()),
      implicit: [sheet.getRange(1, 0).getFormula(), sheet.getRange(2, 0).getFormula(), sheet.getRange(1, 5).getFormula()],
      validations: consumer.getDataValidations().map(({ rule }) => structuredClone(rule)),
      validationFormulaInfo: consumer.getDataValidations().map(({ rule }) => structuredClone(injector.get(DataValidationFormulaService).getRuleFormulaInfo('book', 'consumers', rule.uid))),
      names: structuredClone(names.getDefinedNameMap('book')),
      theme: themes.getCellStyle('book', 'data', 0, 0) ?? null,
      header: sheet.getSheet().getComposedCellStyle(0, 0) ?? null,
      explicitCell: structuredClone(sheet.getSheet().getCellMatrix().getValue(1, 1)),
      totals: sheet.getRange(3, 1).getFormula(),
      forwardedListFormulas: forwardedListFormulas.splice(0),
      registryRange: structuredClone(registry.getTable('book', 'Staff')?.range ?? null),
      registered: { Staff: registry.hasTable('book', 'Staff'), Other: registry.hasTable('book', 'Other') },
      operations: workbookTableOperations(model as any, workbook),
    })
    const installed = installTableConvert({ univer, univerAPI: api }, id => protectedSheets.includes(id))
    disposables.push(installed)
    cleanups.push(() => { disposables.reverse().forEach(disposable => disposable.dispose()); univer.dispose() })
    return { installed, snapshot, api, commands, injector, workbook, history: injector.get(IUndoRedoService) }
}

it.each([false, true])('converts with official consumers and restores full table state with local list adapter %s', async localListAdapter => {
  const { installed, snapshot, api } = setup(localListAdapter)
    const before = structuredClone(snapshot())
    expect(installed.convert('file-table-data-1')).toBe(true)
    const removed = snapshot()
    expect(await api.undo()).toBe(true)
    const undone = snapshot()
    expect(await api.redo()).toBe(true)
    const redone = snapshot()
    expect(removed.explicit).toEqual(['=SUM(#REF!)', ...before.explicit.slice(1)])
    expect(removed.implicit).toEqual(before.implicit)
    expect(before.filtered).toContain(true)
    expect(removed.filtered).toEqual([false, false, false])
    expect(undone.filtered).toEqual(before.filtered)
    expect(removed.rawCells).toEqual(before.rawCells)
    expect(removed.other).toEqual(before.other)
    expect(removed.validations).toEqual(before.validations)
    expect(removed.names).toEqual(before.names)
    expect(undone.explicit).toEqual(before.explicit)
    expect(undone.table).toEqual(before.table)
    expect(undone.theme).toEqual(before.theme)
    expect(before.registryRange?.endRow).toBe(2)
    expect(undone.registryRange).toEqual(before.registryRange)
    if (localListAdapter) {
      expect(before.forwardedListFormulas).toEqual(["='Data'!$B$2:$B$3", "='Data'!$B$2:$B$3"])
      expect(removed.forwardedListFormulas.length).toBeGreaterThanOrEqual(2)
      expect(new Set(removed.forwardedListFormulas)).toEqual(new Set(['=#NAME?']))
      expect(undone.forwardedListFormulas.slice(-2)).toEqual(["='Data'!$B$2:$B$3", "='Data'!$B$2:$B$3"])
    }
    expect(removed.table).toBeNull()
    expect(removed.registered).toEqual({ Staff: false, Other: true })
    expect(removed.explicitCell).toEqual(before.explicitCell)
    expect(removed.totals).toBe(before.totals)
    expect(removed.theme).toBeNull()
    expect(redone.table).toBeNull()
})


it.each(['data', 'consumers'])('refuses protected %s before mutations and undo history', async protectedSheet => {
  const { installed, snapshot, history } = setup(false, [protectedSheet]), before = structuredClone(snapshot())
  expect(() => installed.convert('file-table-data-1')).toThrow('受保护')
  expect(snapshot()).toEqual(before)
  expect(history.pitchTopUndoElement()).toBeNull()
})

it('refuses stale disposed and forged conversion calls', async () => {
  const { installed, snapshot, commands, history } = setup(), before = structuredClone(snapshot())
  expect(() => installed.convert('missing')).toThrow('不存在')
  expect(commands.syncExecuteCommand('sheet.mutation.native-table-convert', { steps: [] })).toBe(false)
  expect(commands.syncExecuteCommand('sheet.mutation.native-table-convert-state', { restore: false })).toBe(false)
  expect(snapshot()).toEqual(before)
  expect(history.pitchTopUndoElement()).toBeNull()
  installed.dispose()
  expect(() => installed.convert('file-table-data-1')).toThrow('已关闭')
})

it.each(['delete', 'consumer', 'delete-before', 'consumer-before'])('restores all state and history after a %s mutation fails', async fault => {
  const { installed, snapshot, commands, history } = setup(), before = structuredClone(snapshot())
  const original = commands.syncExecuteCommand.bind(commands)
  let injected = false
  commands.syncExecuteCommand = (id, params, options) => {
    if (!injected && id === (fault.startsWith('delete') ? 'sheet.mutation.delete-table' : 'sheet.mutation.set-range-values')) {
      injected = true
      if (fault.endsWith('-before')) throw new Error('conversion fault')
      const result = original(id, params, options)
      expect(result).toBe(true)
      throw new Error('conversion fault')
    }
    return original(id, params, options)
  }
  try { expect(() => installed.convert('file-table-data-1')).toThrow('conversion fault') }
  finally { commands.syncExecuteCommand = original }
  expect(injected).toBe(true)
  expect(snapshot()).toEqual(before)
  expect(history.pitchTopUndoElement()).toBeNull()
})

it('saves conversion through real table removal operations and reopens with explicit cells unchanged', async () => {
  const { applyCellEdits, applyTableAdditions, createBlankWorkbook, readWorkbook, createBufferEntrySource } = await import('@sheets-web/xlsx-engine')
  const { applyWorkbookOperations } = await import('../../../reporting/workbook_engine/bridge/operations')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { readBackSnapshot } = await import('./workbook-vendor/grid/sync')
  const { diffToEdits } = await import('./workbook-vendor/core/session-core')
  const original = await applyTableAdditions(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' }, style: { fillColor: '#FF0000', fontColor: '#00FF00', bold: false } },
    { sheetName: 'Sheet1', row: 4, column: 0, writeValue: true, cell: { value: null, formula: '=COUNTA(Staff[Name])' } },
  ]), [{ worksheetSheetName: 'Sheet1', name: 'Staff', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, columnNames: ['Name'], style: 'TableStyleMedium2', bandedRows: true }])
  const model = await readWorkbook(original), univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  cleanups.push(() => univer.dispose())
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin)
  univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookTables(buildWorkbookData(model, 'saved-book', 'saved'), model))
  const api = FUniver.newAPI(univer), workbook = api.getActiveWorkbook()!
  univer.__getInjector().get(IUniverInstanceService).focusUnit('saved-book')
  const installed = installTableConvert({ univer, univerAPI: api })
  cleanups.push(() => installed.dispose())
  expect(installed.convert(`file-table-sheet-0-${model.sheets[0]!.tables![0]!.id}`)).toBe(true)
  const tableOps = workbookTableOperations(model, workbook)
  expect(tableOps).toEqual([{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', remove: true }] }])
  const edits = diffToEdits(model, readBackSnapshot(await workbook.save()))
  expect(edits).toHaveLength(1)
  expect(edits[0]).toMatchObject({ row: 4, column: 0, cell: { formula: '=COUNTA(#REF!)' } })
  const converted = await applyWorkbookOperations(original, [...tableOps, { kind: 'applyCellEdits', edits }]), reopened = await readWorkbook(converted)
  expect(reopened.sheets[0]!.tables ?? []).toEqual([])
  expect(reopened.sheets[0]!.cells.A1).toEqual(model.sheets[0]!.cells.A1)
  expect(reopened.sheets[0]!.cells.A2).toEqual(model.sheets[0]!.cells.A2)
  expect(reopened.sheets[0]!.cells.A5?.formula).toBe('=COUNTA(#REF!)')
  const beforeZip = await createBufferEntrySource(original), afterZip = await createBufferEntrySource(converted)
  expect((await afterZip.paths()).filter(path => path.startsWith('xl/tables/'))).toEqual([])
  expect(await afterZip.readText('xl/styles.xml')).toBe(await beforeZip.readText('xl/styles.xml'))
  await api.undo()
  expect(workbookTableOperations(model, workbook)).toEqual([])
  expect(diffToEdits(model, readBackSnapshot(await workbook.save()))).toEqual([])
})


it('authorizes nested official table mutations while keeping one undo step', async () => {
  const { installed, api, snapshot, history } = setup(), before = structuredClone(snapshot()), unauthorized: string[] = []
  const listener = api.addEvent(api.Event.BeforeCommandExecute, command => {
    if (['sheet.mutation.delete-table', 'sheet.mutation.add-table', 'sheet.mutation.native-table-convert', 'sheet.mutation.native-table-convert-state'].includes(command.id) && !installed.ownsMutation(command.params as object)) {
      unauthorized.push(command.id)
      command.cancel = true
    }
  })
  try {
    installed.convert('file-table-data-1')
    expect(await api.undo()).toBe(true)
    expect(snapshot()).toEqual(before)
    expect(history.pitchTopUndoElement()).toBeNull()
    expect(unauthorized).toEqual([])
  } finally { listener.dispose() }
})

it('preserves the empty filter list exactly when converting and undoing a newly created table', async () => {
  const { installed, injector, api } = setup()
  const manager = injector.get(TableManager), table = manager.getTable('book', 'file-table-data-1')!
  table.getTableFilters().fromJSON({ tableColumnFilterList: [] })
  const before = structuredClone(table.toJSON())
  installed.convert('file-table-data-1')
  await api.undo()
  expect(manager.getTable('book', 'file-table-data-1')!.toJSON()).toEqual(before)
})
