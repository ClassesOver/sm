import { afterEach, expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin, SetRangeValuesMutation } from '@univerjs/sheets'
import { IDefinedNamesService, ISuperTableService, UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import { UniverSheetsDataValidationPlugin } from '@univerjs/sheets-data-validation'
import { TableManager, UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-table/facade'
import '@univerjs/sheets-data-validation/facade'
import { withWorkbookTables, workbookTableConfig } from './workbook-tables'
import { withWorkbookDataValidations } from './workbook-data-validation'
import { installTableResize } from './workbook-table-resize'

const instances: Univer[] = []
afterEach(() => instances.splice(0).forEach(instance => instance.dispose()))
function setup(options: { protected?: string[]; headerless?: boolean; totals?: boolean; merges?: any[]; columnChangeReason?: import('./workbook-table-pivot-source').TableColumnChangeReason } = {}) {
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  instances.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin)
  univer.registerPlugin(UniverSheetsDataValidationPlugin)
  univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  const range = { startRow: 1, endRow: 4, startColumn: 1, endColumn: 2 }
  const totals = options.totals !== false
  const model = { sheets: [{ name: 'Data', tables: [{ id: '1', name: 'Staff', displayName: 'Staff', range,
    headerRowCount: options.headerless ? 0 : 1, totalsRowCount: totals ? 1 : 0,
    columns: [{ id: '11', name: 'Name' }, { id: '12', name: 'Qty' }] }] },
    { name: 'Consumers', dataValidations: { rules: [{ ranges: [{ startRow: 2, endRow: 3, startColumn: 0, endColumn: 0 }],
      rule: { type: 'list', formula1: '=Staff[Qty]', allowBlank: true, prompt: '保留' } }] } }] }
  const data = { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.ZH_CN, sheetOrder: ['data', 'consumers'], sheets: {
    data: { id: 'data', name: 'Data', rowCount: 100, columnCount: 1100, mergeData: options.merges ?? [], cellData: {
      1: { 1: { v: 'Name' }, 2: { v: 'Qty' } }, 2: { 1: { v: 'Ada' }, 2: { v: 1 } }, 3: { 1: { v: 'Grace' }, 2: { v: 2 } },
      ...(totals ? { 4: { 1: { v: 'Total', s: { bl: 1 } }, 2: { f: '=SUBTOTAL(109,C3:C4)', s: { bl: 1, n: { pattern: '0.00' } } } } } : {}),
    } }, consumers: { id: 'consumers', name: 'Consumers', rowCount: 20, columnCount: 20, cellData: {
      0: { 0: { f: '=SUM(Staff[Qty])' }, 1: { f: '=IF(A1,"Staff[Qty]",0)' } },
    } } } }
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookDataValidations(withWorkbookTables(data as any, model as any), model as any))
  const api = FUniver.newAPI(univer), injector = univer.__getInjector()
  injector.get(IUniverInstanceService).focusUnit('book')
  const names = injector.get(IDefinedNamesService)
  names.registerDefinedName('book', { id: 'qty', name: 'Quantity', formulaOrRefString: 'Staff[[Qty]]', comment: '保留' })
  const installed = installTableResize({ univer, univerAPI: api }, (id: string) => options.protected?.includes(id) ?? false, options.columnChangeReason)
  const workbook = api.getActiveWorkbook()!, sheet = workbook.getSheetBySheetId('data')!, consumer = workbook.getSheetBySheetId('consumers')!
  const commands = injector.get(ICommandService)
  const write = (cellValue: any) => commands.syncExecuteCommand(SetRangeValuesMutation.id, { unitId: 'book', subUnitId: 'data', cellValue })
  const unauthorized: string[] = []
  const guard = api.addEvent(api.Event.BeforeCommandExecute, command => {
    if (command.id === 'sheet.mutation.native-table-resize-state' || /^data-validation\.mutation\./.test(command.id)) {
      if (!installed.ownsMutation(command.params as object)) { unauthorized.push(command.id); command.cancel = true }
    }
  })
  const state = () => {
    const cells = structuredClone(sheet.getSheet().getCellMatrix().getData())
    for (const row of Object.values(cells) as any[]) for (const cell of Object.values(row) as any[]) {
      if (cell?.s) cell.s = workbook.getWorkbook().getStyles().getStyleByCell(cell)
      if (cell?.t === 1 && typeof cell.v === 'string') delete cell.t
    }
    return JSON.parse(JSON.stringify({ table: structuredClone(workbook.getTableList()[0]),
    cells, formula: consumer.getRange(0, 0).getFormula(),
    literal: consumer.getRange(0, 1).getFormula(), rule: structuredClone(consumer.getDataValidations()[0].rule),
    name: structuredClone(names.getValueById('book', 'qty')) }))
  }
  return { api, installed, write, sheet, consumer, names, state, unauthorized, tables: injector.get(TableManager), superTables: injector.get(ISuperTableService),
    dispose() { guard.dispose(); installed.dispose() } }
}

