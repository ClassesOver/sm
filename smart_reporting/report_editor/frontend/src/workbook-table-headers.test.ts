import { expect, it } from 'vitest'
import { tableHeaderProtectionReason } from './workbook-table-headers'

it('allows format-only paste without normalizing existing spaced names on protected consumers', () => {
  const workbook = { getId: () => 'book', getTableList: () => [{ subUnitId: 'sheet', name: 'Staff', showHeader: true,
    range: { startRow: 0, startColumn: 0 }, columns: [{ displayName: ' Name ' }] }],
    getSheets: () => [{ getSheetId: () => 'locked', getSheetName: () => 'Locked', getDataValidations: () => [],
      getSheet: () => ({ getCellMatrix: () => ({ forValue: (visit: any) => visit(0, 0, { f: '=SUM(Staff[ Name ])' }) }) }) }] }
  const command = { id: 'sheet.mutation.set-range-values', params: { unitId: 'book', subUnitId: 'sheet', cellValue: { 0: { 0: { s: { bl: 1 } } } } } }
  expect(tableHeaderProtectionReason(workbook, command, () => true)).toBeUndefined()
  command.params.cellValue[0][0] = { v: 'Employee' } as any
  expect(tableHeaderProtectionReason(workbook, command, () => true)).toContain('Locked')
})

