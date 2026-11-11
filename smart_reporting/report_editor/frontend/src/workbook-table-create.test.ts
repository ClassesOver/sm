import { afterEach, expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, IUndoRedoService, LocaleType, Univer, UniverInstanceType, type ICellData } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { SheetRangeThemeModel, UniverSheetsPlugin } from '@univerjs/sheets'
import { IDefinedNamesService, ISuperTableService, UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import { TableManager, UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import { UniverSheetsFilterPlugin } from '@univerjs/sheets-filter'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-table/facade'
import '@univerjs/sheets-filter/facade'
import { installTableCreate, inferTableRegion, tableCreateCellEdits } from './workbook-table-create'
import { workbookTableConfig } from './workbook-tables'
import { installNativeTableStyleRendering } from './workbook-table-styles'
import { installTableStyleEdit } from './workbook-table-style-edit'
import { installTableTotals } from './workbook-table-totals'
import { installTableResize } from './workbook-table-resize'
import { installTableConvert } from './workbook-table-convert'

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).reverse().forEach(cleanup => cleanup()))
const area = { startRow: 1, endRow: 3, startColumn: 0, endColumn: 1 }
function setup(cellData: any = { 1: { 0: { v: ' Name ' }, 1: { v: 'name' } }, 2: { 0: { v: 'Ada' }, 1: { v: 2, s: { bg: { rgb: '#FF0000' } } } }, 3: { 0: { v: 'Grace' }, 1: { v: 3 } } }, protectedSheet = false, merges: any[] = []) {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin); univer.registerPlugin(UniverSheetsFilterPlugin)
  univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, { id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.EN_US,
    sheetOrder: ['data'], sheets: { data: { id: 'data', name: 'Data', rowCount: 30, columnCount: 1010, cellData: structuredClone(cellData), mergeData: merges } } })
  const api = FUniver.newAPI(univer), injector = univer.__getInjector(), workbook = api.getActiveWorkbook()!, sheet = workbook.getActiveSheet()!
  injector.get(IUniverInstanceService).focusUnit('book')
  const runtime = { univer, univerAPI: api, themePalette: ['#FFFFFF', '#000000', '#EEEEEE', '#222222', '#008800'] }
  const installed = installTableCreate(runtime, () => protectedSheet), rendering = installNativeTableStyleRendering(injector)
  cleanups.push(() => { installed.dispose(); rendering.dispose(); univer.dispose() })
  const manager = injector.get(TableManager), commands = injector.get(ICommandService), history = injector.get(IUndoRedoService)
  const snapshot = () => {
    const cells = structuredClone(sheet.getSheet().getCellMatrix().getData()) as Record<number, Record<number, ICellData>>
    for (const row of Object.values(cells)) for (const cell of Object.values(row)) if (cell) {
      const style = workbook.getWorkbook().getStyles().getStyleByCell(cell)
      delete cell.t
      if (style) cell.s = structuredClone(style)
    }
    return structuredClone({ cells, tables: manager.toJSON('book') })
  }
  return { installed, runtime, injector, api, workbook, sheet, manager, commands, history, snapshot }
}

it('creates a themed native table with normalized headers and one complete undo redo', async () => {
  const c = setup(), before = c.snapshot()
  c.injector.get(IDefinedNamesService).registerDefinedName('book', { id: 'one', name: 'Table1', formulaOrRefString: 'Data!A1', localSheetId: 'data' })
  expect(c.installed.create('data', area, true)).toBe(true)
  const table = c.workbook.getTableList()[0]!, live = c.manager.getTable('book', table.id)!
  expect(table.id.startsWith('native-new-table:')).toBe(true)
  expect(table.name).toBe('Table2')
  expect(live.toJSON()).toMatchObject({ range: area, columns: [{ displayName: 'Name' }, { displayName: 'name2' }], meta: {
    nativeCreatedTable: true, nativeTotalsRowCount: 0, nativeThemePalette: c.runtime.themePalette,
    nativeTableStyle: { name: 'TableStyleMedium2', showRowStripes: true, showColumnStripes: false, showFirstColumn: false, showLastColumn: false },
  } })
  expect(c.sheet.getRange(1, 0).getValue()).toBe('Name')
  expect(c.sheet.getRange(1, 1).getValue()).toBe('name2')
  expect(c.sheet.getSheet().getComposedCellStyle(1, 0)).toMatchObject({ bg: { rgb: '#008800' }, bl: 1 })
  expect(c.sheet.getSheet().getCellMatrix().getValue(2, 1)).toEqual(before.cells[2]![1])
  expect(c.injector.get(ISuperTableService).getTable('book', 'Table2')?.titleMap.get('name2')).toBe(1)
  const created = c.snapshot()
  await c.api.undo()
  expect(c.snapshot()).toEqual(before)
  expect(c.history.pitchTopUndoElement()).toBeNull()
  expect(c.injector.get(SheetRangeThemeModel).getCellStyle('book', 'data', 1, 0)).toBeUndefined()
  await c.api.redo()
  expect(c.snapshot()).toEqual(created)
})

