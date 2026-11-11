import { afterEach, expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, IUndoRedoService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { IDefinedNamesService, ISuperTableService, UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import { UniverSheetsDataValidationPlugin } from '@univerjs/sheets-data-validation'
import { UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-table/facade'
import '@univerjs/sheets-data-validation/facade'
import { withWorkbookTables, workbookTableConfig } from './workbook-tables'
import { withWorkbookDataValidations } from './workbook-data-validation'
import { installTableDesign } from './workbook-table-design'

const instances: Univer[] = []
afterEach(() => instances.splice(0).forEach(instance => instance.dispose()))
function setup(protectedSheets: string[] = []) {
  const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: {} } })
  instances.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin)
  univer.registerPlugin(UniverSheetsDataValidationPlugin)
  univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  const table = (id: string, name: string, column: number) => ({ id, name, displayName: name,
    range: { startRow: 0, endRow: 3, startColumn: column, endColumn: column }, headerRowCount: 1, totalsRowCount: 0,
    columns: [{ id: '1', name: 'Name' }] })
  const model = { sheets: [{ name: 'Data', tables: [table('1', 'Staff', 0), table('2', 'Other', 5)] },
    { name: 'Consumers', dataValidations: { rules: [{ ranges: [{ startRow: 2, endRow: 3, startColumn: 0, endColumn: 0 }],
      rule: { type: 'list', formula1: '=Staff[Name]', allowBlank: true, prompt: '选择员工' } }] } }] }
  const data = { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.ZH_CN, sheetOrder: ['data', 'consumers'],
    sheets: { data: { id: 'data', name: 'Data', rowCount: 20, columnCount: 20, cellData: { 0: { 0: { v: 'Name', t: 1 }, 5: { v: 'Name', t: 1 } }, 1: { 0: { v: 'Ada', t: 1 } } } },
      consumers: { id: 'consumers', name: 'Consumers', rowCount: 20, columnCount: 20,
        cellData: { 0: { 0: { f: '=COUNTA(Staff[Name])' }, 1: { f: '=IF(A1,"Staff[Name]",Other[Name])' } } } } } }
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookDataValidations(withWorkbookTables(data as any, model as any), model as any))
  const api = FUniver.newAPI(univer), injector = univer.__getInjector()
  injector.get(IUniverInstanceService).focusUnit('book')
  const names = injector.get(IDefinedNamesService)
  names.registerDefinedName('book', { id: 'employees', name: 'Employees', formulaOrRefString: 'Staff[[Name]]', comment: '保留注释' })
  const installed = installTableDesign({ univer, univerAPI: api }, (id: string) => protectedSheets.includes(id))
  const commands = injector.get(ICommandService), history = injector.get(IUndoRedoService)
  const unauthorized: string[] = []
  const guard = api.addEvent(api.Event.BeforeCommandExecute, command => {
    if (command.id === 'sheet.mutation.set-sheet-table' || /^data-validation\.mutation\./.test(command.id)) {
      if (!installed.ownsMutation(command.params as object)) { unauthorized.push(command.id); command.cancel = true }
    }
  })
  const workbook = api.getActiveWorkbook()!, consumer = workbook.getSheetBySheetId('consumers')!
  const state = () => ({ name: workbook.getTableList().find(item => item.id === 'file-table-data-1')!.name,
    formula: consumer.getRange(0, 0).getFormula(), untouched: consumer.getRange(0, 1).getFormula(),
    validation: consumer.getDataValidations()[0].rule,
    definedName: names.getValueById('book', 'employees') })
  return { installed, api, state, names, commands, history, unauthorized, superTables: injector.get(ISuperTableService), dispose() { guard.dispose(); installed.dispose() } }
}

it('renames table and explicit consumers atomically in one undo/redo history and supports a second rename', async () => {
  const current = setup(), before = current.state()
  expect(current.installed.rename('file-table-data-1', 'People')).toBe(true)
  expect(current.superTables.hasTable('book', 'Staff')).toBe(false)
  expect(current.superTables.hasTable('book', 'People')).toBe(true)
  expect(current.state()).toEqual({ ...before, name: 'People', formula: '=COUNTA(People[Name])',
    validation: { ...before.validation, formula1: '=People[Name]' },
    definedName: { ...before.definedName, formulaOrRefString: 'People[[Name]]' } })
  await current.api.undo()
  expect(current.state()).toEqual(before)
  expect(current.superTables.hasTable('book', 'Staff')).toBe(true)
  expect(current.superTables.hasTable('book', 'People')).toBe(false)
  await current.api.redo()
  expect(current.state().name).toBe('People')
  expect(current.installed.rename('file-table-data-1', '员工表')).toBe(true)
  expect(current.state().formula).toBe('=COUNTA(员工表[Name])')
  await current.api.undo()
  expect(current.state().name).toBe('People')
  expect(current.state().formula).toBe('=COUNTA(People[Name])')
  expect(current.unauthorized).toEqual([])
  current.dispose()
})

it.each(['data', 'consumers'])('refuses protected %s before any mutation or history change', async protectedSheet => {
  const current = setup([protectedSheet]), before = current.state()
  expect(() => current.installed.rename('file-table-data-1', 'People')).toThrow('受保护')
  expect(current.state()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  current.dispose()
})

it.each(['A1', 'r1c1', 'RC', '1Name', 'Bad Name', 'a'.repeat(256), '', 'other', 'employees'])('refuses invalid or conflicting name %s before writes', name => {
  const current = setup(), before = current.state()
  expect(() => current.installed.rename('file-table-data-1', name)).toThrow()
  expect(current.state()).toEqual(before)
  current.dispose()
})

it('normalizes name input, preserves a no-op history and rejects stale table identity', async () => {
  const current = setup(), before = current.state()
  expect(current.installed.rename('file-table-data-1', ' Staff ')).toBe(true)
  expect(current.state()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  expect(() => current.installed.rename('missing', 'People')).toThrow('不存在')
  current.dispose()
})

it('supports case-only renames and backslash names while retaining undo history', async () => {
  const current = setup()
  expect(current.installed.rename('file-table-data-1', 'staff')).toBe(true)
  expect(current.state().name).toBe('staff')
  expect(current.state().formula).toBe('=COUNTA(staff[Name])')
  expect(current.installed.rename('file-table-data-1', '\\People')).toBe(true)
  expect(current.state().formula).toBe('=COUNTA(\\People[Name])')
  await current.api.undo()
  expect(current.state().name).toBe('staff')
  current.dispose()
})

it('checks protected local defined names before writing any planned consumer changes', () => {
  const current = setup(['locked-name-scope']), before = current.state()
  current.names.registerDefinedName('book', { id: 'local', name: 'LocalEmployees', localSheetId: 'locked-name-scope', formulaOrRefString: 'Staff[Name]' })
  expect(() => current.installed.rename('file-table-data-1', 'People')).toThrow('受保护')
  expect(current.state()).toEqual(before)
  expect(current.names.getValueById('book', 'local')?.formulaOrRefString).toBe('Staff[Name]')
  current.dispose()
})

it('rolls back already executed mutations when a later mutation is cancelled', async () => {
  const current = setup(), before = current.state()
  const reject = current.api.addEvent(current.api.Event.BeforeCommandExecute, command => {
    if (command.id === 'data-validation.mutation.updateRule') command.cancel = true
  })
  expect(() => current.installed.rename('file-table-data-1', 'People')).toThrow('未执行')
  expect(current.state()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  reject.dispose()
  current.dispose()
})