import { afterEach } from 'vitest'
import { ICommandService, IUniverInstanceService, IUndoRedoService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin, SetRangeValuesMutation, SetRangeValuesUndoMutationFactory } from '@univerjs/sheets'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import { UniverSheetsDataValidationPlugin } from '@univerjs/sheets-data-validation'
import { UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import { ISheetClipboardService, mergeSetRangeValues } from '@univerjs/sheets-ui'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-table/facade'
import '@univerjs/sheets-data-validation/facade'
import { installTableHeaders } from './workbook-table-headers'
import { withWorkbookTables, workbookTableConfig } from './workbook-tables'

const instances: Univer[] = []
afterEach(() => instances.splice(0).forEach(instance => instance.dispose()))
function runtime(header = 'Name', protectedConsumer: boolean | ((id: string) => boolean) = false, implicit = false, columnChangeReason?: import('./workbook-table-pivot-source').TableColumnChangeReason, onRejected?: (message: string) => void) {
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  instances.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin)
  univer.registerPlugin(UniverSheetsDataValidationPlugin)
  univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  const data: any = { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.ZH_CN, sheetOrder: ['sheet'], sheets: { sheet: { id: 'sheet', name: 'Sheet1', rowCount: 20, columnCount: 20, cellData: { 0: { 0: { v: header, t: 1 }, 1: { v: 'Qty', t: 1 } }, 5: { 0: { f: `=SUM(Staff[${header}])+SUM(Staff[Qty])` } } } } } }
  const model: any = { sheets: [{ name: 'Sheet1', tables: [{ id: '1', name: 'Staff', displayName: 'Staff', range: { startRow: 0, endRow: 3, startColumn: 0, endColumn: 1 }, headerRowCount: 1, totalsRowCount: 0, columns: [{ id: '1', name: header }, { id: '2', name: 'Qty' }] }] }] }
  if (implicit) {
    Object.assign(data.sheets.sheet.cellData, { 1: { 0: { f: '=[@Qty]' }, 5: { f: '=[@Qty]' } },
      2: { 0: { f: '=SUM([Qty])' }, 5: { f: '=SUM(Staff[Qty])+SUM([Qty])' } },
      3: { 0: { f: '=[[#Data],[Qty]]' } }, 5: { 0: { f: '=[@Qty]' } } })
    Object.assign(data.sheets.sheet.cellData[0], { 5: { v: 'Name', t: 1 }, 6: { v: 'Qty', t: 1 } })
    model.sheets[0].tables.push({ ...structuredClone(model.sheets[0].tables[0]), id: '2', name: 'Other', displayName: 'Other',
      range: { startRow: 0, endRow: 3, startColumn: 5, endColumn: 6 } })
    data.sheetOrder.push('other')
    data.sheets.other = { id: 'other', name: 'Sheet2', rowCount: 20, columnCount: 20,
      cellData: { 0: { 0: { v: 'Name', t: 1 }, 1: { v: 'Qty', t: 1 } }, 1: { 0: { f: '=[@Qty]' }, 1: { f: '=SUM(Staff[Qty])' } } } }
    model.sheets.push({ name: 'Sheet2', tables: [{ ...structuredClone(model.sheets[0].tables[0]), id: '3', name: 'OtherSheet', displayName: 'OtherSheet' }] })
  }
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookTables(data as any, model as any))
  const api = FUniver.newAPI(univer), injector = univer.__getInjector()
  injector.get(IUniverInstanceService).focusUnit('book')
  const history = injector.get(IUndoRedoService), commands = injector.get(ICommandService)
  const hooks: any[] = []
  const clipboard = { getClipboardHooks: () => hooks, addClipboardHook(hook: any) { hooks.push(hook); hooks.sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0)); return { dispose() { hooks.splice(hooks.indexOf(hook), 1) } } },
    rePasteWithPasteType(): boolean {
      const previous = history.pitchTopUndoElement()
      if (previous) { previous.undoMutations.forEach(mutation => commands.syncExecuteCommand(mutation.id, mutation.params)); history.popUndoToRedo() }
      paste(); return true
    } }
  injector.add([ISheetClipboardService, { useValue: clipboard } as never])
  const installed = installTableHeaders({ univer, univerAPI: api }, id => typeof protectedConsumer === 'function' ? protectedConsumer(id) : protectedConsumer, columnChangeReason, onRejected)
  const write = (id: string, cellValue: any) => clipboard.addClipboardHook({ id, onPasteCells() { const params = { unitId: 'book', subUnitId: 'sheet', cellValue }; return { redos: [{ id: SetRangeValuesMutation.id, params }], undos: [{ id: SetRangeValuesMutation.id, params: injector.invoke(SetRangeValuesUndoMutationFactory, params) }] } } })
  const paste = () => {
    hooks.forEach(hook => hook.onBeforePaste?.())
    const batches = hooks.map(hook => hook.onPasteCells?.()).filter(Boolean)
    const redos = mergeSetRangeValues(batches.flatMap(batch => batch.redos)), undos = mergeSetRangeValues(batches.flatMap(batch => batch.undos))
    for (const mutation of redos) expect(commands.syncExecuteCommand(mutation.id, mutation.params)).toBe(true)
    history.pushUndoRedo({ unitID: 'book', redoMutations: redos, undoMutations: undos })
  }
  const sheet = api.getActiveWorkbook()!.getActiveSheet()!
  return { api, sheet, write, paste, clipboard, history, names: () => api.getActiveWorkbook()!.getTableList()[0].columns.map(column => column.displayName), dispose: () => installed.dispose() }
}
it('merges clear/value/style and multiple hooks into one table rename history', async () => {
  const current = runtime()
  current.write('clear', { 0: { 0: { v: null, p: null } } })
  current.write('values', { 0: { 0: { v: 'Employee' }, 1: { v: 'Cost' } } })
  current.write('styles-and-formula', { 0: { 0: { s: { bl: 1 } }, 2: { f: '=SUM(Staff[Name])', v: null } }, 5: { 0: { s: { bl: 1 } } } })
  current.paste()
  expect(current.names()).toEqual(['Employee', 'Cost'])
  expect(current.sheet.getRange(5, 0).getFormula()).toBe('=SUM(Staff[Employee])+SUM(Staff[Cost])')
  expect(current.sheet.getRange(0, 2).getFormula()).toBe('=SUM(Staff[Employee])')
  await current.api.undo()
  expect(current.names()).toEqual(['Name', 'Qty'])
  expect(current.sheet.getRange(0, 0).getValue()).toBe('Name')
  expect(current.sheet.getRange(0, 2).getFormula()).toBe('')
  expect(current.sheet.getRange(5, 0).getFormula()).toBe('=SUM(Staff[Name])+SUM(Staff[Qty])')
  await current.api.redo()
  expect(current.names()).toEqual(['Employee', 'Cost'])
  expect(current.sheet.getRange(0, 2).getFormula()).toBe('=SUM(Staff[Employee])')
  current.dispose()
})

