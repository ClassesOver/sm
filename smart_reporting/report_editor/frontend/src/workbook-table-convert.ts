import { CommandType, ICommandService, IUndoRedoService } from '@univerjs/core'
import { RangeThemeStyle, SheetInterceptorService, SheetRangeThemeModel } from '@univerjs/sheets'
import { AddSheetTableMutation, DeleteSheetTableCommand, DeleteSheetTableMutation, TableManager } from '@univerjs/sheets-table'
import { RemoveSuperTableMutation, SetSuperTableMutation } from '@univerjs/engine-formula'

const CONVERT_MUTATION = 'sheet.mutation.native-table-convert'
const STATE_MUTATION = 'sheet.mutation.native-table-convert-state'

// 复用官方删除消费者规划；补全官方撤销未保存的列、meta、筛选与汇总行注册。
export function installTableConvert(runtime: any, protectedSheet: (id: string) => boolean = () => false) {
  const injector = runtime.univer.__getInjector(), commands = injector.get(ICommandService)
  const tables = injector.get(TableManager), themes = injector.get(SheetRangeThemeModel), owned = new WeakSet<object>()
  let disposed = false
  const execute = (id: string, params: any) => {
    owned.add(params)
    if (!commands.syncExecuteCommand(id, params)) throw new Error('转换为区域未执行，修改已撤销')
  }
  const state = commands.registerCommand({ id: STATE_MUTATION, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (!params || !owned.has(params)) return false
      const { unitId, subUnitId, tableId, snapshot } = params
      if (!params.restore) {
        if (tables.getTable(unitId, tableId)) {
          // 官方delete事件不刷新筛选隐藏行缓存；先通过官方筛选接口释放目标表的隐藏行。
          for (let column = 0; column < snapshot.table.columns.length; column++) tables.addFilter(unitId, tableId, column, undefined)
          execute(DeleteSheetTableMutation.id, { unitId, subUnitId, tableId })
        }
        execute(RemoveSuperTableMutation.id, { unitId, tableName: snapshot.table.name })
        return true
      }
      const json = structuredClone(snapshot.table), themeId = json.options.tableStyleId
      if (snapshot.theme) themes.registerRangeThemeStyle(unitId, new RangeThemeStyle(themeId, structuredClone(snapshot.theme)))
      if (!tables.getTable(unitId, tableId)) execute(AddSheetTableMutation.id, {
        unitId, subUnitId, tableId, name: json.name, range: json.range, options: json.options,
        header: json.columns.map((column: any) => column.displayName),
      })
      const table = tables.getTable(unitId, tableId)
      table.setColumns([])
      table.fromJSON(json)
      for (let column = 0; column < (json.filters.tableColumnFilterList?.length ?? 0); column++) tables.addFilter(unitId, tableId, column, json.filters.tableColumnFilterList?.[column])
      execute(SetSuperTableMutation.id, { unitId, tableName: json.name,
        reference: { range: { ...json.range, endRow: json.range.endRow - (json.meta?.nativeTotalsRowCount ?? 0) }, sheetId: subUnitId,
          titleMap: new Map(json.columns.map((column: any, index: number) => [column.displayName, index])) } })
      return true
    },
  })
  const transaction = commands.registerCommand({ id: CONVERT_MUTATION, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (!params || !owned.has(params)) return false
      const run = (steps: any[]) => { for (const step of steps) execute(step.id, step.params) }
      try { run(params.steps) }
      catch (error) { run(params.rollback); throw error }
      return true
    },
  })
  return {
    ownsMutation: (params: object) => owned.has(params),
    dispose() { disposed = true; transaction.dispose(); state.dispose() },
    convert(tableId: string): boolean {
      if (disposed) throw new Error('表格转换已关闭')
      const workbook = runtime.univerAPI.getActiveWorkbook(), unitId = workbook?.getId()
      const table = unitId && tables.getTable(unitId, tableId)
      if (!table) throw new Error('当前表格不存在，请重新选择')
      const subUnitId = table.getSubunitId()
      if (protectedSheet(subUnitId)) throw new Error('表格所在工作表受保护，请先撤销保护')
      const snapshot = { table: structuredClone(table.toJSON()), theme: structuredClone(themes.getRangeThemeStyle(unitId, table.getTableStyleId())?.toJson()) }
      const consumers = injector.get(SheetInterceptorService).onCommandExecute({ id: DeleteSheetTableCommand.id,
        params: { unitId, subUnitId, tableId, tableName: snapshot.table.name } })
      const consumerRedos = [...(consumers.preRedos ?? []), ...consumers.redos]
      for (const step of consumerRedos) {
        const params = step.params as any
        const affected = new Set<string>([params?.subUnitId, ...Object.keys(params?.formulaData?.[unitId] ?? {})])
        for (const id of affected) if (id && protectedSheet(id)) throw new Error('引用此表格的工作表受保护，请先撤销保护')
      }
      const stateStep = (restore: boolean) => ({ id: STATE_MUTATION, params: { unitId, subUnitId, tableId, snapshot, restore } })
      const redos = [...(consumers.preRedos ?? []), stateStep(false), ...consumers.redos]
      const undos = [...(consumers.preUndos ?? []), stateStep(true), ...consumers.undos]
      const redo = { id: CONVERT_MUTATION, params: { steps: redos, rollback: undos } }
      const undo = { id: CONVERT_MUTATION, params: { steps: undos, rollback: redos } }
      owned.add(redo.params); owned.add(undo.params)
      if (!commands.syncExecuteCommand(redo.id, redo.params)) throw new Error('转换为区域未执行')
      injector.get(IUndoRedoService).pushUndoRedo({ unitID: unitId, redoMutations: [redo], undoMutations: [undo] })
      return true
    },
  }
}
