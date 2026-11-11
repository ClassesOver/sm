import { afterEach, expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin, SheetRangeThemeModel } from '@univerjs/sheets'
import { TableManager, UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-table/facade'
import { withWorkbookTables, workbookTableConfig, workbookTableOperations } from './workbook-tables'
import { installNativeTableStyleRendering } from './workbook-table-styles'
import { installTableStyleEdit, type TableStyleOption } from './workbook-table-style-edit'
import { applyCellEdits, applyTableAdditions, applyTableEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import { installTableTotals } from './workbook-table-totals'

const instances: Univer[] = []
afterEach(() => instances.splice(0).forEach(instance => instance.dispose()))
function setup(protectedSheet = false, totals = false) {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  instances.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  if (totals) { univer.registerPlugin(UniverFormulaEnginePlugin); univer.registerPlugin(UniverSheetsFormulaPlugin) }
  univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  const style = { name: 'TableStyleMedium2', showRowStripes: true, showColumnStripes: false, showFirstColumn: false, showLastColumn: false }
  const model = { themePalette: ['#FFFFFF', '#000000', '#EEEEEE', '#222222', '#008800'], sheets: [{ name: 'Data', tables: [0, 3].map((column, index) => ({
    id: String(index + 1), name: `Table${index}`, displayName: `Table${index}`, range: { startRow: 0, endRow: 3, startColumn: column, endColumn: column + 1 },
    columns: [{ id: '1', name: 'Name' }, { id: '2', name: 'Qty' }], headerRowCount: 1, totalsRowCount: 0, style,
  })) }] }
  const data = { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.EN_US, sheetOrder: ['data'], sheets: { data: {
    id: 'data', name: 'Data', rowCount: 20, columnCount: 20, cellData: { 0: { 0: { v: 'Name' }, 1: { v: 'Qty' }, 3: { v: 'Name' }, 4: { v: 'Qty' } },
      1: { 0: { v: 'Ada' }, 1: { f: '=1+1', v: 2, s: { bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' }, bl: 0 } } } },
  } } }
  const loaded = withWorkbookTables(data as any, model as any)
  // 本模块仅消费root集成的来源meta契约，不依赖其是否已同步写入。
  const resource = loaded.resources.find((item: { name: string; data: string }) => item.name === 'SHEET_TABLE_PLUGIN')!
  const tables = JSON.parse(resource.data)
  for (const table of tables.data.tables) table.meta = { ...table.meta, nativeTableStyle: structuredClone(style), nativeThemePalette: model.themePalette, other: 'keep' }
  resource.data = JSON.stringify(tables)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, loaded)
  const injector = univer.__getInjector(), api = FUniver.newAPI(univer)
  injector.get(IUniverInstanceService).focusUnit('book')
  const rendering = installNativeTableStyleRendering(injector), installed = installTableStyleEdit({ univer, univerAPI: api }, () => protectedSheet)
  const sheet = api.getActiveWorkbook()!.getActiveSheet()!.getSheet(), manager = injector.get(TableManager)
  const table = () => manager.getTable('book', 'file-table-data-1')!
  return { univer, api, sheet, table, rendering, installed, injector, cells: structuredClone(sheet.getCellMatrix().getData()),
    rawStyles: structuredClone(api.getActiveWorkbook()!.getSnapshot().styles), dispose() { installed.dispose(); rendering.dispose() } }
}

it('switches builtin styles independently with workbook colors and a single undo/redo history without cell edits', async () => {
  const current = setup(), beforeMeta = structuredClone(current.table().getTableMeta())
  expect(current.installed.setStyle('file-table-data-1', 'TableStyleDark2')).toBe(true)
  expect(current.sheet.getComposedCellStyle(0, 0)).toMatchObject({ bg: { rgb: '#000000' }, cl: { rgb: '#FFFFFF' } })
  expect(current.sheet.getComposedCellStyle(0, 3)).toMatchObject({ bg: { rgb: '#008800' } })
  expect(current.sheet.getComposedCellStyle(1, 1)).toMatchObject({ bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' } })
  expect(current.table().getTableMeta()).toMatchObject({ nativeTableStyleName: 'TableStyleDark2', nativeTableStyle: { ...beforeMeta.nativeTableStyle, name: 'TableStyleDark2' }, other: 'keep' })
  expect(current.sheet.getCellMatrix().getData()).toEqual(current.cells)
  expect(current.api.getActiveWorkbook()!.getSnapshot().styles).toEqual(current.rawStyles)
  await current.api.undo()
  expect(current.table().getTableMeta()).toEqual(beforeMeta)
  expect(current.sheet.getComposedCellStyle(0, 0)).toMatchObject({ bg: { rgb: '#008800' } })
  await current.api.redo()
  expect(current.sheet.getComposedCellStyle(0, 0)).toMatchObject({ bg: { rgb: '#000000' } })
  current.installed.setStyle('file-table-data-1', 'TableStyleLight2')
  expect(current.sheet.getComposedCellStyle(0, 0)?.cl).toEqual({ rgb: '#006600' })
  expect(current.sheet.getCellMatrix().getData()).toEqual(current.cells)
  current.dispose()
})

it('uses an empty theme for None without inventing header bold, and restores the previous theme', async () => {
  const current = setup()
  expect(current.installed.setStyle('file-table-data-1', '')).toBe(true)
  expect(current.table().getTableMeta().nativeTableStyleName).toBe('')
  expect(current.sheet.getComposedCellStyle(0, 0)?.bg).toBeUndefined()
  expect(current.sheet.getComposedCellStyle(0, 0)?.bl).toBeUndefined()
  current.rendering.refresh()
  expect(current.sheet.getComposedCellStyle(0, 0)?.bg).toBeUndefined()
  await current.api.undo()
  expect(current.sheet.getComposedCellStyle(0, 0)).toMatchObject({ bg: { rgb: '#008800' }, bl: 1 })
  await current.api.redo()
  expect(current.sheet.getComposedCellStyle(0, 0)?.bl).toBeUndefined()
  expect(current.sheet.getCellMatrix().getData()).toEqual(current.cells)
  current.dispose()
})

it.each(['TableStyleLight22', 'TableStyleMedium29', 'TableStyleDark12', 'CustomStyle', 'TableStyleLight01'])('rejects unsupported style %s before writes', style => {
  const current = setup(), before = structuredClone(current.table().getTableMeta())
  expect(() => current.installed.setStyle('file-table-data-1', style)).toThrow('样式')
  expect(current.table().getTableMeta()).toEqual(before)
  current.dispose()
})

it('rejects protected tables and stale identities before theme/meta writes', async () => {
  const current = setup(true), before = structuredClone(current.table().getTableMeta())
  expect(() => current.installed.setStyle('file-table-data-1', 'TableStyleDark2')).toThrow('受保护')
  expect(() => current.installed.setStyle('missing', 'TableStyleDark2')).toThrow('不存在')
  expect(current.table().getTableMeta()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  current.dispose()
})

it('rejects forged mutation parameters and rolls back a theme registration failure without history', async () => {
  const current = setup(), before = structuredClone(current.table().getTableMeta())
  const commands = current.injector.get(ICommandService), themes = current.injector.get(SheetRangeThemeModel)
  expect(commands.syncExecuteCommand('sheet.mutation.native-table-style', { unitId: 'book', tableId: 'file-table-data-1', state: {} })).toBe(false)
  const original = themes.registerRangeThemeStyle.bind(themes)
  let injected = false
  themes.registerRangeThemeStyle = (unitId, theme) => {
    if (!injected) { injected = true; throw new Error('theme fault') }
    original(unitId, theme)
  }
  expect(() => current.installed.setStyle('file-table-data-1', 'TableStyleDark2')).toThrow('theme fault')
  themes.registerRangeThemeStyle = original
  expect(current.table().getTableMeta()).toEqual(before)
  expect(current.sheet.getComposedCellStyle(0, 0)).toMatchObject({ bg: { rgb: '#008800' } })
  expect(await current.api.undo()).toBe(false)
  expect(current.sheet.getCellMatrix().getData()).toEqual(current.cells)
  current.dispose()
})

it.each(['TableStyleDark2', ''])('retains style %s after official resource save and workbook rebuild', async style => {
  const current = setup()
  current.installed.setStyle('file-table-data-1', style)
  const saved = await current.api.getActiveWorkbook()!.save()
  current.injector.get(IUniverInstanceService).disposeUnit('book')
  current.api.createWorkbook(saved)
  const sheet = current.api.getActiveWorkbook()!.getActiveSheet()!.getSheet()
  expect(sheet.getComposedCellStyle(0, 0)?.bg?.rgb).toBe(style ? '#000000' : undefined)
  expect(sheet.getCellMatrix().getData()).toEqual(current.cells)
  expect(current.table().getTableMeta().nativeTableStyleName).toBe(style)
  current.dispose()
})


it.each(['TableStyleDark3', ''])('round-trips style %s through real table save operations without changing cell parts or style flags', async style => {
  const original = await applyTableEdits(await applyTableAdditions(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' }, style: { fillColor: '#FF0000', fontColor: '#00FF00', bold: false } },
  ]), [{ worksheetSheetName: 'Sheet1', name: 'Staff', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 },
    columnNames: ['Name'], style: 'TableStyleMedium2', bandedRows: true }]),
  [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', firstColumn: true, lastColumn: true, bandedColumns: true }])
  const baseline = await readWorkbook(original), before = baseline.sheets[0]!.tables![0]!
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  instances.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookTables(buildWorkbookData(baseline, 'roundtrip', 'roundtrip'), baseline))
  const api = FUniver.newAPI(univer), injector = univer.__getInjector()
  injector.get(IUniverInstanceService).focusUnit('roundtrip')
  const installed = installTableStyleEdit({ univer, univerAPI: api })
  const workbook = api.getActiveWorkbook()!, sheet = workbook.getActiveSheet()!
  const cells = structuredClone(sheet.getSheet().getCellMatrix().getData())
  expect(workbookTableOperations(baseline, workbook)).toEqual([])
  expect(installed.setStyle(`file-table-${sheet.getSheetId()}-${before.id}`, style)).toBe(true)
  const operations = workbookTableOperations(baseline, workbook)
  expect(operations).toEqual([{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', style }] }])
  const bytes = await applyWorkbookOperations(original, operations), reopened = await readWorkbook(bytes)
  expect(reopened.sheets[0]!.tables![0]!.style).toEqual({ ...before.style, name: style || undefined })
  expect(reopened.sheets[0]!.cells).toEqual(baseline.sheets[0]!.cells)
  expect(sheet.getSheet().getCellMatrix().getData()).toEqual(cells)
  const sourceZip = await createBufferEntrySource(original), savedZip = await createBufferEntrySource(bytes)
  expect(await savedZip.paths()).toEqual(await sourceZip.paths())
  for (const path of await sourceZip.paths()) {
    if (!path.startsWith('xl/tables/')) expect(await savedZip.readText(path)).toBe(await sourceZip.readText(path))
  }
  await api.undo()
  expect(workbookTableOperations(baseline, workbook)).toEqual([])
  await api.redo()
  expect(workbookTableOperations(baseline, workbook)).toEqual(operations)
  installed.dispose()
})


const optionCases: [TableStyleOption, boolean, number, number, 'bl' | 'bg', unknown][] = [
  ['showFirstColumn', true, 1, 0, 'bl', 1],
  ['showLastColumn', true, 2, 1, 'bl', 1],
  ['showRowStripes', false, 1, 0, 'bg', undefined],
  ['showColumnStripes', true, 2, 0, 'bg', { rgb: '#B4FFB4' }],
]
it.each(optionCases)('edits %s using the official theme with one history and no cell format writes', async (option, enabled, row, column, key, expected) => {
  const current = setup(), before = structuredClone(current.table().getTableMeta())
  expect(current.installed.setOption('file-table-data-1', option, enabled)).toBe(true)
  expect(current.table().getTableMeta().nativeTableStyle).toEqual({ ...before.nativeTableStyle, [option]: enabled })
  expect(current.sheet.getComposedCellStyle(row, column)?.[key]).toEqual(expected)
  expect(current.sheet.getComposedCellStyle(1, 1)).toMatchObject({ bg: { rgb: '#FF0000' }, cl: { rgb: '#00FF00' }, bl: 0 })
  expect(current.sheet.getComposedCellStyle(1, 3)?.bl).toBeUndefined()
  expect(current.sheet.getCellMatrix().getData()).toEqual(current.cells)
  expect(current.api.getActiveWorkbook()!.getSnapshot().styles).toEqual(current.rawStyles)
  current.installed.setOption('file-table-data-1', option, enabled)
  await current.api.undo()
  expect(current.table().getTableMeta()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  await current.api.redo()
  expect(current.table().getTableMeta().nativeTableStyle[option]).toBe(enabled)
  current.dispose()
})

it('keeps options across None builtin style and totals rebuilds with separate undo steps', async () => {
  const current = setup(false, true), totals = installTableTotals({ univer: current.univer, univerAPI: current.api })
  current.installed.setStyle('file-table-data-1', '')
  current.installed.setOption('file-table-data-1', 'showFirstColumn', true)
  current.installed.setOption('file-table-data-1', 'showColumnStripes', true)
  expect(current.sheet.getComposedCellStyle(1, 0)?.bl).toBeUndefined()
  expect(current.sheet.getComposedCellStyle(1, 0)?.bg).toBeUndefined()
  totals.setTotals('file-table-data-1', true)
  expect(current.sheet.getComposedCellStyle(1, 0)?.bl).toBeUndefined()
  current.installed.setStyle('file-table-data-1', 'TableStyleLight2')
  expect(current.table().getTableMeta().nativeTableStyle).toMatchObject({ showFirstColumn: true, showColumnStripes: true })
  expect(current.sheet.getComposedCellStyle(1, 0)?.bl).toBe(1)
  await current.api.undo()
  expect(current.sheet.getComposedCellStyle(1, 0)?.bl).toBeUndefined()
  expect(current.table().getTableMeta().nativeTotalsRowCount).toBe(1)
  await current.api.undo()
  expect(current.table().getTableMeta().nativeTotalsRowCount).toBe(0)
  expect(current.table().getTableMeta().nativeTableStyle.showColumnStripes).toBe(true)
  await current.api.undo()
  expect(current.table().getTableMeta().nativeTableStyle.showColumnStripes).toBe(false)
  totals.dispose(); current.dispose()
})

it('rejects invalid protected stale and disposed option edits before writes', async () => {
  const current = setup(true), before = structuredClone(current.table().getTableMeta())
  expect(() => current.installed.setOption('file-table-data-1', 'showFirstColumn', true)).toThrow('受保护')
  expect(() => current.installed.setOption('missing', 'showFirstColumn', true)).toThrow('不存在')
  expect(() => current.installed.setOption('file-table-data-1', 'name' as TableStyleOption, true)).toThrow('选项')
  expect(() => current.installed.setOption('file-table-data-1', 'showFirstColumn', 'true' as any)).toThrow('选项')
  expect(current.table().getTableMeta()).toEqual(before)
  expect(await current.api.undo()).toBe(false)
  current.dispose()
  expect(() => current.installed.setOption('file-table-data-1', 'showFirstColumn', true)).toThrow('已关闭')
})

it('rolls back failed option registration without retaining metadata or history', async () => {
  const current = setup(), before = structuredClone(current.table().getTableMeta()), themes = current.injector.get(SheetRangeThemeModel)
  const original = themes.registerRangeThemeStyle.bind(themes)
  let injected = false
  themes.registerRangeThemeStyle = (unitId, theme) => {
    if (!injected) { injected = true; throw new Error('option theme fault') }
    original(unitId, theme)
  }
  expect(() => current.installed.setOption('file-table-data-1', 'showFirstColumn', true)).toThrow('option theme fault')
  themes.registerRangeThemeStyle = original
  expect(current.table().getTableMeta()).toEqual(before)
  expect(current.sheet.getComposedCellStyle(1, 0)?.bl).toBeUndefined()
  expect(await current.api.undo()).toBe(false)
  expect(current.sheet.getCellMatrix().getData()).toEqual(current.cells)
  current.dispose()
})


it.each(optionCases)('saves %s through real table operations without changing cells or other XML parts', async (option, enabled) => {
  const original = await applyTableAdditions(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' }, style: { fillColor: '#FF0000', fontColor: '#00FF00', bold: false } },
  ]), [{ worksheetSheetName: 'Sheet1', name: 'Staff', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 },
    columnNames: ['Name'], style: option === 'showColumnStripes' ? '' : 'TableStyleMedium2', bandedRows: true }])
  const baseline = await readWorkbook(original), before = baseline.sheets[0]!.tables![0]!
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  instances.push(univer)
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookTables(buildWorkbookData(baseline, 'option-save', 'options'), baseline))
  const api = FUniver.newAPI(univer), injector = univer.__getInjector()
  injector.get(IUniverInstanceService).focusUnit('option-save')
  const installed = installTableStyleEdit({ univer, univerAPI: api }), workbook = api.getActiveWorkbook()!
  const tableId = `file-table-${workbook.getActiveSheet()!.getSheetId()}-${before.id}`
  installed.setOption(tableId, option, enabled)
  const keys = { showFirstColumn: 'firstColumn', showLastColumn: 'lastColumn', showRowStripes: 'bandedRows', showColumnStripes: 'bandedColumns' }
  const operations = workbookTableOperations(baseline, workbook)
  expect(operations).toEqual([{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', [keys[option]]: enabled }] }])
  const bytes = await applyWorkbookOperations(original, operations), reopened = await readWorkbook(bytes)
  expect(reopened.sheets[0]!.tables![0]!.style).toEqual({ ...before.style, [option]: enabled })
  expect(reopened.sheets[0]!.cells).toEqual(baseline.sheets[0]!.cells)
  const sourceZip = await createBufferEntrySource(original), savedZip = await createBufferEntrySource(bytes)
  expect(await savedZip.paths()).toEqual(await sourceZip.paths())
  for (const path of await sourceZip.paths()) {
    if (!path.startsWith('xl/tables/')) expect(await savedZip.readText(path)).toBe(await sourceZip.readText(path))
  }
  await api.undo()
  expect(workbookTableOperations(baseline, workbook)).toEqual([])
  await api.redo()
  expect(workbookTableOperations(baseline, workbook)).toEqual(operations)
  installed.dispose()
})


it('restores option metadata and rendering when theme rule registration fails after the table update', async () => {
  const current = setup(), before = structuredClone(current.table().getTableMeta()), themes = current.injector.get(SheetRangeThemeModel)
  const original = themes.registerRangeThemeRule.bind(themes)
  let injected = false
  themes.registerRangeThemeRule = (name, info) => {
    if (!injected) { injected = true; throw new Error('option rule fault') }
    return original(name, info)
  }
  expect(() => current.installed.setOption('file-table-data-1', 'showFirstColumn', true)).toThrow('option rule fault')
  themes.registerRangeThemeRule = original
  expect(current.table().getTableMeta()).toEqual(before)
  expect(current.sheet.getComposedCellStyle(1, 0)?.bl).toBeUndefined()
  expect(await current.api.undo()).toBe(false)
  expect(current.sheet.getCellMatrix().getData()).toEqual(current.cells)
  current.dispose()
})

it('notifies the official range-theme mutation so the real canvas invalidates cached table styles', () => {
  const current = setup(), events: any[] = []
  const listener = current.injector.get(ICommandService).onCommandExecuted(command => { if (command.id === 'sheet.mutation.set-worksheet-range-theme-style') events.push(command.params) })
  try {
    current.installed.setOption('file-table-data-1', 'showRowStripes', false)
    expect(events).toContainEqual(expect.objectContaining({ unitId: 'book', subUnitId: 'data', range: { startRow: 0, endRow: 3, startColumn: 0, endColumn: 1 } }))
    expect(current.sheet.getCellMatrix().getData()).toEqual(current.cells)
  } finally { listener.dispose(); current.dispose() }
})