it('rejects a cached field paste before changing headers, consumers or undo history', () => {
  const current = runtime('Name', false, false, (_table, names) => names.includes('Name') ? undefined : '透视缓存仍引用此表格字段')
  current.write('rename', { 0: { 0: { v: 'Employee' } } })
  expect(() => current.paste()).toThrow('透视缓存仍引用')
  expect(current.names()).toEqual(['Name', 'Qty'])
  expect(current.sheet.getRange(0, 0).getValue()).toBe('Name')
  expect(current.sheet.getRange(5, 0).getFormula()).toBe('=SUM(Staff[Name])+SUM(Staff[Qty])')
  current.dispose()
})

it('returns false for a cached header clear without changing any cells or column identities', async () => {
  const current = runtime('Name', false, false, (_table, names) => names.includes('Name') ? undefined : '透视缓存仍引用此表格字段')
  await expect(current.api.executeCommand('sheet.command.clear-selection-content', { unitId: 'book', subUnitId: 'sheet', ranges: [{ startRow: 0, endRow: 1, startColumn: 0, endColumn: 1 }] })).resolves.toBe(false)
  expect(current.names()).toEqual(['Name', 'Qty'])
  expect(current.sheet.getRange(0, 0).getValue()).toBe('Name')
  current.dispose()
})

it('restores the actual previous formatting paste and native history after a rejected re-paste', () => {
  const messages: string[] = [], current = runtime('Name', false, false, (_table, names) => names.includes('Name') ? undefined : '透视缓存仍引用', message => messages.push(message))
  const format = current.write('format', { 0: { 0: { s: { bl: 1 } } } })
  current.paste()
  const previous = current.history.pitchTopUndoElement(), previousRedo = current.history.pitchTopRedoElement()
  format.dispose(); current.write('values', { 0: { 0: { v: 'Employee' } } })
  expect(current.clipboard.rePasteWithPasteType()).toBe(false)
  expect(current.sheet.getSheet().getComposedCellStyle(0, 0)).toMatchObject({ bl: 1 })
  expect(current.sheet.getRange(0, 0).getValue()).toBe('Name')
  expect(current.names()).toEqual(['Name', 'Qty'])
  expect(current.history.pitchTopUndoElement()).toBe(previous)
  expect(current.history.pitchTopRedoElement()).toBe(previousRedo)
  expect(messages).toEqual(['透视缓存仍引用'])
  current.dispose()
})
it('preserves spaced names on format paste and rejects protected consumer rename before execution', () => {
  const current = runtime(' Name ', true)
  const formatting = current.write('format', { 0: { 0: { s: { bl: 1 } } } })
  current.paste()
  expect(current.names()).toEqual([' Name ', 'Qty'])
  expect(current.sheet.getRange(0, 0).getValue()).toBe(' Name ')
  formatting.dispose()
  current.write('rename', { 0: { 0: { v: 'Employee' } } })
  expect(() => current.paste()).toThrow('受保护')
  expect(current.names()).toEqual([' Name ', 'Qty'])
  expect(current.sheet.getRange(0, 0).getValue()).toBe(' Name ')
  current.dispose()
})

it('migrates implicit references only inside the renamed table with explicit consumers retaining workbook scope', async () => {
  const current = runtime('Name', false, true)
  expect(await current.api.executeCommand('sheet.command.set-range-values', {
    unitId: 'book', subUnitId: 'sheet', range: { startRow: 0, endRow: 0, startColumn: 1, endColumn: 1 }, value: { v: 'Cost' },
  })).toBe(true)
  expect(current.sheet.getRange(1, 0).getFormula()).toBe('=[@Cost]')
  expect(current.sheet.getRange(2, 0).getFormula()).toBe('=SUM([Cost])')
  expect(current.sheet.getRange(3, 0).getFormula()).toBe('=[[#Data],[Cost]]')
  expect(current.sheet.getRange(1, 5).getFormula()).toBe('=[@Qty]')
  expect(current.sheet.getRange(2, 5).getFormula()).toBe('=SUM(Staff[Cost])+SUM([Qty])')
  expect(current.sheet.getRange(5, 0).getFormula()).toBe('=[@Qty]')
  const other = current.api.getActiveWorkbook()!.getSheetBySheetId('other')!
  expect(other.getRange(1, 0).getFormula()).toBe('=[@Qty]')
  expect(other.getRange(1, 1).getFormula()).toBe('=SUM(Staff[Cost])')
  await current.api.undo()
  expect(current.names()).toEqual(['Name', 'Qty'])
  expect(current.sheet.getRange(1, 0).getFormula()).toBe('=[@Qty]')
  expect(current.sheet.getRange(2, 5).getFormula()).toBe('=SUM(Staff[Qty])+SUM([Qty])')
  await current.api.redo()
  expect(current.sheet.getRange(1, 0).getFormula()).toBe('=[@Cost]')
  current.dispose()
})

