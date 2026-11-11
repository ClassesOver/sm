import { afterEach, expect, it } from 'vitest'
import { ICommandService, IUniverInstanceService, IUndoRedoService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { SheetRangeThemeModel, UniverSheetsPlugin } from '@univerjs/sheets'
import { ISuperTableService, UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import { TableColumnFilterTypeEnum, TableManager, UniverSheetsTablePlugin } from '@univerjs/sheets-table'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-table/facade'
import { installTableHeaderRow } from './workbook-table-header-row'
import { withWorkbookTables, workbookTableConfig } from './workbook-tables'
import { installNativeTableStyleRendering } from './workbook-table-styles'
import { installTableFormulaReferences } from './workbook-table-formulas'

const cleanup: (() => void)[] = []
afterEach(() => cleanup.splice(0).reverse().forEach(fn => fn()))
const area = { startRow: 1, endRow: 4, startColumn: 0, endColumn: 1 }
const style = { name: 'TableStyleMedium23', showFirstColumn: true, showLastColumn: false, showRowStripes: true, showColumnStripes: true }
function setup(protectedSheet = false, cells?: any, header = true, merges: any[] = []) {
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin); univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin); univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
  const cellData = cells ?? { 1: { 0: { v: 'Name', s: { bg: { rgb: '#FF0000' }, bl: 0 } }, 1: { v: 'Qty' } }, 2: { 0: { v: 'Ada' }, 1: { v: 2 } }, 3: { 0: { v: 'Grace' }, 1: { v: 3 } }, 4: { 0: { v: 'Total' }, 1: { f: '=SUBTOTAL(109,B3:B4)' } } }
  const table = { id: '1', name: 'Staff', displayName: 'Staff', range: { ...area, startRow: header ? 1 : 2 }, headerRowCount: header ? 1 : 0, totalsRowCount: 1,
    columns: [{ id: '11', name: 'Name' }, { id: '22', name: 'Qty' }], style }
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookTables({ id: 'book', name: 'book', appVersion: '0.25.1', locale: LocaleType.EN_US,
    sheetOrder: ['data'], sheets: { data: { id: 'data', name: 'Data', rowCount: 20, columnCount: 10, cellData: structuredClone(cellData), mergeData: merges } } }, { sheets: [{ name: 'Data', tables: [table] }] } as any))
  const api = FUniver.newAPI(univer), injector = univer.__getInjector(), workbook = api.getActiveWorkbook()!, sheet = workbook.getActiveSheet()!
  injector.get(IUniverInstanceService).focusUnit('book')
  const manager = injector.get(TableManager), live = manager.getTable('book', 'file-table-data-1')!
  live.setTableMeta({ ...live.getTableMeta(), custom: { keep: 7 } })
  manager.addFilter('book', live.getId(), 1, { filterType: TableColumnFilterTypeEnum.manual, values: ['2'], isAllSelected: false })
  const references = installTableFormulaReferences({ univer }), rendering = installNativeTableStyleRendering(injector), installed = installTableHeaderRow({ univer, univerAPI: api }, () => protectedSheet)
  cleanup.push(() => { installed.dispose(); rendering.dispose(); references.dispose(); univer.dispose() })
  const rawCells = () => {
    const cells = structuredClone(sheet.getSheet().getCellMatrix().getData()) as Record<number, Record<number, any>>
    for (const row of Object.values(cells)) for (const cell of Object.values(row)) if (cell) {
      const explicit = workbook.getWorkbook().getStyles().getStyleByCell(cell)
      delete cell.t
      if (explicit) cell.s = structuredClone(explicit)
    }
    return cells
  }
  const snapshot = () => ({ json: structuredClone(live.toJSON()), cells: rawCells(),
    filtered: [2, 3].map(row => sheet.getSheet().isRowFiltered(row)), theme: structuredClone(injector.get(SheetRangeThemeModel).getCellStyle('book', 'data', live.getRange().startRow, 0)),
    registry: structuredClone(injector.get(ISuperTableService).getTable('book', 'Staff')) })
  return { installed, api, injector, manager, live, workbook, sheet, snapshot, commands: injector.get(ICommandService), history: injector.get(IUndoRedoService) }
}

it('hides the actual header range and clears its contents while restoring full state in one undo', async () => {
  const c = setup(), before = c.snapshot()
  expect(c.installed.setHeaderRow(c.live.getId(), false)).toBe(true)
  expect(c.live.isShowHeader()).toBe(false)
  expect(c.live.getRange()).toEqual({ ...area, startRow: 2 })
  expect(c.live.getTableMeta()).toMatchObject({ nativeHeaderRowCount: 0, nativeTotalsRowCount: 1, custom: { keep: 7 } })
  expect(c.sheet.getRange(1, 0).getValue()).toBeNull()
  expect(c.sheet.getSheet().getComposedCellStyle(1, 0)).toMatchObject({ bg: { rgb: '#FF0000' }, bl: 0 })
  expect(c.sheet.getRange(4, 1).getFormula()).toBe('=SUBTOTAL(109,B3:B4)')
  expect(c.snapshot().filtered).toEqual([false, false])
  expect(c.injector.get(ISuperTableService).getTable('book', 'Staff')?.range).toEqual({ ...area, startRow: 2, endRow: 3 })
  await c.api.undo(); expect(c.snapshot()).toEqual(before)
  await c.api.redo(); expect(c.live.isShowHeader()).toBe(false)
})

