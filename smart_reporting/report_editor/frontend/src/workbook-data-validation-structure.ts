import { CustomCommandExecutionError, ICommandService } from '@univerjs/core'
import { TableManager } from '@univerjs/sheets-table'
import { SheetInterceptorService } from '@univerjs/sheets'
import { shiftFormulaText, shiftSpecOf } from '@sheets-web/xlsx-engine/structural'
import { cellShiftSpec } from '@sheets-web/xlsx-engine/cell-shift'
import { renameSheetInFormula } from '@sheets-web/xlsx-engine/sheets-edit'
import { createCfId } from '@univerjs/sheets-conditional-formatting'
import { planNativeConditionalFormattingStructure, planNativeConditionalFormattingRename } from './workbook-cf-structure-plan'
import { CF_MUTATION_IDS } from './workbook-conditional-formatting'
import { DV_MUTATION } from './workbook-data-validation'
import { structuralMutation } from './workbook-grid-operations'
import { preflightTableStructure } from './workbook-tables'
import { CELL_SHIFT_COMMANDS } from './workbook-cell-shift'
import { createCellShiftRawStyleGuard } from './workbook-cell-shift-raw-style'
import { assertConditionalFormattingSheetRemoval } from './workbook-cf-sheet-removal'
import { assertDataValidationSheetRemoval } from './workbook-dv-sheet-removal'
import { assertCellFormulaSheetRemoval } from './workbook-cell-formula-removal'
import { assertDefinedNameSheetRemoval } from './workbook-defined-name-removal'
const TABLE_MUTATION = /^sheet\.mutation\.(?:add-table|delete-table|set-sheet-table|set-table-filter)$/