it('creates no-header table using a free row above without moving formula data', async () => {
  const c = setup({ 1: { 0: { v: 'Ada' }, 1: { f: '=1+1', v: 2 } }, 2: { 0: { v: 'Grace' }, 1: { v: 3 } } }), before = c.snapshot()
  c.installed.create('data', { ...area, endRow: 2 }, false)
  expect(c.workbook.getTableList()[0]!.range).toEqual({ ...area, startRow: 0, endRow: 2 })
  expect(c.sheet.getRange(0, 0).getValue()).toBe('Column1')
  expect(c.sheet.getRange(1, 1).getFormula()).toBe('=1+1')
  await c.api.undo(); expect(c.snapshot()).toEqual(before)
})

it('moves no-header data down into a free row with raw cell formatting preserved', async () => {
  const c = setup({ 0: { 0: { v: 'Ada', s: { bl: 1 }, custom: { source: 'keep' } }, 1: { v: 2 } }, 1: { 0: { v: 'Grace' }, 1: { v: 3 } } }), before = c.snapshot()
  c.installed.create('data', { ...area, startRow: 0, endRow: 1 }, false)
  expect(c.sheet.getRange(0, 0).getValue()).toBe('Column1')
  expect(c.snapshot().cells[1]![0]).toEqual({ ...before.cells[0]![0], custom: { source: 'keep', nativeTableCreateStyleReset: true } })
  expect(c.sheet.getRange(2, 0).getValue()).toBe('Grace')
  await c.api.undo(); expect(c.snapshot()).toEqual(before)
})

it('infers the continuous region from one cell and returns null for empty or single-row regions', () => {
  const c = setup()
  expect(inferTableRegion(c.sheet, 2, 1)).toEqual(area)
  expect(inferTableRegion(c.sheet, 10, 10)).toBeNull()
  expect(inferTableRegion(c.sheet, 3, 0)).toEqual(area)
})

it.each(['protected', 'merge', 'formula-shift', 'no-room', 'filter', 'overlap', 'invalid', 'width', 'headers-one-row'])('rejects %s before cells table or history changes', kind => {
  const cells = kind === 'formula-shift' ? { 0: { 0: { f: '=1+1', v: 2 } } } : undefined
  const c = setup(cells, kind === 'protected', kind === 'merge' ? [{ ...area, endRow: 2 }] : [])
  if (kind === 'filter') c.sheet.getRange('A2:B4').createFilter()
  if (kind === 'overlap') c.installed.create('data', area, true)
  if (kind === 'no-room') c.sheet.getRange('A1:B5').setValues(Array.from({ length: 5 }, () => ['occupied', 'occupied']))
  const before = c.snapshot(), history = c.history.pitchTopUndoElement()
  const requested = kind === 'formula-shift' ? { ...area, startRow: 0, endRow: 0 } : kind === 'invalid' ? { ...area, startRow: -1 } : kind === 'width' ? { ...area, endColumn: 1000 } : kind === 'headers-one-row' ? { ...area, endRow: 1 } : area
  expect(() => c.installed.create('data', requested, !['formula-shift', 'no-room'].includes(kind))).toThrow()
  expect(c.snapshot()).toEqual(before)
  expect(c.history.pitchTopUndoElement()).toBe(history)
})

it('normalizes blank long and case-duplicate headers without exceeding 255 characters', () => {
  const c = setup({ 1: { 0: { v: '' }, 1: { v: 'x'.repeat(260) }, 2: { v: 'X'.repeat(260) } }, 2: { 0: { v: 1 } } })
  c.installed.create('data', { ...area, endRow: 2, endColumn: 2 }, true)
  const headers = c.workbook.getTableList()[0]!.columns.map(column => column.displayName)
  expect(headers).toEqual(['Column1', 'x'.repeat(255), 'X'.repeat(254) + '2'])
})

it.each(['cells-before', 'cells-after', 'add-before', 'add-after', 'registry-after'])('rolls back %s faults including header cells and table registry', fault => {
  const c = setup(), before = c.snapshot(), original = c.commands.syncExecuteCommand.bind(c.commands)
  let injected = false
  const target = fault.startsWith('cells') ? 'sheet.mutation.set-range-values' : fault.startsWith('add') ? 'sheet.mutation.add-table' : 'formula.mutation.set-super-table'
  c.commands.syncExecuteCommand = (id, params, options) => {
    if (!injected && id === target) {
      injected = true
      if (fault.endsWith('after')) original(id, params, options)
      throw new Error('create fault')
    }
    return original(id, params, options)
  }
  try { expect(() => c.installed.create('data', area, true)).toThrow('create fault') }
  finally { c.commands.syncExecuteCommand = original }
  expect(injected).toBe(true)
  expect(c.snapshot()).toEqual(before)
  expect(c.injector.get(ISuperTableService).hasTable('book', 'Table1')).toBe(false)
  expect(c.history.pitchTopUndoElement()).toBeNull()
})

