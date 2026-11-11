import { CommandType, ICommandService, IUndoRedoService, extractPureTextFromCell, generateRandomId } from '@univerjs/core'
import { SetRangeValuesMutation, SetRangeValuesUndoMutationFactory } from '@univerjs/sheets'
import { TableManager } from '@univerjs/sheets-table'
import { IDefinedNamesService, SetDefinedNameMutation, SetSuperTableMutation } from '@univerjs/engine-formula'
import { UpdateDataValidationMutation } from '@univerjs/data-validation'
import { parseRange, formatAddress } from '@sheets-web/xlsx-engine'
import { renameImplicitTableColumns, renameTableColumns } from './workbook-table-references'
import type { TableColumnChangeReason } from './workbook-table-pivot-source'

type Area = { startRow: number; endRow: number; startColumn: number; endColumn: number }
const STATE_MUTATION = 'sheet.mutation.native-table-resize-state'
const overlaps = (a: Area, b: Area) => a.startRow <= b.endRow && b.startRow <= a.endRow && a.startColumn <= b.endColumn && b.startColumn <= a.endColumn
const sameArea = (a: Area, b: Area) => (Object.keys(a) as (keyof Area)[]).every(key => a[key] === b[key])
function readArea(address: string): Area {
  if (!/^\$?[A-Za-z]{1,3}\$?[1-9]\d*(?::\$?[A-Za-z]{1,3}\$?[1-9]\d*)?$/.test(address.trim())) throw new Error('表格范围无效，请使用当前工作表的A1区域')
  const area = parseRange(address.trim().replaceAll('$', ''))
  if (area.endRow > 1048575 || area.endColumn > 16383 || area.startRow > area.endRow || area.startColumn > area.endColumn) throw new Error('表格范围超出工作表边界')
  return area
}
function uniqueNames(values: string[]): string[] {
  const used = new Set<string>()
  return values.map((value, index) => {
    const base = value.trim().slice(0, 255) || `Column${index + 1}`
    let name = base
    for (let suffix = 2; used.has(name.toLowerCase()); suffix++) {
      const tail = String(suffix)
      name = base.slice(0, 255 - tail.length) + tail
    }
    used.add(name.toLowerCase())
    return name
  })
}

