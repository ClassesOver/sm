import { CommandType, ICommandService, IUndoRedoService } from '@univerjs/core'
import { TableManager } from '@univerjs/sheets-table'

const MUTATION = 'sheet.mutation.native-table-filter-button'

// 使用官方筛选模型和事件清除/恢复条件，不修改表范围或手动隐藏行。
export function installTableFilterButton(runtime: any, protectedSheet: (id: string) => boolean = () => false) {
  const injector = runtime.univer.__getInjector(), commands = injector.get(ICommandService)
  const tables = injector.get(TableManager), owned = new WeakSet<object>()
  let disposed = false
  const original = tables.getSheetFilterRangeWithState
  const visibleRanges = function (this: any, unitId: string, subUnitId: string) {
    return original.call(this, unitId, subUnitId).filter((item: any) => this.getTable(unitId, item.tableId)?.getTableMeta().nativeFilterButton !== false)
  }
  tables.getSheetFilterRangeWithState = visibleRanges
  const capture = (table: any) => ({ meta: structuredClone(table.getTableMeta()), filters: structuredClone(table.getTableFilters().toJSON()) })
  const apply = (unitId: string, table: any, state: ReturnType<typeof capture>) => {
    table.setTableMeta(structuredClone(state.meta))
    table.getTableFilters().fromJSON(structuredClone(state.filters))
    // addFilter 发布官方 tableFilterChanged$，同步过滤行缓存及按钮重绘。
    tables.addFilter(unitId, table.getId(), 0, table.getTableFilterColumn(0))
  }
  const registration = commands.registerCommand({ id: MUTATION, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (!params || !owned.has(params)) return false
      const table = tables.getTable(params.unitId, params.tableId)
      if (!table || table.getSubunitId() !== params.subUnitId) return false
      const before = capture(table)
      try { apply(params.unitId, table, params.state) }
      catch (error) { apply(params.unitId, table, before); throw error }
      return true
    },
  })
  return {
    ownsMutation: (params: object) => owned.has(params),
    dispose() {
      disposed = true; registration.dispose()
      if (tables.getSheetFilterRangeWithState === visibleRanges) tables.getSheetFilterRangeWithState = original
    },
    setFilterButton(tableId: string, enabled: boolean): boolean {
      if (disposed) throw new Error('表格筛选按钮编辑已关闭')
      if (typeof enabled !== 'boolean') throw new Error('筛选按钮设置无效')
      const workbook = runtime.univerAPI.getActiveWorkbook(), unitId = workbook?.getId(), table = unitId && tables.getTable(unitId, tableId)
      if (!table) throw new Error('当前表格不存在，请重新选择')
      if (protectedSheet(table.getSubunitId())) throw new Error('表格所在工作表受保护，请先撤销保护')
      if (enabled && !table.isShowHeader()) throw new Error('请先显示标题行，再启用筛选按钮')
      const before = capture(table)
      if ((before.meta.nativeFilterButton !== false) === enabled) return false
      const after = structuredClone(before)
      after.meta.nativeFilterButton = enabled
      if (!enabled) after.filters.tableColumnFilterList = []
      const make = (state: typeof before) => {
        const params = { unitId, subUnitId: table.getSubunitId(), tableId, state }
        owned.add(params)
        return { id: MUTATION, params }
      }
      const redo = make(after), undo = make(before)
      if (!commands.syncExecuteCommand(redo.id, redo.params)) throw new Error('筛选按钮设置未应用')
      injector.get(IUndoRedoService).pushUndoRedo({ unitID: unitId, redoMutations: [redo], undoMutations: [undo] })
      return true
    },
  }
}