it('rejects stale sheets forged mutations and disposed creation without writes', () => {
  const c = setup(), before = c.snapshot()
  expect(() => c.installed.create('missing', area, true)).toThrow('不存在')
  expect(c.commands.syncExecuteCommand('sheet.mutation.native-table-create', { steps: [] })).toBe(false)
  expect(c.commands.syncExecuteCommand('sheet.mutation.native-table-create-state', { create: true })).toBe(false)
  c.installed.dispose()
  expect(() => c.installed.create('data', area, true)).toThrow('已关闭')
  expect(c.snapshot()).toEqual(before)
})

it('supports existing resize style totals and conversion tools after native creation', async () => {
  const c = setup(), before = c.snapshot()
  c.installed.create('data', area, true)
  const id = c.workbook.getTableList()[0]!.id
  const resize = installTableResize(c.runtime), styles = installTableStyleEdit(c.runtime), totals = installTableTotals(c.runtime), convert = installTableConvert(c.runtime)
  try {
    resize.resize(id, 'A2:B5')
    styles.setStyle(id, 'TableStyleDark2')
    styles.setOption(id, 'showLastColumn', true)
    totals.setTotals(id, true)
    const created = c.snapshot()
    convert.convert(id)
    expect(c.workbook.getTableList()).toEqual([])
    await c.api.undo()
    const restored = c.snapshot()
    for (const resource of Object.values(restored.tables)) for (const table of resource.tables) if (table.filters.tableColumnFilterList?.every(value => value === undefined)) table.filters.tableColumnFilterList = []
    expect(restored).toEqual(created)
    expect(c.injector.get(ISuperTableService).getTable('book', 'Table1')?.range.endRow).toBe(4)
    for (let i = 0; i < 5; i++) await c.api.undo()
    expect(c.snapshot()).toEqual(before)
  } finally { convert.dispose(); totals.dispose(); styles.dispose(); resize.dispose() }
})

it('marks nested official writes owned and stores only one creation history entry', async () => {
  const c = setup(), unauthorized: string[] = []
  const listener = c.api.addEvent(c.api.Event.BeforeCommandExecute, command => {
    if (['sheet.mutation.add-table', 'sheet.mutation.delete-table', 'sheet.mutation.set-range-values', 'sheet.mutation.native-table-create', 'sheet.mutation.native-table-create-state'].includes(command.id) && !c.installed.ownsMutation(command.params as object)) {
      unauthorized.push(command.id); command.cancel = true
    }
  })
  try {
    c.installed.create('data', area, true)
    await c.api.undo()
    expect(c.history.pitchTopUndoElement()).toBeNull()
    expect(unauthorized).toEqual([])
  } finally { listener.dispose() }
})

it('roundtrips actual new table and normalized header edits through the workbook save engine', async () => {
  const { applyCellEdits, createBlankWorkbook, readWorkbook } = await import('@sheets-web/xlsx-engine')
  const { applyWorkbookOperations } = await import('../../../reporting/workbook_engine/bridge/operations')
  const { workbookTableOperations } = await import('./workbook-tables')
  const { diffToEdits } = await import('./workbook-vendor/core/session-core')
  const { readBackSnapshot } = await import('./workbook-vendor/grid/sync')
  const original = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: ' Name ' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 'name' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'Ada' } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 2 }, style: { fillColor: '#FF0000' } },
    { sheetName: 'Sheet1', row: 3, column: 0, writeValue: true, cell: { value: 'Grace' } },
    { sheetName: 'Sheet1', row: 3, column: 1, writeValue: true, cell: { value: 3 } },
  ])
  const model = await readWorkbook(original), c = setup()
  c.sheet.setName('Sheet1')
  c.installed.create('data', area, true)
  const styles = installTableStyleEdit(c.runtime), totals = installTableTotals(c.runtime)
  try {
    const id = c.workbook.getTableList()[0]!.id
    styles.setOption(id, 'showLastColumn', true)
    totals.setTotals(id, true)
    const tableOps = workbookTableOperations(model, c.workbook)
    expect(tableOps.some(op => op.kind === 'applyTableAdditions')).toBe(true)
    const edits = diffToEdits(model, readBackSnapshot(await c.workbook.save()))
    const saved = await applyWorkbookOperations(original, [{ kind: 'applyCellEdits', edits }, ...tableOps]), reopened = await readWorkbook(saved)
    expect(reopened.sheets[0]!.tables![0]).toMatchObject({ name: 'Table1', range: { ...area, endRow: 4 }, totalsRowCount: 1,
      columns: [{ name: 'Name' }, { name: 'name2' }], style: { name: 'TableStyleMedium2', showLastColumn: true, showRowStripes: true } })
    expect(reopened.sheets[0]!.cells.B3).toEqual(model.sheets[0]!.cells.B3)
    await c.api.undo(); await c.api.undo(); await c.api.undo()
    expect(workbookTableOperations(model, c.workbook)).toEqual([])
    expect(diffToEdits(model, readBackSnapshot(await c.workbook.save()))).toEqual([])
  } finally { totals.dispose(); styles.dispose() }
})

