import { afterEach, expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin, SetRangeValuesMutation, SheetRangeThemeModel } from '@univerjs/sheets'
import { ISuperTableService, UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import { TableManager, UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-table/facade'
import { withWorkbookTables, workbookTableConfig, workbookTableOperations } from './workbook-tables'
import { installTableTotals } from './workbook-table-totals'
import { installNativeTableStyleRendering } from './workbook-table-styles'
import { installTableStyleEdit } from './workbook-table-style-edit'
import { applyCellEdits, applyTableAdditions, applyTableEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'

const instances: Univer[] = []
afterEach(() => instances.splice(0).forEach(instance => instance.dispose()))
function setup(last: unknown[] = [1, 2], protectedSheet = false, merge = false) {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  instances.push(univer)
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin); univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  const model = { sheets: [{ name: 'Data', tables: [{ id: '1', name: 'Staff', displayName: 'Staff',
    range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 1 }, headerRowCount: 1, totalsRowCount: 0,
    style: { name: 'TableStyleMedium9', showRowStripes: true, showColumnStripes: false, showFirstColumn: false, showLastColumn: false },
    columns: [{ id: '11', name: 'Name' }, { id: '12', name: 'Qty' }] }] }] }
  const data = { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.EN_US, sheetOrder: ['data'],
    sheets: { data: { id: 'data', name: 'Data', rowCount: 20, columnCount: 20, mergeData: merge ? [{ startRow: 3, endRow: 3, startColumn: 1, endColumn: 2 }] : [], cellData: { 0: { 0: { v: 'Name' }, 1: { v: 'Qty' } },
      1: { 0: { v: 'Ada' }, 1: { v: last[0] } }, 2: { 0: { v: 'Grace' }, 1: { v: last[1] } } } } } }
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookTables(data as any, model as any))
  const api = FUniver.newAPI(univer), injector = univer.__getInjector()
  injector.get(IUniverInstanceService).focusUnit('book')
  const installed = installTableTotals({ univer, univerAPI: api }, () => protectedSheet)
  const rendering = installNativeTableStyleRendering(injector)
  const workbook = api.getActiveWorkbook()!, sheet = workbook.getActiveSheet()!, tables = injector.get(TableManager)
  const state = () => JSON.parse(JSON.stringify({ table: tables.getTable('book', 'file-table-data-1')!.toJSON(),
    cells: sheet.getSheet().getCellMatrix().getData() }))
  const write = (cellValue: any) => injector.get(ICommandService).syncExecuteCommand(SetRangeValuesMutation.id, { unitId: 'book', subUnitId: 'data', cellValue })
  return { api, installed, sheet, tables, state, write, rendering, injector, workbook, model, themes: injector.get(SheetRangeThemeModel), registry: injector.get(ISuperTableService) }
}

it.each([[1, 2, 109], ['a', 'b', 103], [null, '', 103]])('enables totals using data type %s/%s and one undo history', async (a, b, code) => {
  const current = setup([a, b])
  const before = current.state().table
  expect(current.installed.setTotals('file-table-data-1', true)).toBe(true)
  expect(current.sheet.getRange(3, 0).getValue()).toBe('Total')
  expect(current.sheet.getRange(3, 1).getFormula()).toBe(`=SUBTOTAL(${code},B2:B3)`)
  expect(current.state().table).toMatchObject({ range: { endRow: 3 }, options: { showFooter: true }, meta: { nativeTotalsRowCount: 1 }, columns: before.columns, filters: before.filters })
  expect(current.registry.getTable('book', 'Staff')!.range.endRow).toBe(2)
  await current.api.undo()
  expect(current.state().table).toEqual(before)
  expect(current.sheet.getRange(3, 0).getValue()).toBeNull()
  await current.api.redo()
  expect(current.sheet.getRange(3, 1).getFormula()).toBe(`=SUBTOTAL(${code},B2:B3)`)
  current.installed.dispose()
})

it('disables totals, retains other style components and supports undo', async () => {
  const current = setup()
  current.installed.setTotals('file-table-data-1', true)
  current.write({ 3: { 1: { f: '=SUBTOTAL(109,B2:B3)', s: { bg: { rgb: '#FF0000' }, n: { pattern: '0.00' }, bl: 1 } } } })
  const before = current.state().table
  current.installed.setTotals('file-table-data-1', false)
  expect(current.sheet.getRange(3, 0).getValue()).toBeNull()
  expect(current.sheet.getRange(3, 1).getFormula()).toBe('')
  expect(current.sheet.getRange(3, 1).getCellStyleData()?.bl).toBe(0)
  expect(current.state().table).toMatchObject({ range: { endRow: 2 }, options: { showFooter: false }, meta: { nativeTotalsRowCount: 0 } })
  await current.api.undo()
  expect(current.state().table).toEqual(before)
  expect(current.sheet.getRange(3, 1).getFormula()).toBe('=SUBTOTAL(109,B2:B3)')
  current.installed.dispose()
})