it('grows the full table and moves totals by absolute column with refreshed formulas and one undo/redo', async () => {
  const current = setup(), before = current.state()
  current.installed.resize('file-table-data-1', 'B2:D7')
  expect(current.state().table.range).toEqual({ startRow: 1, endRow: 6, startColumn: 1, endColumn: 3 })
  expect(current.state().table.columns.map((column: any) => [column.id, column.displayName]).slice(0, 2)).toEqual([['11', 'Name'], ['12', 'Qty']])
  expect(current.sheet.getRange(1, 3).getValue()).toBe('Column3')
  expect(current.sheet.getRange(4, 1).getValue()).toBeNull()
  expect(current.sheet.getRange(4, 2).getFormula()).toBe('')
  expect(current.sheet.getRange(6, 1).getValue()).toBe('Total')
  expect(current.sheet.getRange(6, 2).getFormula()).toBe('=SUBTOTAL(109,C3:C6)')
  expect(current.state().table.meta.nativeTotalsRowCount).toBe(1)
  expect(current.superTables.getTable('book', 'Staff')?.range).toEqual({ startRow: 1, endRow: 5, startColumn: 1, endColumn: 3 })
  const changed = current.state()
  await current.api.undo()
  expect(current.state()).toEqual(before)
  expect(current.superTables.getTable('book', 'Staff')?.range).toEqual({ ...before.table.range, endRow: before.table.range.endRow - 1 })
  await current.api.redo()
  expect(current.state()).toEqual(changed)
  expect(current.unauthorized).toEqual([])
  current.dispose()
})

it('rejects cached source column loss before moving totals, writing cells or adding history', async () => {
  const current = setup({ columnChangeReason: (_table, names) => names.includes('Qty') ? undefined : '透视缓存仍引用此表格字段' }), before = current.state()
  expect(() => current.installed.resize('file-table-data-1', 'B2:B5')).toThrow('透视缓存仍引用')
  expect(current.state()).toEqual(before)
  current.installed.resize('file-table-data-1', 'B2:C6')
  await current.api.undo()
  expect(current.state()).toEqual(before)
  current.dispose()
})

it('normalizes actual headers and migrates existing explicit consumers in the same transaction', async () => {
  const current = setup()
  current.write({ 1: { 2: { v: ' Count ' }, 3: { v: 'count' } } })
  const before = current.state()
  current.installed.resize('file-table-data-1', 'B2:D7')
  expect(current.state().table.columns.map((column: any) => column.displayName)).toEqual(['Name', 'Count', 'count2'])
  expect(current.sheet.getRange(1, 2).getValue()).toBe('Count')
  expect(current.state().formula).toBe('=SUM(Staff[Count])')
  expect(current.state().literal).toBe('=IF(A1,"Staff[Qty]",0)')
  expect(current.state().rule).toMatchObject({ formula1: '=Staff[Count]', prompt: '保留' })
  expect(current.state().name).toMatchObject({ formulaOrRefString: 'Staff[[Count]]', comment: '保留' })
  await current.api.undo()
  expect(current.state()).toEqual(before)
  current.dispose()
})