it('shows a header only by using the free preceding row and leaves body/totals untouched', async () => {
  const c = setup(false, { 2: { 0: { v: 'Ada' }, 1: { v: 2 } }, 3: { 0: { v: 'Grace' }, 1: { v: 3 } }, 4: { 0: { v: 'Total' }, 1: { f: '=SUBTOTAL(109,B3:B4)' } } }, false), before = c.snapshot()
  c.installed.setHeaderRow(c.live.getId(), true)
  expect(c.live.getRange()).toEqual(area)
  expect(c.live.isShowHeader()).toBe(true)
  expect(c.sheet.getRange(1, 0, 1, 2).getValues()).toEqual([['Name', 'Qty']])
  expect(c.sheet.getRange(2, 0, 3, 2).getFormulas()).toEqual([['', ''], ['', ''], ['', '=SUBTOTAL(109,B3:B4)']])
  await c.api.undo(); expect(c.snapshot()).toEqual(before)
})

it.each(['protected', 'occupied', 'formula-empty', 'merge', 'overlap', 'top-edge'])('rejects %s before touching cells, table or history', kind => {
  const c = setup(kind === 'protected', undefined, kind === 'protected')
  if (kind === 'occupied' || kind === 'formula-empty') c.sheet.getSheet().getCellMatrix().setValue(1, 0, kind === 'occupied' ? { v: 'Keep' } : { f: '=""', v: '' })
  if (kind === 'merge') c.sheet.getSheet().getMergeData().push({ startRow: 1, endRow: 1, startColumn: 0, endColumn: 1 })
  if (kind === 'overlap') c.manager.addTable('book', 'data', 'Other', { startRow: 0, endRow: 1, startColumn: 0, endColumn: 1 }, ['X', 'Y'], 'other')
  if (kind === 'top-edge') c.live.fromJSON({ ...c.live.toJSON(), columns: [], range: { ...area, startRow: 0 }, options: { ...c.live.toJSON().options, showHeader: false } })
  const before = c.snapshot()
  expect(() => c.installed.setHeaderRow(c.live.getId(), kind !== 'protected')).toThrow()
  expect(c.snapshot()).toEqual(before)
  expect(c.history.pitchTopUndoElement()).toBeNull()
})

it.each(['cells-before', 'cells-after', 'state-before', 'registry-after'])('rolls back %s without history or metadata loss', fault => {
  const c = setup(), before = c.snapshot(), original = c.commands.syncExecuteCommand.bind(c.commands)
  let injected = false
  c.commands.syncExecuteCommand = (id, params, options) => {
    const target = fault.startsWith('cells') ? 'sheet.mutation.set-range-values' : fault === 'state-before' ? 'sheet.mutation.native-table-header-row-state' : 'formula.mutation.set-super-table'
    if (!injected && id === target) { injected = true; if (fault.endsWith('after')) original(id, params, options); throw new Error('header row fault') }
    return original(id, params, options)
  }
  try { expect(() => c.installed.setHeaderRow(c.live.getId(), false)).toThrow('header row fault') }
  finally { c.commands.syncExecuteCommand = original }
  expect(injected).toBe(true); expect(c.snapshot()).toEqual(before)
  expect(c.history.pitchTopUndoElement()).toBeNull()
})

