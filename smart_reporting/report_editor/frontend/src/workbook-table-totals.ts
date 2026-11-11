import { CommandType, ICommandService, IUndoRedoService } from '@univerjs/core'
import { RangeThemeStyle, SheetRangeThemeModel, SetRangeValuesMutation, SetRangeValuesUndoMutationFactory } from '@univerjs/sheets'
import { TableManager } from '@univerjs/sheets-table'
import { SetSuperTableMutation } from '@univerjs/engine-formula'
import { formatAddress } from '@sheets-web/xlsx-engine'
import { nativeTableTheme } from './workbook-table-styles'

const STATE_MUTATION = 'sheet.mutation.native-table-totals-state'
const overlaps = (a: any, b: any) => a.startRow <= b.endRow && b.startRow <= a.endRow && a.startColumn <= b.endColumn && b.startColumn <= a.endColumn

// 固定源toggleTotalsRow：全部检查先于写入，cells/model/theme/reference共享一条历史。
export function installTableTotals(runtime: any, protectedSheet: (id: string) => boolean = () => false) {
  const injector = runtime.univer.__getInjector(), commands = injector.get(ICommandService), history = injector.get(IUndoRedoService)
  const tables = injector.get(TableManager), themes = injector.get(SheetRangeThemeModel), owned = new WeakSet<object>()
  let disposed = false
  const registration = commands.registerCommand({ id: STATE_MUTATION, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (!params || !owned.has(params)) return false
      const table = tables.getTable(params.unitId, params.tableId)
      if (!table || table.getSubunitId() !== params.subUnitId) return false
      const oldRange = table.getRange(), json = structuredClone(params.table)
      // fromJSON追加columns；先清空再重装，保留原id/filter/meta，不替换Table实例。
      table.setColumns([])
      table.fromJSON({ ...json, range: oldRange })
      tables.updateTableRange(params.unitId, params.tableId, { newRange: json.range })
      const meta = table.getTableMeta(), name = table.getTableStyleId()
      const theme = nativeTableTheme({ customStyle: meta.nativeCustomTableStyle, style: meta.nativeTableStyle, headerRowCount: table.isShowHeader() ? 1 : 0,
        totalsRowCount: meta.nativeTotalsRowCount ?? 0 }, meta.nativeThemePalette, name)
      if (theme) themes.registerRangeThemeStyle(params.unitId, new RangeThemeStyle(name, theme))
      const info = table.getTableInfo()
      return commands.syncExecuteCommand(SetSuperTableMutation.id, { unitId: params.unitId, tableName: info.name,
        reference: { range: { ...info.range, endRow: info.range.endRow - (meta.nativeTotalsRowCount ?? 0) }, sheetId: info.subUnitId,
          titleMap: new Map(info.columns.map((column: any, index: number) => [column.displayName, index])) } })
    },
  })
  return {
    ownsMutation: (params: object) => owned.has(params),
    dispose() { disposed = true; registration.dispose() },
    setTotals(tableId: string, enabled: boolean): boolean {
      if (disposed) throw new Error('表格设计已关闭')
      const workbook = runtime.univerAPI.getActiveWorkbook(), live = workbook?.getTableList() ?? []
      const info = live.find((table: any) => table.id === tableId)
      if (!info) throw new Error('当前表格不存在，请重新选择')
      const table = tables.getTable(workbook.getId(), tableId)!, before = table.toJSON()
      const current = (before.meta.nativeTotalsRowCount ?? 0) > 0
      if (current === enabled) return true
      if (protectedSheet(info.subUnitId)) throw new Error('表格所在工作表受保护，请先撤销保护')
      const sheet = workbook.getSheetBySheetId(info.subUnitId), core = sheet.getSheet(), area = info.range
      const row = enabled ? area.endRow + 1 : area.endRow
      if (row > 1048575) throw new Error('汇总行超出工作表边界')
      const strip = { ...area, startRow: row, endRow: row }
      if (core.getMergeData().some((merge: any) => overlaps(merge, strip))) throw new Error('汇总行包含合并单元格，请先取消合并')
      if (live.some((other: any) => other.id !== tableId && other.subUnitId === info.subUnitId && overlaps(other.range, strip))) throw new Error('汇总行与其他表格交叠')
      const raw = (r: number, c: number) => core.getCellMatrix().getValue(r, c)
      if (enabled) for (let column = area.startColumn; column <= area.endColumn; column++) {
        const cell = raw(row, column)
        if (cell?.f || cell?.p || cell?.v !== null && cell?.v !== undefined && cell?.v !== '') throw new Error('汇总行目标位置已有内容')
      }
      const after = structuredClone(before)
      after.range.endRow += enabled ? 1 : -1
      after.options.showFooter = enabled
      after.meta.nativeTotalsRowCount = enabled ? 1 : 0
      const cellValue: Record<number, Record<number, any>> = { [row]: {} }
      for (let column = area.startColumn; column <= area.endColumn; column++) {
        cellValue[row]![column] = enabled ? { s: { bl: 1 } } : { v: null, f: null, si: null, p: null, s: { bl: 0 } }
      }
      if (enabled) {
        const start = area.startRow + (info.showHeader ? 1 : 0)
        const filled: unknown[] = []
        for (let r = start; r <= area.endRow; r++) {
          const value = sheet.getRange(r, area.endColumn).getValue()
          if (value !== null && value !== undefined && value !== '') filled.push(value)
        }
        const fn = filled.length && filled.every(value => typeof value === 'number') ? 109 : 103
        if (area.endColumn > area.startColumn) Object.assign(cellValue[row]![area.startColumn], { v: 'Total', f: null, p: null })
        if (start <= area.endRow) Object.assign(cellValue[row]![area.endColumn], {
          v: null, p: null, f: `=SUBTOTAL(${fn},${formatAddress(start, area.endColumn)}:${formatAddress(area.endRow, area.endColumn)})`,
        })
      }
      const unitId = workbook.getId(), subUnitId = info.subUnitId, cells = { unitId, subUnitId, cellValue }
      const pairs = [
        { redo: { id: SetRangeValuesMutation.id, params: cells }, undo: { id: SetRangeValuesMutation.id, params: injector.invoke(SetRangeValuesUndoMutationFactory, cells) } },
        { redo: { id: STATE_MUTATION, params: { unitId, subUnitId, tableId, table: after } }, undo: { id: STATE_MUTATION, params: { unitId, subUnitId, tableId, table: before } } },
      ]
      for (const pair of pairs) { owned.add(pair.redo.params); owned.add(pair.undo.params) }
      const executed: typeof pairs = []
      try {
        for (const pair of pairs) {
          executed.push(pair)
          if (!commands.syncExecuteCommand(pair.redo.id, pair.redo.params)) throw new Error('汇总行修改未执行，修改已撤销')
        }
      } catch (error) {
        for (const pair of executed.reverse()) commands.syncExecuteCommand(pair.undo.id, pair.undo.params)
        throw error
      }
      history.pushUndoRedo({ unitID: unitId, redoMutations: pairs.map(pair => pair.redo), undoMutations: [...pairs].reverse().map(pair => pair.undo) })
      return true
    },
  }
}