it('rewrites swapped column names once instead of chasing the rename map twice', () => {
  const current = setup()
  current.write({ 1: { 1: { v: 'Qty' }, 2: { v: 'Name' } } })
  current.installed.resize('file-table-data-1', 'B2:D7')
  expect(current.state().formula).toBe('=SUM(Staff[Name])')
  expect(current.state().rule.formula1).toBe('=Staff[Name]')
  current.dispose()
})

it('migrates implicit references once only for formulas inside the resized table', async () => {
  const current = setup()
  current.write({ 1: { 1: { v: 'Qty' }, 2: { v: 'Name' } }, 2: {
    1: { f: '=SUM([@Qty])+SUM(Staff[Qty])+IF(1,"[Qty]",0)' },
    3: { f: '=SUM([Qty])' }, 4: { f: '=SUM([Qty])' },
  } })
  const before = current.state()
  current.installed.resize('file-table-data-1', 'B2:D7')
  expect(current.sheet.getRange(2, 1).getFormula()).toBe('=SUM([@Name])+SUM(Staff[Name])+IF(1,"[Qty]",0)')
  expect(current.sheet.getRange(2, 3).getFormula()).toBe('=SUM([Name])')
  expect(current.sheet.getRange(2, 4).getFormula()).toBe('=SUM([Qty])')
  expect(current.state().formula).toBe('=SUM(Staff[Name])')
  await current.api.undo()
  expect(current.state()).toEqual(before)
  current.dispose()
})

it('keeps headerless column identities anchored to sheet columns when expanding left', async () => {
  const current = setup({ headerless: true, totals: false }), before = current.state()
  current.installed.resize('file-table-data-1', 'A1:D6')
  expect(current.state().table.showHeader).toBe(false)
  expect(current.state().table.columns.map((column: any) => column.displayName)).toEqual(['Column1', 'Name', 'Qty', 'Column4'])
  expect(current.state().table.columns.slice(1, 3).map((column: any) => column.id)).toEqual(['11', '12'])
  expect(current.state().cells).toEqual(before.cells)
  await current.api.undo()
  expect(current.state()).toEqual(before)
  current.dispose()
})

it('supports consecutive resizes and same-row horizontal expansion while preserving totals styles and metadata', async () => {
  const current = setup(), before = current.state()
  current.installed.resize('file-table-data-1', 'A2:D5')
  expect(current.sheet.getRange(4, 1).getValue()).toBe('Total')
  expect(current.sheet.getRange(4, 2).getFormula()).toBe('=SUBTOTAL(109,C3:C4)')
  expect(current.state().table.columns.slice(1, 3).map((column: any) => column.id)).toEqual(['11', '12'])
  const first = current.state()
  current.installed.resize('file-table-data-1', 'A2:D8')
  expect(current.sheet.getRange(7, 2).getFormula()).toBe('=SUBTOTAL(109,C3:C7)')
  expect(current.state().cells[7][2].s).toMatchObject({ bl: 1, n: { pattern: '0.00' } })
  expect(current.state().table.meta).toEqual(before.table.meta)
  await current.api.undo()
  expect(current.state()).toEqual(first)
  await current.api.undo()
  expect(current.state()).toEqual(before)
  current.dispose()
})

it('checks other table overlap and protected local names before any writes', () => {
  const other = setup()
  other.tables.addTable('book', 'data', 'Other', { startRow: 1, endRow: 6, startColumn: 4, endColumn: 4 }, ['Other'], 'other-table')
  const beforeOther = other.state()
  expect(() => other.installed.resize('file-table-data-1', 'B2:E7')).toThrow('交叠')
  expect(other.state()).toEqual(beforeOther)
  other.dispose()
  const local = setup({ protected: ['locked-scope'] })
  local.names.registerDefinedName('book', { id: 'local', name: 'LocalQty', localSheetId: 'locked-scope', formulaOrRefString: '=Staff[Qty]' })
  local.write({ 1: { 2: { v: 'Count' } } })
  const beforeLocal = local.state()
  expect(() => local.installed.resize('file-table-data-1', 'B2:D7')).toThrow('受保护')
  expect(local.state()).toEqual(beforeLocal)
  local.dispose()
})