// 使用官方拦截器将公式迁移并入同一次结构编辑及其撤销历史。
export function installDataValidationStructure(runtime: any, preflight?: (mutation: any) => void, removalPreflight?: (command: { id: string; params?: Record<string, any> }, workbook: any) => void, structuralPreflight?: (command: { id: string; params?: Record<string, any> }, workbook: any) => void) {
  const followers = new WeakSet<object>()
  const restoredMeta = new WeakMap<object, Record<string, any>>()
  const service = runtime.univer.__getInjector().get(SheetInterceptorService)
  const commands = runtime.univer.__getInjector().get(ICommandService)
  const rawStyles = createCellShiftRawStyleGuard()
  const beforeStyles = commands.beforeCommandExecuted?.((command: any) => {
    const workbook = runtime.univerAPI.getActiveWorkbook()
    try { structuralPreflight?.(command, workbook) }
    catch (error) {
      // 官方服务在 before listener 抛错时不会释放当前执行栈，拒绝时仅移除本调用身份。
      const stack = (commands as unknown as { _commandExecutionStack?: unknown[] })._commandExecutionStack
      const index = stack?.indexOf(command) ?? -1
      if (index >= 0) stack?.splice(index, 1)
      throw new CustomCommandExecutionError((error as Error).message)
    }
    rawStyles.begin(command, workbook)
  })
  const restore = commands.onCommandExecuted?.((command: any) => {
    rawStyles.clear(command)
    const meta = command.params && restoredMeta.get(command.params)
    if (meta) runtime.univer.__getInjector().get(TableManager).getTable(command.params.unitId, command.params.tableId)?.setTableMeta(structuredClone(meta))
  })
  const registration = service.interceptCommand({
    priority: -100,
    getMutations(command: any) {
      const result = { redos: [] as any[], undos: [] as any[] }
      const workbook = runtime.univerAPI.getActiveWorkbook()
      if (!workbook) return result
      const params = command.params ?? {}
      const target = params.subUnitId ? workbook.getSheetBySheetId(params.subUnitId) : workbook.getActiveSheet()
      if (!target) return result
      const mutationId: Record<string, string> = {
        'sheet.command.insert-row': 'sheet.mutation.insert-row',
        'sheet.command.remove-row': 'sheet.mutation.remove-rows',
        'sheet.command.insert-col': 'sheet.mutation.insert-col',
        'sheet.command.remove-col': 'sheet.mutation.remove-col',
      }
      const structural = params.range && mutationId[command.id] ? structuralMutation(mutationId[command.id]!, { ...params, subUnitId: target.getSheetId() }) : undefined
      const rename = command.id === 'sheet.command.set-worksheet-name' ? params.name : undefined
      if (!structural && !rename) return result
      for (const sheet of workbook.getSheets()) for (const { rule } of sheet.getDataValidations?.() ?? []) {
        const spec = structural ? shiftSpecOf(structural.op) : undefined
        if (spec && spec.delta < 0 && sheet.getSheetId() === target.getSheetId() && rule.ranges.every((range: any) => {
          const start = spec.axis === 'row' ? range.startRow : range.startColumn
          const end = spec.axis === 'row' ? range.endRow : range.endColumn
          return start >= spec.start && end < spec.start - spec.delta
        })) continue
        const before: Record<string, string> = {}, after: Record<string, string> = {}
        for (const key of ['formula1', 'formula2']) {
          if (typeof rule[key] !== 'string' || !rule[key].startsWith('=')) continue
          // Univer 自己的引用服务可能将本工作簿 id 写成外部簿限定符；文件中不能保留它。
          const formula = workbook.getSheets().reduce((value: string, item: any) =>
            renameSheetInFormula(value, '[' + workbook.getId() + ']' + item.getSheetName(), item.getSheetName()), rule[key])
          before[key] = rule[key]
          after[key] = rename ? renameSheetInFormula(formula, target.getSheetName(), rename)
            : shiftFormulaText(formula, shiftSpecOf(structural!.op), sheet.getSheetId() === target.getSheetId(), target.getSheetName())
        }
        if (!Object.keys(before).length || Object.keys(before).every(key => before[key] === after[key] && rule[key] === before[key])) continue
        const make = (payload: Record<string, string>) => ({ id: 'data-validation.mutation.updateRule', params: {
          unitId: workbook.getId(), subUnitId: sheet.getSheetId(), ruleId: rule.uid, payload: { type: 0, payload: {
            type: rule.type, operator: rule.operator, allowBlank: rule.allowBlank, formula1: rule.formula1, formula2: rule.formula2, ...payload,
          } }, source: 'patched',
        } })
        const redo = make(after), undo = make(before)
        followers.add(redo.params); followers.add(undo.params)
        result.redos.push(redo); result.undos.push(undo)
      }
      return result
    },
  })
  // 同时登记官方引用服务生成的从属更新；只按实际参数对象身份放行，不能信任 source 字符串。
  const original = service.onCommandExecute
  const collect = function (this: any, command: any) {
    try { structuralPreflight?.(command, runtime.univerAPI.getActiveWorkbook()) }
    catch (error) { throw new CustomCommandExecutionError((error as Error).message) }
    if (command.id === 'sheet.command.remove-sheet') {
      const workbook = runtime.univerAPI.getActiveWorkbook()
      try {
        removalPreflight?.(command, workbook)
        assertConditionalFormattingSheetRemoval(workbook, command.params?.subUnitId)
        assertDataValidationSheetRemoval(workbook, command.params?.subUnitId)
        assertCellFormulaSheetRemoval(workbook, command.params?.subUnitId)
        assertDefinedNameSheetRemoval(workbook, command.params?.subUnitId)
      } catch (error) { throw new CustomCommandExecutionError((error as Error).message) }
    }
    rawStyles.normalize(command)
    let insertions: ReturnType<typeof preflightTableStructure>
    try { insertions = preflightTableStructure(runtime.univerAPI.getActiveWorkbook(), command) }
    catch (error) { throw new CustomCommandExecutionError((error as Error).message) }
    const result = original.call(this, command)
    // CF分区与文件侧共用完整计划；官方Common helper跨表偏移与Add优先级不直接回放。
    const workbook = runtime.univerAPI.getActiveWorkbook()
    const params = command.params ?? {}
    const target = params.subUnitId ? workbook?.getSheetBySheetId(params.subUnitId) : workbook?.getActiveSheet()
    const mutationId: Record<string, string> = {
      'sheet.command.insert-row': 'sheet.mutation.insert-row', 'sheet.command.remove-row': 'sheet.mutation.remove-rows',
      'sheet.command.insert-col': 'sheet.mutation.insert-col', 'sheet.command.remove-col': 'sheet.mutation.remove-col',
    }
    const structural = target && params.range && mutationId[command.id]
      ? structuralMutation(mutationId[command.id]!, { ...params, subUnitId: target.getSheetId() }) : undefined
    const cellDirection = CELL_SHIFT_COMMANDS[command.id]
    const rename = command.id === 'sheet.command.set-worksheet-name' && typeof params.name === 'string' ? params.name : undefined
    const spec = structural ? shiftSpecOf(structural.op) : target && params.range && cellDirection ? cellShiftSpec(params.range, cellDirection) : undefined
    const trustedStructure = /^sheet\.command\.(?:insert-row|remove-row|insert-col|remove-col|set-worksheet-name)$/.test(command.id) || !!cellDirection
    if (trustedStructure) {
      // 先完成整个批次的可落盘检查，再替换CF；失败不得改变官方结果或登记归属。
      try {
        for (const mutation of [...(result.preRedos ?? []), ...result.redos]) {
          if (DV_MUTATION.test(mutation.id)) preflight?.(mutation)
        }
      } catch { throw new CustomCommandExecutionError('数据验证结构迁移预检失败') }
    }
    if ((spec || rename !== undefined) && workbook && target) {
      const plans = []
      try {
        for (const sheet of workbook.getSheets()) {
          const rules = sheet.getConditionalFormattingRules?.() ?? []
          if (!rules.length) continue
          plans.push(rename !== undefined ? planNativeConditionalFormattingRename(rules, workbook.getId(), sheet.getSheetId(), target.getSheetName(), rename)
            : planNativeConditionalFormattingStructure(rules, workbook.getId(), sheet.getSheetId(), sheet.getSheetName(), target.getSheetName(), spec!, createCfId, { geometry: cellDirection ? 'cells' : 'rows-columns' }))
        }
      } catch (error) { throw new CustomCommandExecutionError((error as Error).message) }
      // 所有sheet计划通过后才发布官方mutation批次，基础结构尚未执行。
      for (const key of ['redos', 'undos', 'preRedos', 'preUndos']) {
        if (result[key]) result[key] = result[key].filter((mutation: any) => !CF_MUTATION_IDS.has(mutation.id))
      }
      for (const plan of plans) {
        result.redos.push(...plan.redos)
        // 官方cells command登记历史时reverse整个undo批次；仅反序CF事务抵消它，保留其他followers。
        result.undos.push(...(cellDirection ? [...plan.undos].reverse() : plan.undos))
      }
    }
    // 表内插列复用文件引擎生成的列名，并把表头写入同一次官方结构历史。
    for (const mutation of result.redos) {
      const operation = mutation.params?.config?.rowColOperation
      const projected = insertions.get(mutation.params?.tableId)
      if (mutation.id === 'sheet.mutation.set-sheet-table' && projected && mutation.params?.config?.updateRange) mutation.params.config.updateRange.newRange = { ...projected.range }
      const records = projected?.insertions
      if (mutation.id !== 'sheet.mutation.set-sheet-table' || operation?.operationType !== 'insert' || operation.rowColType !== 'column' || !records) continue
      const table = runtime.univerAPI.getActiveWorkbook().getTableList().find((item: any) => item.id === mutation.params.tableId)
      let nextId = Math.max(0, ...table.columns.map((column: any) => Number(column.id))) + 1
      operation.columnsJson = records.flatMap(record => record.columns.map(column => ({ id: String(nextId++), displayName: column.name, dataType: 'string', formula: '', meta: {}, style: {} })))
      const cellValue: Record<number, Record<number, { v: string; t: number }>> = {}
      for (const record of records) if (record.headerRow !== null) {
        for (const column of record.columns) (cellValue[record.headerRow] ??= {})[column.column] = { v: column.name, t: 1 }
      }
      if (Object.keys(cellValue).length) result.redos.push({ id: 'sheet.mutation.set-range-values', params: { unitId: mutation.params.unitId, subUnitId: mutation.params.subUnitId, cellValue } })
    }
    if (trustedStructure || command.id === 'sheet.command.remove-sheet') {
      for (const batch of [result.redos, result.undos, result.preRedos, result.preUndos]) {
        for (const mutation of batch ?? []) {
          if ((DV_MUTATION.test(mutation.id) || TABLE_MUTATION.test(mutation.id) || CF_MUTATION_IDS.has(mutation.id)) && mutation.params) followers.add(mutation.params)
          if (mutation.id === 'sheet.mutation.add-table') {
            const table = runtime.univerAPI.getActiveWorkbook()?.getTableList?.().find((item: any) => item.id === mutation.params.tableId)
            if (table?.meta) restoredMeta.set(mutation.params, structuredClone(table.meta))
          }
        }
      }
    }
    return result
  }
  service.onCommandExecute = collect
  return { dispose() { registration.dispose(); beforeStyles?.dispose(); restore?.dispose(); rawStyles.clear(); if (service.onCommandExecute === collect) service.onCommandExecute = original },
    ownsMutation: (params: object) => followers.has(params) }
}
