import { CommandType, ICommandService, IUndoRedoService, generateRandomId, type ICellData, type IWorkbookData } from '@univerjs/core'
import { RangeThemeStyle, SheetRangeThemeModel, SetRangeValuesMutation, SetRangeValuesUndoMutationFactory } from '@univerjs/sheets'
import { AddSheetTableMutation, DeleteSheetTableMutation, TableManager } from '@univerjs/sheets-table'
import { IDefinedNamesService, RemoveSuperTableMutation, SetSuperTableMutation } from '@univerjs/engine-formula'
import type { CellEdit } from '@sheets-web/xlsx-engine'
import { fromUniverStyle, styleDelta, type UniverStyleData } from './workbook-vendor/core/style-map'
import { nativeTableTheme } from './workbook-table-styles'

export interface TableCreateRange { startRow: number; endRow: number; startColumn: number; endColumn: number }
const SHIFT_STYLE_RESET = 'nativeTableCreateStyleReset'

// 下移替换的是完整基础格式；缺失的样式字段不能按普通增量保存继承到目标格。
// 标记存放在单元格 custom 中，随官方移动、撤销和表格转区域一同保留。
export function tableCreateCellEdits(edits: readonly CellEdit[], data: unknown): CellEdit[] {
  const snapshot = data as Partial<IWorkbookData>, result = [...edits]
  const key = (sheet: string, row: number, column: number) => JSON.stringify([sheet, row, column])
  const positions = new Map(result.map((edit, index) => [key(edit.sheetName, edit.row, edit.column), index]))
  for (const sheet of Object.values(snapshot.sheets ?? {})) {
    if (!sheet.name) continue
    for (const [row, cells] of Object.entries(sheet.cellData ?? {})) for (const [column, cell] of Object.entries((cells ?? {}) as Record<number, ICellData>)) {
      if (cell?.custom?.[SHIFT_STYLE_RESET] !== true) continue
      const rawStyle = typeof cell.s === 'string' ? snapshot.styles?.[cell.s] : cell.s
      const logicalStyle = fromUniverStyle((rawStyle ?? {}) as UniverStyleData)
      const style = { ...styleDelta(undefined, logicalStyle), ...(logicalStyle.vAlign === 'middle' ? { verticalAlignment: 'center' as const } : {}) }
      const index = positions.get(key(sheet.name, Number(row), Number(column)))
      const edit: CellEdit = { ...(index === undefined
        ? { sheetName: sheet.name, row: Number(row), column: Number(column), writeValue: false, cell: { value: null } }
        : result[index]!), styleReset: true, style }
      if (index === undefined) result.push(edit)
      else result[index] = edit
    }
  }
  return result
}

const STATE = 'sheet.mutation.native-table-create-state'
const TRANSACTION = 'sheet.mutation.native-table-create'
const overlaps = (a: TableCreateRange, b: TableCreateRange) => a.startRow <= b.endRow && b.startRow <= a.endRow && a.startColumn <= b.endColumn && b.startColumn <= a.endColumn
const hasContent = (cell: any) => !!(cell?.f || cell?.p || cell?.v !== null && cell?.v !== undefined && cell?.v !== '')

// 固定源 CurrentRegion：相邻边上任一非空格即扩展，只返回至少两行的区域。
export function inferTableRegion(sheet: any, row: number, column: number): TableCreateRange | null {
  const matrix = sheet.getSheet().getCellMatrix()
  if (!hasContent(matrix.getValue(row, column))) return null
  let lastRow = row, lastColumn = column
  matrix.forValue((r: number, c: number, cell: any) => { if (hasContent(cell)) { lastRow = Math.max(lastRow, r); lastColumn = Math.max(lastColumn, c) } })
  const area = { startRow: row, endRow: row, startColumn: column, endColumn: column }
  const rowHas = (r: number) => { for (let c = area.startColumn; c <= area.endColumn; c++) if (hasContent(matrix.getValue(r, c))) return true; return false }
  const colHas = (c: number) => { for (let r = area.startRow; r <= area.endRow; r++) if (hasContent(matrix.getValue(r, c))) return true; return false }
  let grew = true
  while (grew) {
    grew = false
    if (area.startRow > 0 && rowHas(area.startRow - 1)) { area.startRow--; grew = true }
    if (area.endRow < lastRow && rowHas(area.endRow + 1)) { area.endRow++; grew = true }
    if (area.startColumn > 0 && colHas(area.startColumn - 1)) { area.startColumn--; grew = true }
    if (area.endColumn < lastColumn && colHas(area.endColumn + 1)) { area.endColumn++; grew = true }
  }
  return area.endRow > area.startRow ? area : null
}

