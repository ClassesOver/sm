import { CommandType, CustomCommandExecutionError, ICommandService, IUndoRedoService, RedoCommand, LifecycleService, LifecycleStages, extractPureTextFromCell } from '@univerjs/core'
import { ISheetClipboardService, mergeSetRangeValues } from '@univerjs/sheets-ui'
import { followTableHeaderPaste } from './workbook-table-paste'
import { SheetInterceptorService, SheetsSelectionsService, getVisibleRanges, SetRangeValuesMutation, SetRangeValuesUndoMutationFactory } from '@univerjs/sheets'
import { TableManager } from '@univerjs/sheets-table'
import { IDefinedNamesService, SetDefinedNameMutation, SetSuperTableMutation } from '@univerjs/engine-formula'
import { renameImplicitTableColumns, renameTableColumns } from './workbook-table-references'
import type { TableColumnChangeReason } from './workbook-table-pivot-source'

interface ColumnRename {
  name: string
  columns: Map<string, string>
  subUnitId: string
  range: { startRow: number; endRow: number; startColumn: number; endColumn: number }
}

function rewriteColumns(formula: string, renames: readonly ColumnRename[], location?: { subUnitId: string; row: number; column: number }): string {
  return renames.reduce((value, table) => {
    const explicit = renameTableColumns(value, table.name, table.columns)
    const range = table.range
    return location?.subUnitId === table.subUnitId && location.row >= range.startRow && location.row <= range.endRow &&
      location.column >= range.startColumn && location.column <= range.endColumn
      ? renameImplicitTableColumns(explicit, table.columns) : explicit
  }, formula)
}

export const TABLE_COLUMNS_MUTATION = 'sheet.mutation.native-table-columns'

// 固定源 table-design.ts uniqueColumnNames：空白补列名，重复按大小写无关追加序号。
function uniqueColumnNames(headers: readonly unknown[]): string[] {
  const used = new Set<string>()
  return headers.map((raw, index) => {
    const base = String(raw ?? '').trim().slice(0, 255) || `Column${index + 1}`
    let candidate = base
    for (let suffix = 2; used.has(candidate.toLowerCase()); suffix += 1) {
      const tail = String(suffix)
      candidate = base.slice(0, 255 - tail.length) + tail
    }
    used.add(candidate.toLowerCase())
    return candidate
  })
}

function proposedColumns(table: any, values: any): string[] {
  return uniqueColumnNames(table.columns.map((column: any, index: number) => {
    const cell = values[table.range.startColumn + index]
    return cell === null ? '' : cell && (Object.hasOwn(cell, 'v') || cell.p) ? extractPureTextFromCell(cell) : column.displayName
  }))
}

function writesHeader(table: any, values: any): boolean {
  return !!values && table.columns.some((_column: any, index: number) => {
    const cell = values[table.range.startColumn + index]
    return cell === null || cell && (Object.hasOwn(cell, 'v') || Object.hasOwn(cell, 'p') || Object.hasOwn(cell, 'f'))
  })
}