it('shrinks onto occupied data without moving old totals, and refreshes the new totals formula', async () => {
  const current = setup()
  current.write({ 3: { 2: { f: '=SUBTOTAL(103,C3:C3)' } } })
  const before = current.state()
  current.installed.resize('file-table-data-1', 'B2:C4')
  expect(current.sheet.getRange(3, 1).getValue()).toBe('Grace')
  expect(current.sheet.getRange(3, 2).getFormula()).toBe('=SUBTOTAL(103,C3:C3)')
  expect(current.sheet.getRange(4, 2).getFormula()).toBe('=SUBTOTAL(109,C3:C4)')
  await current.api.undo()
  expect(current.state()).toEqual(before)
  current.dispose()
})

it('moves totals into a free shrink destination and keeps a no-op out of undo history', async () => {
  const current = setup()
  expect(current.installed.resize('file-table-data-1', '$B$2:$C$5')).toBe(true)
  expect(await current.api.undo()).toBe(false)
  current.write({ 3: { 1: { v: null, f: null }, 2: { v: null, f: null } } })
  const before = current.state()
  current.installed.resize('file-table-data-1', 'B2:C4')
  expect(current.sheet.getRange(3, 1).getValue()).toBe('Total')
  expect(current.sheet.getRange(3, 2).getFormula()).toBe('=SUBTOTAL(109,C3:C3)')
  expect(current.sheet.getRange(4, 1).getValue()).toBeNull()
  expect(current.sheet.getRange(4, 2).getFormula()).toBe('')
  await current.api.undo()
  expect(current.state()).toEqual(before)
  current.dispose()
})

it.each(['B3:D7', 'E2:F7', 'B2:C3', 'B2:ALN7', 'A0:C7', 'B2:C1048577', 'Other!B2:C7'])('rejects invalid range %s before writes or history', async address => {
  const current = setup(), before = current.state()
  expect(() => current.installed.resize('file-table-data-1', address)).toThrow()
  expect(current.state()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  current.dispose()
})

it.each(['value', 'formula'])('rejects growth onto an occupied totals destination (%s) before writes', async kind => {
  const current = setup()
  current.write({ 6: { 1: kind === 'value' ? { v: 'occupied' } : { f: '=IF(1,"","")', v: '' } } })
  const before = current.state()
  expect(() => current.installed.resize('file-table-data-1', 'B2:D7')).toThrow('汇总行')
  expect(current.state()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  current.dispose()
})

it.each(['data', 'consumers'])('rejects protected %s without partial writes', async protectedSheet => {
  const current = setup({ protected: [protectedSheet] })
  current.write({ 1: { 2: { v: 'Count' } } })
  const before = current.state()
  expect(() => current.installed.resize('file-table-data-1', 'B2:D7')).toThrow('受保护')
  expect(current.state()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  current.dispose()
})

it('rejects merge conflicts before writes and rolls back when a consumer mutation is cancelled', async () => {
  const merged = setup({ merges: [{ startRow: 2, endRow: 2, startColumn: 3, endColumn: 4 }] }), beforeMerge = merged.state()
  expect(() => merged.installed.resize('file-table-data-1', 'B2:D7')).toThrow('合并')
  expect(merged.state()).toEqual(beforeMerge)
  merged.dispose()
  const current = setup()
  current.write({ 1: { 2: { v: 'Count' } } })
  const before = current.state()
  const reject = current.api.addEvent(current.api.Event.BeforeCommandExecute, command => {
    if (command.id === 'data-validation.mutation.updateRule') command.cancel = true
  })
  expect(() => current.installed.resize('file-table-data-1', 'B2:D7')).toThrow('撤销')
  expect(current.state()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  reject.dispose(); current.dispose()
})

it('rolls back a state mutation when its nested formula registry mutation is cancelled', async () => {
  const current = setup(), before = current.state()
  const reject = current.api.addEvent(current.api.Event.BeforeCommandExecute, command => {
    if (command.id === 'formula.mutation.set-super-table') command.cancel = true
  })
  expect(() => current.installed.resize('file-table-data-1', 'B2:D7')).toThrow('撤销')
  expect(current.state()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  reject.dispose(); current.dispose()
})
