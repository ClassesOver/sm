import { CommandType, ICommandService, IUndoRedoService } from '@univerjs/core'
import { RangeThemeStyle, SheetRangeThemeModel, SetRangeValuesMutation, SetRangeValuesUndoMutationFactory } from '@univerjs/sheets'
import { TableManager } from '@univerjs/sheets-table'
import { SetSuperTableMutation } from '@univerjs/engine-formula'
import { nativeTableTheme } from './workbook-table-styles'

const STATE = 'sheet.mutation.native-table-header-row-state'
const TRANSACTION = 'sheet.mutation.native-table-header-row'
const overlaps = (a: any, b: any) => a.startRow <= b.endRow && b.startRow <= a.endRow && a.startColumn <= b.endColumn && b.startColumn <= a.endColumn

// 固定源toggleHeaderRow：开关实际增减表范围；数据与汇总行位置保持，撤销恢复完整筛选/列/主题。
export function installTableHeaderRow(runtime: any, protectedSheet: (id: string) => boolean = () => false) {
  const injector = runtime.univer.__getInjector(), commands = injector.get(ICommandService), tables = injector.get(TableManager)
  const themes = injector.get(SheetRangeThemeModel), owned = new WeakSet<object>()
  let disposed = false
  const execute = (id: string, params: any) => {
    owned.add(params)
    if (!commands.syncExecuteCommand(id, params)) throw new Error('标题行修改未执行，修改已撤销')
  }
  const state = commands.registerCommand({ id: STATE, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (!params || !owned.has(params)) return false
      const table = tables.getTable(params.unitId, params.tableId)
      if (!table || table.getSubunitId() !== params.subUnitId) return false
      const json = structuredClone(params.snapshot.table), oldRange = { ...table.getRange() }
      const oldFilters = table.toJSON().filters.tableColumnFilterList ?? []
      for (let c = 0; c < oldFilters.length; c++) tables.addFilter(params.unitId, params.tableId, c, undefined)
      table.setColumns([]); table.fromJSON({ ...json, range: oldRange })
      if (params.snapshot.theme) themes.registerRangeThemeStyle(params.unitId, new RangeThemeStyle(json.options.tableStyleId, structuredClone(params.snapshot.theme)))
      tables.updateTableRange(params.unitId, params.tableId, { newRange: json.range })
      for (let c = 0; c < (json.filters.tableColumnFilterList?.length ?? 0); c++) tables.addFilter(params.unitId, params.tableId, c, json.filters.tableColumnFilterList[c])
      execute(SetSuperTableMutation.id, { unitId: params.unitId, tableName: json.name,
        reference: { range: { ...json.range, endRow: json.range.endRow - (json.meta.nativeTotalsRowCount ?? 0) }, sheetId: params.subUnitId,
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
    setHeaderRow(tableId: string, enabled: boolean): boolean {
      if (disposed) throw new Error('标题行编辑已关闭')
      if (typeof enabled !== 'boolean') throw new Error('标题行设置无效')
      const workbook = runtime.univerAPI.getActiveWorkbook(), unitId = workbook?.getId(), table = unitId && tables.getTable(unitId, tableId)
      if (!table) throw new Error('当前表格不存在，请重新选择')
      const subUnitId = table.getSubunitId()
      if (protectedSheet(subUnitId)) throw new Error('表格所在工作表受保护，请先撤销保护')
      if (table.isShowHeader() === enabled) return true
      const before = { table: structuredClone(table.toJSON()), theme: structuredClone(themes.getRangeThemeStyle(unitId, table.getTableStyleId())?.toJson()) }
      const after = structuredClone(before), area = before.table.range
      const row = enabled ? area.startRow - 1 : area.startRow
      const sheet = workbook.getSheetBySheetId(subUnitId), core = sheet.getSheet(), matrix = core.getCellMatrix()
      if (row < 0) throw new Error('表格上方没有空行可用于标题行')
      const strip = { ...area, startRow: row, endRow: row }
      if (core.getMergeData().some((merge: any) => overlaps(merge, strip))) throw new Error('标题行包含合并单元格，请先取消合并')
      if (tables.getTableList(unitId).some((other: any) => other.id !== tableId && other.subUnitId === subUnitId && overlaps(other.range, strip))) throw new Error('标题行与其他表格交叠')
      if (area.endRow - area.startRow + 1 <= (table.isShowHeader() ? 1 : 0) + (before.table.meta.nativeTotalsRowCount ?? 0)) throw new Error('表格必须至少保留一行数据')
      if (enabled) for (let c = area.startColumn; c <= area.endColumn; c++) {
        const cell = matrix.getValue(row, c)
        if (cell?.f || cell?.p || cell?.v !== null && cell?.v !== undefined && cell?.v !== '') throw new Error('标题行目标位置已有内容，请在表格上方留出空行')
      }
      after.table.range.startRow += enabled ? -1 : 1
      after.table.options.showHeader = enabled
      after.table.meta.nativeHeaderRowCount = enabled ? 1 : 0
      after.table.meta.nativeFilterButton = enabled
      // 与文件引擎一致：标题改变后丢弃旧筛选条件，撤销才恢复原条件。
      after.table.filters = { ...after.table.filters, tableColumnFilterList: [] }
      after.theme = nativeTableTheme({ customStyle: after.table.meta.nativeCustomTableStyle, style: after.table.meta.nativeTableStyle, headerRowCount: enabled ? 1 : 0,
        totalsRowCount: after.table.meta.nativeTotalsRowCount ?? 0 }, after.table.meta.nativeThemePalette, after.table.options.tableStyleId) ?? { name: after.table.options.tableStyleId }
      const cellValue = { [row]: Object.fromEntries(after.table.columns.map((column: any, index: number) => [area.startColumn + index,
        { v: enabled ? column.displayName : null, f: null, si: null, p: null }])) }
      const cells = { unitId, subUnitId, cellValue }, undoCells = injector.invoke(SetRangeValuesUndoMutationFactory, cells)
      const make = (snapshot: typeof before) => ({ id: STATE, params: { unitId, subUnitId, tableId, snapshot } })
      // 先切换模型再清标题，避免表头更名保护把清除误识别为改列名。
      const redos = [make(after), { id: SetRangeValuesMutation.id, params: cells }]
      const undos = [make(before), { id: SetRangeValuesMutation.id, params: undoCells }]
      const redo = { id: TRANSACTION, params: { steps: redos, rollback: undos } }, undo = { id: TRANSACTION, params: { steps: undos, rollback: redos } }
      owned.add(redo.params); owned.add(undo.params)
      if (!commands.syncExecuteCommand(redo.id, redo.params)) throw new Error('标题行修改未执行')
      injector.get(IUndoRedoService).pushUndoRedo({ unitID: unitId, redoMutations: [redo], undoMutations: [undo] })
      return true
    },
  }
}