// 基础写入前检查受保护消费者，避免改完表头才发现文件无法保存。
export function tableHeaderProtectionReason(workbook: any, command: any, protectedSheet: (id: string) => boolean, columnChangeReason?: TableColumnChangeReason): string | undefined {
  if (command.id !== 'sheet.mutation.set-range-values') return
  const params = command.params
  if (!workbook || params?.unitId !== workbook.getId()) return
  const changes = workbook.getTableList().flatMap((table: any) => {
    const values = params.cellValue?.[table.range.startRow]
    if (table.subUnitId !== params.subUnitId || !table.showHeader || !writesHeader(table, values)) return []
    const names = proposedColumns(table, values)
    const columns = new Map<string, string>(table.columns.flatMap((column: any, index: number) =>
      column.displayName === names[index] ? [] : [[column.displayName.toLowerCase(), names[index]]]))
    return columns.size ? [{ name: table.name, columns, subUnitId: table.subUnitId, range: table.range, table, names }] : []
  })
  if (!changes.length) return
  for (const change of changes) {
    const reason = columnChangeReason?.(change.table, change.names)
    if (reason) return reason
  }
  const changed = (formula: unknown, location?: { subUnitId: string; row: number; column: number }) => typeof formula === 'string' && rewriteColumns(formula, changes, location) !== formula
  for (const sheet of workbook.getSheets()) {
    if (!protectedSheet(sheet.getSheetId())) continue
    let affected = sheet.getDataValidations().some(({ rule }: any) => changed(rule.formula1) || changed(rule.formula2))
    sheet.getSheet().getCellMatrix().forValue((row: number, column: number, cell: any) => {
      if (changed(cell?.f, { subUnitId: sheet.getSheetId(), row, column })) affected = true
    })
    if (affected) return `工作表“${sheet.getSheetName()}”受保护且引用此表格列，请先撤销该表保护再更名`
  }
}