it('roundtrips hidden and restored headers through actual cell/table edits without moving data or totals', async () => {
  const { applyCellEdits, applyTableAdditions, applyTableEdits, createBlankWorkbook, readWorkbook } = await import('@sheets-web/xlsx-engine')
  const { applyWorkbookOperations } = await import('../../../reporting/workbook_engine/bridge/operations')
  const { workbookTableOperations } = await import('./workbook-tables')
  const { diffToEdits } = await import('./workbook-vendor/core/session-core')
  const { readBackSnapshot } = await import('./workbook-vendor/grid/sync')
  const c = setup()
  const original = await applyTableEdits(await applyTableAdditions(await applyCellEdits(await createBlankWorkbook('Data'), [
    { sheetName: 'Data', row: 1, column: 0, writeValue: true, cell: { value: 'Name' }, style: { fillColor: '#FF0000', bold: false } },
    { sheetName: 'Data', row: 1, column: 1, writeValue: true, cell: { value: 'Qty' } },
    { sheetName: 'Data', row: 2, column: 0, writeValue: true, cell: { value: 'Ada' } },
    { sheetName: 'Data', row: 2, column: 1, writeValue: true, cell: { value: 2 } },
    { sheetName: 'Data', row: 3, column: 0, writeValue: true, cell: { value: 'Grace' } },
    { sheetName: 'Data', row: 3, column: 1, writeValue: true, cell: { value: 3 } },
    { sheetName: 'Data', row: 4, column: 0, writeValue: true, cell: { value: 'Total' } },
    { sheetName: 'Data', row: 4, column: 1, writeValue: true, cell: { value: null, formula: '=SUBTOTAL(109,B3:B4)' } },
  ]), [{ worksheetSheetName: 'Data', area, name: 'Staff', columnNames: ['Name', 'Qty'], style: style.name, bandedRows: true }]),
  [{ worksheetSheetName: 'Data', tableName: 'Staff', totalsRow: true, firstColumn: true, bandedColumns: true }])
  const baseline = await readWorkbook(original)
  const save = async () => {
    const tableOps = workbookTableOperations(baseline, c.workbook)
    const edits = diffToEdits(baseline, readBackSnapshot(await c.workbook.save()))
    return { tableOps, bytes: await applyWorkbookOperations(original, [...(edits.length ? [{ kind: 'applyCellEdits', edits }] : []), ...tableOps]) }
  }
  c.installed.setHeaderRow(c.live.getId(), false)
  const hidden = await save(), reopened = await readWorkbook(hidden.bytes)
  expect(hidden.tableOps).toEqual([{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Data', tableName: 'Staff', area: { ...area, startRow: 2 }, headerRow: false }] }])
  expect(reopened.sheets[0]!.tables![0]).toMatchObject({ range: { ...area, startRow: 2 }, headerRowCount: 0, totalsRowCount: 1, columns: [{ name: 'Name' }, { name: 'Qty' }] })
  for (const address of ['A3', 'B3', 'A4', 'B4', 'A5', 'B5']) expect(reopened.sheets[0]!.cells[address]).toEqual(baseline.sheets[0]!.cells[address])
  expect(reopened.sheets[0]!.cells.A2?.value ?? null).toBeNull()
  const { createBufferEntrySource } = await import('@sheets-web/xlsx-engine/zip')
  const hiddenXml = await (await createBufferEntrySource(hidden.bytes)).readText('xl/tables/table1.xml')
  expect(hiddenXml).not.toContain('<autoFilter')
  await c.api.undo()
  expect((await save()).tableOps).toEqual([])
  c.installed.setHeaderRow(c.live.getId(), false)
  c.installed.setHeaderRow(c.live.getId(), true)
  const shown = await readWorkbook((await save()).bytes)
  expect(shown.sheets[0]!.tables![0]).toMatchObject({ range: area, headerRowCount: 1, totalsRowCount: 1 })
  expect(shown.sheets[0]!.cells.A2?.value).toBe('Name')
})

it('keeps a single data row with totals when adding the preceding header', async () => {
  const c = setup(false, { 2: { 0: { v: 'Ada' }, 1: { v: 2 } }, 3: { 0: { v: 'Total' }, 1: { f: '=SUBTOTAL(109,B3:B3)' } } }, false)
  c.manager.updateTableRange('book', c.live.getId(), { newRange: { ...area, startRow: 2, endRow: 3 } })
  const before = c.snapshot()
  c.installed.setHeaderRow(c.live.getId(), true)
  expect(c.live.getRange()).toEqual({ ...area, endRow: 3 })
  expect(c.sheet.getRange(2, 1).getValue()).toBe(2)
  expect(c.sheet.getRange(3, 1).getFormula()).toBe('=SUBTOTAL(109,B3:B3)')
  await c.api.undo(); expect(c.snapshot()).toEqual(before)
})

it('ignores no-op calls and rejects stale disposed or forged mutations', () => {
  const c = setup(), before = c.snapshot()
  expect(c.installed.setHeaderRow(c.live.getId(), true)).toBe(true)
  expect(c.history.pitchTopUndoElement()).toBeNull()
  expect(() => c.installed.setHeaderRow('missing', false)).toThrow('不存在')
  expect(c.commands.syncExecuteCommand('sheet.mutation.native-table-header-row', { steps: [] })).toBe(false)
  expect(c.commands.syncExecuteCommand('sheet.mutation.native-table-header-row-state', { snapshot: {} })).toBe(false)
  expect(c.snapshot()).toEqual(before)
  c.installed.dispose()
  expect(() => c.installed.setHeaderRow(c.live.getId(), false)).toThrow('已关闭')
})

it('undoes showing a header without presenting a blank header to consumer protection guards', async () => {
  const c = setup(false, { 2: { 0: { v: 'Ada' }, 1: { v: 2 } }, 3: { 0: { v: 'Grace' }, 1: { v: 3 } }, 4: { 0: { v: 'Total' }, 1: { f: '=SUBTOTAL(109,B3:B4)' } } }, false)
  c.installed.setHeaderRow(c.live.getId(), true)
  // 主视图在set-range-values前校验列更名；空值恢复时必须已退回无标题模型。
  const guard = c.commands.beforeCommandExecuted(command => {
    if (command.id === 'sheet.mutation.set-range-values' && (command.params as any)?.cellValue?.[1]?.[0]?.v === null)
      expect(c.live.isShowHeader()).toBe(false)
  })
  try { expect(await c.api.undo()).toBe(true) } finally { guard.dispose() }
})