it.each([undefined, { fontFamily: 'Calibri', fontSize: 11 }, { fontColor: '#008000', italic: true, borderBottom: { style: 'thin' as const, color: '#0000FF' } },
  { horizontalAlignment: 'right' as const, verticalAlignment: 'center' as const, wrapText: true }])('replaces old destination formatting when no-header creation shifts plain source style %j', async sourceStyle => {
  const { applyCellEdits, createBlankWorkbook, readWorkbook } = await import('@sheets-web/xlsx-engine')
  const { applyWorkbookOperations } = await import('../../../reporting/workbook_engine/bridge/operations')
  const { workbookTableOperations } = await import('./workbook-tables')
  const { buildWorkbookData } = await import('./workbook-vendor/core/univer-data')
  const { diffToEdits, importedStyleOf } = await import('./workbook-vendor/core/session-core')
  const { readBackSnapshot } = await import('./workbook-vendor/grid/sync')
  const original = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'occupied above' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 123 }, ...(sourceStyle ? { style: sourceStyle } : {}) },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 456 }, style: { bold: true, fillColor: '#FF0000', numberFormat: '0.000' } },
  ])
  const model = await readWorkbook(original), univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  cleanups.push(() => univer.dispose())
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin); univer.registerPlugin(UniverSheetsFilterPlugin)
  univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, buildWorkbookData(model, 'shift-book', 'shift'))
  const api = FUniver.newAPI(univer), workbook = api.getActiveWorkbook()!
  univer.__getInjector().get(IUniverInstanceService).focusUnit('shift-book')
  const installed = installTableCreate({ univer, univerAPI: api })
  cleanups.push(() => installed.dispose())
  installed.create('sheet-0', { startRow: 1, endRow: 2, startColumn: 0, endColumn: 0 }, false)
  const snapshot = await workbook.save()
  const edits = tableCreateCellEdits(diffToEdits(model, readBackSnapshot(snapshot)), snapshot)
  const reopened = await readWorkbook(await applyWorkbookOperations(original, [{ kind: 'applyCellEdits', edits }, ...workbookTableOperations(model, workbook)]))
  expect(reopened.sheets[0]!.cells.A3?.value).toBe(123)
  const moved = importedStyleOf(reopened, 'Sheet1', 'A3')
  expect(moved?.bold).not.toBe(true)
  expect(moved?.fillColor).toBeUndefined()
  expect(moved?.numberFormat ?? 'General').toBe('General')
  if (sourceStyle && 'horizontalAlignment' in sourceStyle) expect(moved).toMatchObject({ hAlign: 'right', vAlign: 'middle', wrap: true })
  else if (sourceStyle) expect(moved).toMatchObject(sourceStyle)
  expect(importedStyleOf(reopened, 'Sheet1', 'A4')).toMatchObject({ bold: true, fillColor: '#FF0000', numberFormat: '0.000' })
  // 后续格式修改必须取保存时的实时样式，不能重放创建时缓存的格式。
  univer.__getInjector().get(ICommandService).syncExecuteCommand('sheet.mutation.set-range-values', {
    unitId: 'shift-book', subUnitId: 'sheet-0', cellValue: { 2: { 0: { s: { bl: 1, bg: { rgb: '#0000FF' }, n: { pattern: '0.0%' } } } } },
  })
  const changed = await workbook.save()
  const changedEdits = tableCreateCellEdits(diffToEdits(model, readBackSnapshot(changed)), changed)
  const changedModel = await readWorkbook(await applyWorkbookOperations(original, [{ kind: 'applyCellEdits', edits: changedEdits }, ...workbookTableOperations(model, workbook)]))
  expect(importedStyleOf(changedModel, 'Sheet1', 'A3')).toMatchObject({ bold: true, fillColor: '#0000FF', numberFormat: '0.0%' })
  await api.undo()
  const undone = await workbook.save()
  expect(tableCreateCellEdits(diffToEdits(model, readBackSnapshot(undone)), undone)).toEqual([])
  expect(workbookTableOperations(model, workbook)).toEqual([])
})