it('updates official theme totals band and preserves column/filter/meta identities across repeated toggles', async () => {
  const current = setup(), before = current.state().table
  current.installed.setTotals('file-table-data-1', true)
  expect(current.themes.getCellStyle('book', 'data', 3, 1)).toMatchObject({ bg: { rgb: '#4472C4' }, bl: 1 })
  current.installed.setTotals('file-table-data-1', false)
  expect(current.themes.getCellStyle('book', 'data', 3, 1)).toBeUndefined()
  expect(current.state().table.columns).toEqual(before.columns)
  expect(current.state().table.filters).toEqual(before.filters)
  expect(current.installed.setTotals('file-table-data-1', false)).toBe(true)
  await current.api.undo()
  expect(current.state().table.options.showFooter).toBe(true)
  expect(current.themes.getCellStyle('book', 'data', 3, 1)).toMatchObject({ bg: { rgb: '#4472C4' }, bl: 1 })
  current.installed.dispose(); current.rendering.dispose()
})

it('preserves edited and None style metadata while producing the actual totals save diff', async () => {
  const current = setup(), styles = installTableStyleEdit({ univer: { __getInjector: () => current.injector }, univerAPI: current.api })
  styles.setStyle('file-table-data-1', 'TableStyleDark2')
  const before = current.state().table
  current.installed.setTotals('file-table-data-1', true)
  expect(current.state().table.meta.nativeTableStyleName).toBe('TableStyleDark2')
  expect(current.themes.getCellStyle('book', 'data', 3, 1)).toMatchObject({ bl: 1, cl: { rgb: '#FFFFFF' } })
  expect(workbookTableOperations(current.model as any, current.workbook)).toEqual([{ kind: 'applyTableEdits', edits: [{
    worksheetSheetName: 'Data', tableName: 'Staff', area: { startRow: 0, endRow: 3, startColumn: 0, endColumn: 1 }, totalsRow: true, style: 'TableStyleDark2',
  }] }])
  await current.api.undo()
  expect(current.state().table).toEqual(before)
  styles.setStyle('file-table-data-1', '')
  current.installed.setTotals('file-table-data-1', true)
  expect(current.state().table.meta.nativeTableStyleName).toBe('')
  expect(current.themes.getCellStyle('book', 'data', 3, 1) ?? {}).toEqual({})
  styles.dispose(); current.installed.dispose(); current.rendering.dispose()
})

it.each(['value', 'formula', 'protected', 'merge', 'table'])('refuses %s before writing cells or undo history', async kind => {
  const current = setup([1, 2], kind === 'protected', kind === 'merge')
  if (kind === 'value') current.write({ 3: { 0: { v: 'occupied' } } })
  if (kind === 'formula') current.write({ 3: { 0: { f: '=IF(1,"","")', v: '' } } })
  if (kind === 'table') current.tables.addTable('book', 'data', 'Other', { startRow: 3, endRow: 4, startColumn: 0, endColumn: 1 }, ['A', 'B'], 'other')
  const before = current.state()
  expect(() => current.installed.setTotals('file-table-data-1', true)).toThrow()
  expect(current.state()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  current.installed.dispose()
})

it('rolls back cells and state on nested formula registration failure', async () => {
  const current = setup(), before = current.state().table
  const reject = current.api.addEvent(current.api.Event.BeforeCommandExecute, command => { if (command.id === 'formula.mutation.set-super-table') command.cancel = true })
  expect(() => current.installed.setTotals('file-table-data-1', true)).toThrow('撤销')
  expect(current.state().table).toEqual(before)
  expect(current.sheet.getRange(3, 0).getValue()).toBeNull()
  expect(await current.api.undo()).toBe(false)
  reject.dispose(); current.installed.dispose()
})

it('writes enabled and disabled totals through the actual engine roundtrip', async () => {
  let bytes = await applyTableAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 1 }, columnNames: ['Name', 'Qty'], bandedRows: true }])
  bytes = await applyCellEdits(bytes, [{ sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 1 } }, { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 2 } }])
  const current = setup()
  current.installed.setTotals('file-table-data-1', true)
  bytes = await applyCellEdits(bytes, [{ sheetName: 'Sheet1', row: 3, column: 0, writeValue: true, cell: { value: current.sheet.getRange(3, 0).getValue() as string }, style: { bold: true } },
    { sheetName: 'Sheet1', row: 3, column: 1, writeValue: true, cell: { value: null, formula: current.sheet.getRange(3, 1).getFormula() }, style: { bold: true } }])
  bytes = await applyTableEdits(bytes, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', area: current.state().table.range, totalsRow: true }])
  const enabled = await readWorkbook(bytes)
  expect(enabled.sheets[0]!.tables![0]).toMatchObject({ totalsRowCount: 1, range: { endRow: 3 } })
  expect(enabled.sheets[0]!.cells.B4.formula).toBe('=SUBTOTAL(109,B2:B3)')
  current.installed.setTotals('file-table-data-1', false)
  bytes = await applyCellEdits(bytes, [{ sheetName: 'Sheet1', row: 3, column: 0, writeValue: true, cell: { value: null }, style: { bold: current.sheet.getRange(3, 0).getCellStyleData()?.bl === 1 } },
    { sheetName: 'Sheet1', row: 3, column: 1, writeValue: true, cell: { value: null }, style: { bold: current.sheet.getRange(3, 1).getCellStyleData()?.bl === 1 } }])
  bytes = await applyTableEdits(bytes, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', area: current.state().table.range, totalsRow: false }])
  const disabled = await readWorkbook(bytes)
  expect(disabled.sheets[0]!.tables![0]).toMatchObject({ totalsRowCount: 0, range: { endRow: 2 } })
  const xf = disabled.styles.cellXfs[disabled.sheets[0]!.cells.B4.styleIndex!]!
  expect(disabled.styles.fonts[xf.fontId]?.bold ?? false).toBe(false)
  current.installed.dispose()
})