export function installTableCreate(runtime: any, protectedSheet: (id: string) => boolean = () => false) {
  const injector = runtime.univer.__getInjector(), commands = injector.get(ICommandService), tables = injector.get(TableManager)
  const themes = injector.get(SheetRangeThemeModel), owned = new WeakSet<object>()
  let disposed = false
  const execute = (id: string, params: any) => {
    owned.add(params)
    if (!commands.syncExecuteCommand(id, params)) throw new Error('创建表格未执行，修改已撤销')
  }
  const state = commands.registerCommand({ id: STATE, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (!params || !owned.has(params)) return false
      const { unitId, subUnitId, tableId, json, theme } = params
      if (!params.create) {
        const table = tables.getTable(unitId, tableId)
        if (table) {
          for (let c = 0; c < table.getColumnsCount(); c++) tables.addFilter(unitId, tableId, c, undefined)
          execute(DeleteSheetTableMutation.id, { unitId, subUnitId, tableId })
        }
        execute(RemoveSuperTableMutation.id, { unitId, tableName: json.name })
        return true
      }
      themes.registerRangeThemeStyle(unitId, new RangeThemeStyle(theme.name, structuredClone(theme)))
      execute(AddSheetTableMutation.id, { unitId, subUnitId, tableId, name: json.name, range: json.range,
        header: json.columns.map((column: any) => column.displayName), options: json.options })
      const table = tables.getTable(unitId, tableId)
      table.setColumns([]); table.fromJSON(structuredClone(json))
      execute(SetSuperTableMutation.id, { unitId, tableName: json.name, reference: { range: json.range, sheetId: subUnitId,
        titleMap: new Map(json.columns.map((column: any, index: number) => [column.displayName, index])) } })
      return true
    },
  })
  const transaction = commands.registerCommand({ id: TRANSACTION, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (!params || !owned.has(params)) return false
      const run = (steps: any[]) => { for (const step of steps) execute(step.id, step.params) }
      try { run(params.steps) } catch (error) { run(params.rollback); throw error }
      return true
    },
  })
  return {
    ownsMutation: (params: object) => owned.has(params),
    dispose() { disposed = true; transaction.dispose(); state.dispose() },
    create(sheetId: string, requested: TableCreateRange, hasHeaders: boolean): boolean {
      if (disposed) throw new Error('创建表格已关闭')
      const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getSheetBySheetId(sheetId)
      if (!sheet) throw new Error('工作表不存在，请重新选择')
      if (protectedSheet(sheetId)) throw new Error('工作表受保护，请先撤销保护')
      const valid = (area: TableCreateRange) => area && Object.values(area).every(Number.isSafeInteger) && area.startRow >= 0 && area.startColumn >= 0 && area.endRow >= area.startRow && area.endColumn >= area.startColumn && area.endRow < 1048576 && area.endColumn < 16384
      if (typeof hasHeaders !== 'boolean' || !valid(requested)) throw new Error('表格范围无效')
      const core = sheet.getSheet(), matrix = core.getCellMatrix(), area = { ...requested }
      const free = (row: number) => row >= 0 && row < 1048576 && Array.from({ length: area.endColumn - area.startColumn + 1 }, (_, c) => !hasContent(matrix.getValue(row, area.startColumn + c))).every(Boolean)
      let shift = false
      if (!hasHeaders) {
        if (free(area.startRow - 1)) area.startRow--
        else if (free(area.endRow + 1)) { area.endRow++; shift = true }
        else throw new Error('没有空行可用于表头，请在数据上方留出空行')
      }
      const width = area.endColumn - area.startColumn + 1
      if (!valid(area) || area.endRow <= area.startRow || width > 1000) throw new Error('表格需要表头和至少一行数据，且不超过1000列')
      if (tables.getTableList(workbook.getId()).some((table: any) => table.subUnitId === sheetId && overlaps(table.range, area))) throw new Error('表格范围与已有表格重叠')
      if (core.getMergeData().some((merge: TableCreateRange) => overlaps(merge, area))) throw new Error('表格范围包含合并单元格，请先取消合并')
      const filter = sheet.getFilter?.(), filterRange = filter?.getRange()
      if (filterRange && overlaps({ startRow: filterRange.getRow(), endRow: filterRange.getLastRow(), startColumn: filterRange.getColumn(), endColumn: filterRange.getLastColumn() }, area)) throw new Error('表格范围与自动筛选重叠，请先移除筛选')
      if (shift) for (let r = requested.startRow; r <= requested.endRow; r++) for (let c = requested.startColumn; c <= requested.endColumn; c++) if (matrix.getValue(r, c)?.f || matrix.getValue(r, c)?.si) throw new Error('含公式的数据无法下移，请在数据上方留出空行')
      const names = new Set<string>([...tables.getTableList(workbook.getId()).map((table: any) => table.name.toLowerCase()), ...Object.values(injector.get(IDefinedNamesService).getDefinedNameMap(workbook.getId()) ?? {}).map((entry: any) => entry.name.toLowerCase())])
      let n = 1
      while (names.has(`table${n}`)) n++
      const name = `Table${n}`, unitId = workbook.getId(), tableId = `native-new-table:${generateRandomId()}`, themeId = `native-file-table:${JSON.stringify([sheetId, tableId])}:edit`
      const used = new Set<string>()
      const headers = Array.from({ length: width }, (_, c) => {
        const base = (hasHeaders ? String(sheet.getRange(area.startRow, area.startColumn + c).getValue() ?? '').trim().slice(0, 255) : '') || `Column${c + 1}`
        let next = base
        for (let suffix = 2; used.has(next.toLowerCase()); suffix++) { const tail = String(suffix); next = base.slice(0, 255 - tail.length) + tail }
        used.add(next.toLowerCase()); return next
      })
      const cellValue: Record<number, Record<number, any>> = {}
      if (shift) for (let r = requested.startRow; r <= requested.endRow; r++) for (let c = requested.startColumn; c <= requested.endColumn; c++) {
        const source = structuredClone(matrix.getValue(r, c) ?? {}), destination = matrix.getValue(r + 1, c)
        const styles = workbook.getWorkbook().getStyles(), oldStyle = styles.getStyleByCell(destination) ?? {}, sourceStyle = styles.getStyleByCell(source) ?? {}
        const target = cellValue[r + 1] ??= {}
        target[c] = { ...source, v: source.v ?? null, f: null, si: null, p: source.p ?? null,
          s: { ...Object.fromEntries(Object.keys(oldStyle).map(key => [key, null])), ...sourceStyle },
          custom: { ...source.custom, [SHIFT_STYLE_RESET]: true } }
      }
      cellValue[area.startRow] = Object.fromEntries(headers.map((value, c) => [area.startColumn + c, { v: value, f: null, si: null, p: null }]))
      const cellParams = { unitId, subUnitId: sheetId, cellValue }, undoCells = injector.invoke(SetRangeValuesUndoMutationFactory, cellParams)
      const style = { name: 'TableStyleMedium2', showRowStripes: true, showColumnStripes: false, showFirstColumn: false, showLastColumn: false }
      const json = { id: tableId, name, range: area, options: { showHeader: true, showFooter: false, tableStyleId: themeId },
        columns: headers.map((displayName, c) => ({ id: `${tableId}:${c}`, displayName, dataType: 'string', formula: '', meta: {}, style: {} })), filters: { tableColumnFilterList: [] },
        meta: { nativeCreatedTable: true, nativeTotalsRowCount: 0, nativeTableStyle: style, nativeTableStyleName: style.name, nativeThemePalette: structuredClone(runtime.themePalette), nativeTableThemeId: themeId } }
      const theme = nativeTableTheme({ style, headerRowCount: 1, totalsRowCount: 0 }, runtime.themePalette, themeId)!
      const stateParams = { unitId, subUnitId: sheetId, tableId, json, theme }
      const redos = [{ id: SetRangeValuesMutation.id, params: cellParams }, { id: STATE, params: { ...stateParams, create: true } }]
      const undos = [{ id: STATE, params: { ...stateParams, create: false } }, { id: SetRangeValuesMutation.id, params: undoCells }]
      const redo = { id: TRANSACTION, params: { steps: redos, rollback: undos } }, undo = { id: TRANSACTION, params: { steps: undos, rollback: redos } }
      owned.add(redo.params); owned.add(undo.params)
      if (!commands.syncExecuteCommand(redo.id, redo.params)) throw new Error('创建表格未执行')
      injector.get(IUndoRedoService).pushUndoRedo({ unitID: unitId, redoMutations: [redo], undoMutations: [undo] })
      return true
    },
  }
}