// 固定源 resizeTable/moveTotalsRow：先规划全部变更，再共用官方mutation与一条撤销历史。
export function installTableResize(runtime: any, protectedSheet: (id: string) => boolean = () => false, columnChangeReason?: TableColumnChangeReason) {
  const injector = runtime.univer.__getInjector()
  const commands = injector.get(ICommandService), history = injector.get(IUndoRedoService), tables = injector.get(TableManager)
  const owned = new WeakSet<object>()
  let disposed = false
  const registration = commands.registerCommand({ id: STATE_MUTATION, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (!params || !owned.has(params)) return false
      const table = tables.getTable(params.unitId, params.tableId)
      if (!table || table.getSubunitId() !== params.subUnitId) return false
      tables.updateTableRange(params.unitId, params.tableId, { newRange: structuredClone(params.range) })
      table.setColumns(structuredClone(params.columns))
      const info = table.getTableInfo()
      return commands.syncExecuteCommand(SetSuperTableMutation.id, { unitId: params.unitId, tableName: info.name,
        reference: { range: { ...info.range, endRow: info.range.endRow - (info.meta?.nativeTotalsRowCount ?? 0) },
          sheetId: info.subUnitId, titleMap: new Map(info.columns.map((column: any, index: number) => [column.displayName, index])) } })
    },
  })
  return {
    ownsMutation: (params: object) => owned.has(params),
    dispose() { disposed = true; registration.dispose() },
    resize(tableId: string, rangeA1: string): boolean {
      if (disposed) throw new Error('表格设计已关闭')
      const workbook = runtime.univerAPI.getActiveWorkbook(), live = workbook?.getTableList() ?? []
      const table = live.find((item: any) => item.id === tableId)
      if (!table) throw new Error('当前表格不存在，请重新选择')
      const current: Area = table.range, next = readArea(rangeA1), unitId = workbook.getId(), subUnitId = table.subUnitId
      const sheet = workbook.getSheetBySheetId(subUnitId), core = sheet.getSheet()
      const hasHeader = table.showHeader, totals = table.meta?.nativeTotalsRowCount ?? 0
      if (next.endColumn - next.startColumn + 1 > 1000) throw new Error('表格范围最多支持1000列')
      if (hasHeader && next.startRow !== current.startRow) throw new Error('调整范围时必须保持原表头行')
      if (!overlaps(current, next)) throw new Error('新范围必须与原表格交叠')
      if (next.endRow - next.startRow + 1 <= (hasHeader ? 1 : 0) + totals) throw new Error('表格必须至少保留一行数据')
      if (protectedSheet(subUnitId)) throw new Error('表格所在工作表受保护，请先撤销保护')
      if (live.some((other: any) => other.id !== tableId && other.subUnitId === subUnitId && overlaps(other.range, next))) throw new Error('新范围与其他表格交叠')
      if (core.getMergeData().some((merge: Area) => overlaps(merge, next))) throw new Error('新表格范围包含合并单元格，请先取消合并')
      if (sameArea(current, next)) return true
      const raw = (row: number, column: number) => core.getCellMatrix().getValue(row, column)
      const free = (row: number, area: Area) => {
        for (let column = area.startColumn; column <= area.endColumn; column++) {
          const cell = raw(row, column)
          if (cell?.f || cell?.p || cell?.v !== null && cell?.v !== undefined && cell?.v !== '') return false
        }
        return true
      }
      if (totals && next.endRow > current.endRow && !free(next.endRow, next)) throw new Error('汇总行目标位置已有内容，不能移动')
      const cellValue: Record<number, Record<number, any>> = {}
      const write = (row: number, column: number, cell: any) => { (cellValue[row] ??= {})[column] = cell }
      const width = next.endColumn - next.startColumn + 1
      const names = uniqueNames(Array.from({ length: width }, (_, index) => {
        const column = next.startColumn + index
        return hasHeader ? extractPureTextFromCell(raw(next.startRow, column)) : table.columns[column - current.startColumn]?.displayName ?? ''
      }))
      const reason = columnChangeReason?.(table, names, next.startColumn)
      if (reason) throw new Error(reason)
      const columns = names.map((displayName, index) => {
        const previous = table.columns[next.startColumn + index - current.startColumn]
        return previous ? { ...previous, displayName } : { id: generateRandomId(), displayName, dataType: 'string', formula: '', meta: {}, style: {} }
      })
      if (hasHeader) names.forEach((name, index) => {
        const column = next.startColumn + index, cell = raw(next.startRow, column)
        if (name !== cell?.v || cell?.p || cell?.f) write(next.startRow, column, { v: name, t: 1, f: null, si: null, p: null })
      })
      if (totals && next.endRow !== current.endRow && free(next.endRow, next)) {
        const styles = workbook.getWorkbook().getStyles()
        for (let column = current.startColumn; column <= current.endColumn; column++) write(current.endRow, column, { v: null, f: null, si: null, p: null, s: { bl: null } })
        for (let column = next.startColumn; column <= next.endColumn; column++) {
          const cell = column >= current.startColumn && column <= current.endColumn ? raw(current.endRow, column) : null
          const style = styles.getStyleByCell(cell)
          write(next.endRow, column, cell ? { ...structuredClone(cell), s: { ...structuredClone(style), bl: 1 } } : { v: null, s: { bl: 1 } })
        }
      }
      if (totals) for (let column = next.startColumn; column <= next.endColumn; column++) {
        const cell = cellValue[next.endRow]?.[column] ?? raw(next.endRow, column)
        const match = /^=SUBTOTAL\((\d+),/.exec(cell?.f ?? '')
        if (match) write(next.endRow, column, { ...cell,
          f: `=SUBTOTAL(${match[1]},${formatAddress(next.startRow + (hasHeader ? 1 : 0), column)}:${formatAddress(next.endRow - 1, column)})` })
      }
      const renames = new Map<string, string>()
      for (let index = 0; index < columns.length; index++) {
        const previous = table.columns[next.startColumn + index - current.startColumn]
        if (previous && previous.displayName !== names[index]) renames.set(previous.displayName.toLowerCase(), names[index]!)
      }
      const rewrite = (formula: string) => renameTableColumns(formula, table.name, renames)
      const pairs: { redo: { id: string; params: any }; undo: { id: string; params: any } }[] = []
      const add = (id: string, before: any, after: any) => {
        owned.add(before); owned.add(after)
        pairs.push({ undo: { id, params: before }, redo: { id, params: after } })
      }
      const namePairs: { before: any; after: any }[] = [], validationPairs: { before: any; after: any }[] = []
      const sheetWrites = new Map<string, Record<number, Record<number, any>>>([[subUnitId, cellValue]])
      if (renames.size) for (const consumer of workbook.getSheets()) {
        const id = consumer.getSheetId(), values = sheetWrites.get(id) ?? {}
        const projected = Object.entries(values).flatMap(([row, cells]) => Object.entries(cells).map(([column, cell]) => ({ row: Number(row), column: Number(column), cell })))
        let affected = false
        const visit = (row: number, column: number, cell: any) => {
          if (typeof cell?.f !== 'string') return
          let formula = rewrite(cell.f)
          if (id === subUnitId && row >= next.startRow && row <= next.endRow && column >= next.startColumn && column <= next.endColumn) {
            formula = renameImplicitTableColumns(formula, renames)
          }
          if (formula !== cell.f) { (values[row] ??= {})[column] = { ...values[row]?.[column], f: formula }; affected = true }
        }
        consumer.getSheet().getCellMatrix().forValue((row: number, column: number, cell: any) => {
          if (!Object.hasOwn(values[row] ?? {}, column)) visit(row, column, cell)
        })
        for (const { row, column, cell } of projected) visit(row, column, cell)
        for (const { rule } of consumer.getDataValidations()) {
          const changes: Record<string, string> = {}
          for (const key of ['formula1', 'formula2']) if (typeof rule[key] === 'string') {
            const formula = rewrite(rule[key])
            if (formula !== rule[key]) changes[key] = formula
          }
          if (!Object.keys(changes).length) continue
          affected = true
          const make = (changes: Record<string, string>) => ({ unitId, subUnitId: id, ruleId: rule.uid,
            payload: { type: 0, payload: { type: rule.type, operator: rule.operator, allowBlank: rule.allowBlank,
              formula1: rule.formula1, formula2: rule.formula2, ...changes } }, source: 'patched' })
          validationPairs.push({ before: make({}), after: make(changes) })
        }
        if (affected && protectedSheet(id)) throw new Error(`工作表“${consumer.getSheetName()}”受保护且引用此表格列，请先撤销保护`)
        if (Object.keys(values).length) sheetWrites.set(id, values)
      }
      if (renames.size) for (const entry of Object.values(injector.get(IDefinedNamesService).getDefinedNameMap(unitId) ?? {}) as any[]) {
        const formula = rewrite(entry.formulaOrRefString)
        if (formula === entry.formulaOrRefString) continue
        if (entry.localSheetId && protectedSheet(entry.localSheetId)) throw new Error('引用此表格列的定义名称所在工作表受保护，请先撤销保护')
        namePairs.push({ before: { ...entry, unitId }, after: { ...entry, unitId, formulaOrRefString: formula } })
      }
      for (const [id, values] of sheetWrites) if (Object.keys(values).length) {
        const after = { unitId, subUnitId: id, cellValue: values }
        add(SetRangeValuesMutation.id, injector.invoke(SetRangeValuesUndoMutationFactory, after), after)
      }
      const params = { unitId, subUnitId, tableId }
      add(STATE_MUTATION, { ...params, range: structuredClone(current), columns: structuredClone(table.columns) }, { ...params, range: next, columns })
      for (const pair of validationPairs) add(UpdateDataValidationMutation.id, pair.before, pair.after)
      for (const pair of namePairs) add(SetDefinedNameMutation.id, pair.before, pair.after)
      const executed: typeof pairs = []
      try {
        for (const pair of pairs) {
          // 自有状态mutation可能在嵌套注册失败前已修改模型，也必须进入回滚集合。
          executed.push(pair)
          if (!commands.syncExecuteCommand(pair.redo.id, pair.redo.params)) throw new Error('调整表格范围未执行，修改已撤销')
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
