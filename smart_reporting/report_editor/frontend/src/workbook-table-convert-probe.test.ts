import { expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
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

// 此探针固定官方删除命令的现状，供后续转换功能设计使用；不代表拟定产品契约。
it.each([false, true])('probes official table deletion and undo with local list adapter %s', async localListAdapter => {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  const disposables: { dispose(): void }[] = []
  try {
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
    original.setTableFilterColumn(1, { filterType: TableColumnFilterTypeEnum.manual, values: ['2'], isAllSelected: false })
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
      table: manager.getTable('book', 'file-table-data-1')?.toJSON() ?? null,
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
    const before = snapshot()
    expect(await commands.executeCommand(DeleteSheetTableCommand.id, { unitId: 'book', subUnitId: 'data', tableId: 'file-table-data-1' })).toBe(true)
    const removed = snapshot()
    expect(await api.undo()).toBe(true)
    const undone = snapshot()
    expect(await api.redo()).toBe(true)
    const redone = snapshot()
    console.log('TABLE_CONVERT_PROBE', JSON.stringify({ localListAdapter, before, removed, undone, redone }))
    expect(removed.explicit).toEqual(['=SUM(#REF!)', ...before.explicit.slice(1)])
    expect(removed.implicit).toEqual(before.implicit)
    expect(removed.validations).toEqual(before.validations)
    expect(removed.names).toEqual(before.names)
    expect(undone.explicit).toEqual(before.explicit)
    expect(undone.table?.meta).toBeUndefined()
    expect(undone.table?.columns.map(column => column.id)).not.toEqual(before.table?.columns.map(column => column.id))
    expect(undone.table?.columns.every(column => column.formula === '' && Object.keys(column.meta).length === 0)).toBe(true)
    expect(undone.table?.filters.tableColumnFilterList).toEqual([])
    expect(undone.theme).toEqual(before.theme)
    expect(before.registryRange?.endRow).toBe(2)
    expect(undone.registryRange?.endRow).toBe(3)
    if (localListAdapter) {
      expect(before.forwardedListFormulas).toEqual(["='Data'!$B$2:$B$3", "='Data'!$B$2:$B$3"])
      expect(removed.forwardedListFormulas.length).toBeGreaterThanOrEqual(2)
      expect(new Set(removed.forwardedListFormulas)).toEqual(new Set(['=#NAME?']))
      expect(undone.forwardedListFormulas).toEqual(["='Data'!$B$2:$B$4", "='Data'!$B$2:$B$4"])
    }
    expect(removed.table).toBeNull()
    expect(removed.registered).toEqual({ Staff: false, Other: true })
    expect(removed.explicitCell).toEqual(before.explicitCell)
    expect(removed.totals).toBe(before.totals)
    expect(removed.theme).toBeNull()
    expect(redone.table).toBeNull()
  } finally {
    disposables.reverse().forEach(disposable => disposable.dispose())
    univer.dispose()
  }
})