it('projects pasted implicit formulas by destination and does not resurrect cleared consumers', async () => {
  const current = runtime('Name', false, true)
  current.write('header-and-consumers', { 0: { 1: { v: 'Cost' } }, 1: { 0: { s: { bl: 1 } } },
    2: { 1: { f: '=SUM([Qty])', v: null } }, 3: { 0: null }, 5: { 3: { f: '=SUM([Qty])', v: null } } })
  current.paste()
  expect(current.sheet.getRange(1, 0).getFormula()).toBe('=[@Cost]')
  expect(current.sheet.getRange(2, 1).getFormula()).toBe('=SUM([Cost])')
  expect(current.sheet.getRange(3, 0).getFormula()).toBe('')
  expect(current.sheet.getRange(5, 3).getFormula()).toBe('=SUM([Qty])')
  await current.api.undo()
  expect(current.sheet.getRange(1, 0).getFormula()).toBe('=[@Qty]')
  expect(current.sheet.getRange(2, 1).getFormula()).toBe('')
  expect(current.sheet.getRange(3, 0).getFormula()).toBe('=[[#Data],[Qty]]')
  await current.api.redo()
  expect(current.sheet.getRange(2, 1).getFormula()).toBe('=SUM([Cost])')
  current.dispose()
})

it('includes owned implicit consumers in protection preflight without treating foreign implicit formulas as consumers', () => {
  const current = runtime('Name', true, true)
  current.sheet.getRange(2, 5).setValue(0)
  current.api.getActiveWorkbook()!.getSheetBySheetId('other')!.getRange(1, 1).setValue(0)
  current.write('protected-implicit', { 0: { 1: { v: 'Cost' } } })
  expect(() => current.paste()).toThrow('受保护')
  expect(current.names()).toEqual(['Name', 'Qty'])
  expect(current.sheet.getRange(1, 0).getFormula()).toBe('=[@Qty]')
  current.dispose()
})

it('allows rename when a protected other table has only a same-named implicit column reference', () => {
  const current = runtime('Name', id => id === 'other', true)
  const other = current.api.getActiveWorkbook()!.getSheetBySheetId('other')!
  other.getRange(1, 1).setValue(0)
  current.write('header', { 0: { 1: { v: 'Cost' } } })
  current.paste()
  expect(current.sheet.getRange(1, 0).getFormula()).toBe('=[@Cost]')
  expect(other.getRange(1, 0).getFormula()).toBe('=[@Qty]')
  current.dispose()
})

it('does not recreate implicit consumers cleared in the same table header clear command', async () => {
  const current = runtime('Name', false, true)
  expect(await current.api.executeCommand('sheet.command.clear-selection-content', {
    unitId: 'book', subUnitId: 'sheet', ranges: [{ startRow: 0, endRow: 3, startColumn: 0, endColumn: 1 }],
  })).toBe(true)
  expect(current.names()).toEqual(['Column1', 'Column2'])
  expect(current.sheet.getRange(1, 0).getFormula()).toBe('')
  expect(current.sheet.getRange(2, 0).getFormula()).toBe('')
  expect(current.sheet.getRange(3, 0).getFormula()).toBe('')
  expect(current.sheet.getRange(2, 5).getFormula()).toBe('=SUM(Staff[Column2])+SUM([Qty])')
  await current.api.undo()
  expect(current.names()).toEqual(['Name', 'Qty'])
  expect(current.sheet.getRange(1, 0).getFormula()).toBe('=[@Qty]')
  expect(current.sheet.getRange(3, 0).getFormula()).toBe('=[[#Data],[Qty]]')
  current.dispose()
})