// 官方 set-range-values 已应用单元格后调用 interceptor；列变更加入同一撤销历史。
export function installTableHeaders(runtime: any, protectedSheet: (id: string) => boolean = () => false, columnChangeReason?: TableColumnChangeReason, onRejected?: (message: string) => void) {
  const injector = runtime.univer.__getInjector()
  const commands = injector.get(ICommandService)
  const owned = new WeakSet<object>()
  const mutation = commands.registerCommand({ id: TABLE_COLUMNS_MUTATION, type: CommandType.MUTATION,
    handler: (_accessor: unknown, params: any) => {
      if (!params || !owned.has(params)) return false
      const table = injector.get(TableManager).getTable(params.unitId, params.tableId)
      if (!table || table.getSubunitId() !== params.subUnitId) return false
      table.setColumns(structuredClone(params.columns))
      const info = table.getTableInfo()
      return commands.syncExecuteCommand(SetSuperTableMutation.id, { unitId: params.unitId, tableName: info.name,
        reference: { range: info.range, sheetId: info.subUnitId,
          titleMap: new Map(info.columns.map((column: any, index: number) => [column.displayName, index])) } })
    },
  })
  const plan = (command: any) => {
    const result = { redos: [] as any[], undos: [] as any[] }
    const clearing = /^sheet\.command\.clear-selection-(?:content|all)$/.test(command.id)
    if (command.id !== 'sheet.command.set-range-values' && !clearing && !command.paste) return result
    const workbook = runtime.univerAPI.getActiveWorkbook()
    let params = command.params
    let clearedRanges: any[] = []
    if (clearing && workbook) {
      const sheetId = params?.subUnitId ?? workbook.getActiveSheet().getSheetId()
      const ranges = params?.ranges ?? injector.get(SheetsSelectionsService).getCurrentSelections()?.map((selection: any) => selection.range) ?? []
      clearedRanges = injector.invoke((accessor: any) => getVisibleRanges(ranges, accessor, workbook.getId(), sheetId))
      const cellValue: Record<number, Record<number, null>> = {}
      for (const table of workbook.getTableList()) if (table.subUnitId === sheetId && table.showHeader) {
        const row = table.range.startRow
        for (let column = table.range.startColumn; column <= table.range.endColumn; column++) {
          if (clearedRanges.some(range => row >= range.startRow && row <= range.endRow && column >= range.startColumn && column <= range.endColumn)) (cellValue[row] ??= {})[column] = null
        }
      }
      params = { unitId: workbook.getId(), subUnitId: sheetId, cellValue }
    }
    if (!workbook || params?.unitId !== workbook.getId()) return result
    const renames: ColumnRename[] = []
    for (const table of workbook.getTableList()) {
      if (table.subUnitId !== params.subUnitId || !table.showHeader) continue
      const values = params.cellValue?.[table.range.startRow]
      if (!writesHeader(table, values)) continue
      const rawNames = table.columns.map((column: any, index: number) => {
        const cell = values[table.range.startColumn + index]
        return cell === null ? '' : cell && (Object.hasOwn(cell, 'v') || cell.p) ? extractPureTextFromCell(cell) : column.displayName
      })
      const names = uniqueColumnNames(rawNames)
      const reason = columnChangeReason?.(table, names)
      if (reason) {
        if (!command.paste) onRejected?.(reason)
        throw new CustomCommandExecutionError(reason)
      }
      const columns = table.columns.map((column: any, index: number) => ({ ...column, displayName: names[index] }))
      const corrections: Record<number, any> = {}, untouched: Record<number, any> = {}
      names.forEach((name, index) => {
        if (name === rawNames[index]) return
        const column = table.range.startColumn + index
        corrections[column] = { v: name, t: 1, f: null, si: null, p: null }
        if (!Object.hasOwn(values, column)) untouched[column] = corrections[column]
      })
      if (Object.keys(corrections).length) {
        result.redos.push({ id: SetRangeValuesMutation.id, params: { unitId: params.unitId, subUnitId: params.subUnitId,
          cellValue: { [table.range.startRow]: corrections } } })
        if (Object.keys(untouched).length) result.undos.push({ id: SetRangeValuesMutation.id,
          params: injector.invoke(SetRangeValuesUndoMutationFactory, { unitId: params.unitId, subUnitId: params.subUnitId,
            cellValue: { [table.range.startRow]: untouched } }) })
      }
      if (columns.every((column: any, index: number) => column.displayName === table.columns[index].displayName)) continue
      renames.push({ name: table.name, subUnitId: table.subUnitId, range: { ...table.range }, columns: new Map(table.columns.flatMap((column: any, index: number) =>
        column.displayName === names[index] ? [] : [[column.displayName.toLowerCase(), names[index]]])) })
      const make = (columns: any[]) => {
        const payload = { unitId: params.unitId, subUnitId: params.subUnitId, tableId: table.id, columns: structuredClone(columns) }
        owned.add(payload)
        return { id: TABLE_COLUMNS_MUTATION, params: payload }
      }
      result.redos.push(make(columns)); result.undos.push(make(table.columns))
    }
    if (renames.length) {
      const rewrite = (formula: string, location?: { subUnitId: string; row: number; column: number }) => rewriteColumns(formula, renames, location)
      const follow = (id: string, before: any, after: any) => {
        owned.add(before); owned.add(after)
        result.undos.push({ id, params: before }); result.redos.push({ id, params: after })
      }
      for (const sheet of workbook.getSheets()) {
        for (const { rule } of sheet.getDataValidations()) {
          const changes: Record<string, string> = {}
          for (const key of ['formula1', 'formula2']) if (typeof rule[key] === 'string' && rule[key].startsWith('=')) {
            const value = rewrite(rule[key])
            if (value !== rule[key]) changes[key] = value
          }
          if (!Object.keys(changes).length) continue
          const make = (changes: Record<string, string>) => ({ unitId: params.unitId, subUnitId: sheet.getSheetId(), ruleId: rule.uid,
            payload: { type: 0, payload: { type: rule.type, operator: rule.operator, allowBlank: rule.allowBlank,
              formula1: rule.formula1, formula2: rule.formula2, ...changes } }, source: 'patched' })
          follow('data-validation.mutation.updateRule', make({}), make(changes))
        }
        const cellValue: Record<number, Record<number, any>> = {}
        sheet.getSheet().getCellMatrix().forValue((row: number, column: number, cell: any) => {
          const pasted = command.paste && sheet.getSheetId() === params.subUnitId ? params.cellValue?.[row]?.[column] : undefined
          if (pasted === null || pasted && (Object.hasOwn(pasted, 'f') || Object.hasOwn(pasted, 'v') || Object.hasOwn(pasted, 'p'))) return
          if (typeof cell?.f !== 'string') return
          if (clearing && sheet.getSheetId() === params.subUnitId && clearedRanges.some(range => row >= range.startRow && row <= range.endRow && column >= range.startColumn && column <= range.endColumn)) return
          const formula = rewrite(cell.f, { subUnitId: sheet.getSheetId(), row, column })
          if (formula !== cell.f) (cellValue[row] ??= {})[column] = { f: formula }
        })
        if (command.paste && sheet.getSheetId() === params.subUnitId) {
          for (const [row, cells] of Object.entries(params.cellValue) as [string, Record<string, any>][]) {
            for (const [column, cell] of Object.entries(cells)) if (typeof cell?.f === 'string') {
              const formula = rewrite(cell.f, { subUnitId: sheet.getSheetId(), row: Number(row), column: Number(column) })
              if (formula !== cell.f) (cellValue[Number(row)] ??= {})[Number(column)] = { f: formula }
            }
          }
        }
        if (Object.keys(cellValue).length) {
          const after = { unitId: params.unitId, subUnitId: sheet.getSheetId(), cellValue }
          const before = injector.invoke(SetRangeValuesUndoMutationFactory, after)
          // 基础 mutation 的 undo 已恢复同批写入的格子，不能被从属历史再次覆盖。
          if (sheet.getSheetId() === params.subUnitId) for (const [row, cells] of Object.entries(before.cellValue) as [string, Record<string, unknown>][]) {
            for (const column of Object.keys(cells)) if (Object.hasOwn(params.cellValue?.[row] ?? {}, column)) delete cells[column]
            if (!Object.keys(cells).length) delete before.cellValue[row]
          }
          follow(SetRangeValuesMutation.id, before, after)
        }
      }
      const names = injector.get(IDefinedNamesService).getDefinedNameMap(params.unitId) ?? {}
      for (const entry of Object.values(names) as any[]) {
        const formula = rewrite(entry.formulaOrRefString)
        if (formula !== entry.formulaOrRefString) follow(SetDefinedNameMutation.id, { ...entry, unitId: params.unitId },
          { ...entry, unitId: params.unitId, formulaOrRefString: formula })
      }
    }
    return result
  }
  const interceptor = injector.get(SheetInterceptorService).interceptCommand({ getMutations: plan })
  let disposed = false
  const restores: (() => void)[] = []
  const installPaste = () => {
    if (disposed || !injector.has(ISheetClipboardService)) return
    const clipboard = injector.get(ISheetClipboardService)
    restores.push(followTableHeaderPaste(clipboard, batch => {
      const result = { redos: [] as any[], undos: [] as any[] }
      for (const mutation of mergeSetRangeValues(batch.redos.filter(item => item.id === SetRangeValuesMutation.id))) {
        const reason = tableHeaderProtectionReason(runtime.univerAPI.getActiveWorkbook(), mutation, protectedSheet, columnChangeReason)
        if (reason) throw new Error(reason)
        const followers = plan({ id: 'native-table-paste', params: mutation.params, paste: true })
        result.redos.push(...followers.redos); result.undos.push(...followers.undos)
      }
      return result
    }, onRejected, () => {
      const history = injector.get(IUndoRedoService), before = history.pitchTopUndoElement()
      return () => {
        // 官方重新粘贴先撤销上次成功批次；仅恢复本次确实移入 redo 的同一元素。
        if (before && history.pitchTopRedoElement() === before && !commands.syncExecuteCommand(RedoCommand.id)) {
          throw new Error('字段修改已拒绝，但先前粘贴未能恢复，请检查工作表')
        }
      }
    }))
  }
  if (ISheetClipboardService && injector.has(ISheetClipboardService)) installPaste()
  else injector.get(LifecycleService).onStage(LifecycleStages.Rendered).then(() => setTimeout(installPaste, 0), () => undefined)
  return { ownsMutation: (params: object) => owned.has(params), dispose() { disposed = true; restores.forEach(restore => restore()); interceptor.dispose(); mutation.dispose() } }
}
