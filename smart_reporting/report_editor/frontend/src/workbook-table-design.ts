import { ICommandService, IUndoRedoService } from '@univerjs/core'
import { SetRangeValuesMutation, SetRangeValuesUndoMutationFactory } from '@univerjs/sheets'
import { SetSheetTableMutation } from '@univerjs/sheets-table'
import { IDefinedNamesService, SetDefinedNameMutation } from '@univerjs/engine-formula'
import { UpdateDataValidationMutation } from '@univerjs/data-validation'
import { renameTableReferences } from './workbook-table-references'

// 固定源 table-design.ts：Unicode字母、下划线或反斜杠起首，排除A1/R1C1地址。
function validName(name: string): boolean {
  return name.length > 0 && name.length <= 255 && /^[\p{L}_\\][\p{L}\p{N}_.\\]*$/u.test(name) &&
    !/^(\$?[A-Za-z]{1,3}\$?[0-9]+|[rR]\d*[cC]\d*)$/.test(name)
}

// 所有消费者先完成规划与保护检查，官方mutation共用一条撤销历史。
export function installTableDesign(runtime: any, protectedSheet: (id: string) => boolean = () => false) {
  const injector = runtime.univer.__getInjector()
  const commands = injector.get(ICommandService), history = injector.get(IUndoRedoService)
  const owned = new WeakSet<object>()
  let disposed = false
  return {
    ownsMutation: (params: object) => owned.has(params),
    dispose() { disposed = true },
    rename(tableId: string, rawName: string): boolean {
      if (disposed) throw new Error('表格设计已关闭')
      const workbook = runtime.univerAPI.getActiveWorkbook()
      const tables = workbook?.getTableList() ?? []
      const table = tables.find((item: any) => item.id === tableId)
      if (!table) throw new Error('当前表格不存在，请重新选择')
      const name = rawName.trim(), unitId = workbook.getId()
      if (name === table.name) return true
      if (!validName(name)) throw new Error('表格名称无效：请使用不超过255字符的名称，且不能为单元格地址')
      const definedNames = Object.values(injector.get(IDefinedNamesService).getDefinedNameMap(unitId) ?? {}) as any[]
      if (tables.some((item: any) => item.id !== tableId && item.name.toLowerCase() === name.toLowerCase()) ||
          definedNames.some(item => item.name.toLowerCase() === name.toLowerCase())) throw new Error('表格名称与工作簿中已有的表格或定义名称冲突')
      if (protectedSheet(table.subUnitId)) throw new Error('表格所在工作表受保护，请先撤销保护')
      const rewrite = (formula: string) => renameTableReferences(formula, table.name, name)
      const pairs: { redo: { id: string; params: any }; undo: { id: string; params: any } }[] = []
      const add = (id: string, before: any, after: any) => {
        owned.add(before); owned.add(after)
        pairs.push({ undo: { id, params: before }, redo: { id, params: after } })
      }
      const tableParams = { unitId, subUnitId: table.subUnitId, tableId }
      // TableManager的名称事件同步官方SuperTable注册，不另建第二套表格注册表。
      add(SetSheetTableMutation.id, { ...tableParams, config: { name: table.name } }, { ...tableParams, config: { name } })
      for (const sheet of workbook.getSheets()) {
        const subUnitId = sheet.getSheetId(), cellValue: Record<number, Record<number, { f: string }>> = {}
        let affected = false
        sheet.getSheet().getCellMatrix().forValue((row: number, column: number, cell: any) => {
          if (typeof cell?.f !== 'string') return
          const formula = rewrite(cell.f)
          if (formula !== cell.f) { (cellValue[row] ??= {})[column] = { f: formula }; affected = true }
        })
        if (Object.keys(cellValue).length) {
          const after = { unitId, subUnitId, cellValue }
          add(SetRangeValuesMutation.id, injector.invoke(SetRangeValuesUndoMutationFactory, after), after)
        }
        for (const { rule } of sheet.getDataValidations()) {
          const changes: Record<string, string> = {}
          for (const key of ['formula1', 'formula2']) if (typeof rule[key] === 'string') {
            const formula = rewrite(rule[key])
            if (formula !== rule[key]) changes[key] = formula
          }
          if (!Object.keys(changes).length) continue
          affected = true
          const make = (changes: Record<string, string>) => ({ unitId, subUnitId, ruleId: rule.uid,
            payload: { type: 0, payload: { type: rule.type, operator: rule.operator, allowBlank: rule.allowBlank,
              formula1: rule.formula1, formula2: rule.formula2, ...changes } }, source: 'patched' })
          add(UpdateDataValidationMutation.id, make({}), make(changes))
        }
        if (affected && protectedSheet(subUnitId)) throw new Error(`工作表“${sheet.getSheetName()}”受保护且引用此表格，请先撤销保护`)
      }
      for (const entry of definedNames) {
        const formula = rewrite(entry.formulaOrRefString)
        if (formula === entry.formulaOrRefString) continue
        if (entry.localSheetId && protectedSheet(entry.localSheetId)) throw new Error('引用此表格的定义名称所在工作表受保护，请先撤销保护')
        add(SetDefinedNameMutation.id, { ...entry, unitId }, { ...entry, unitId, formulaOrRefString: formula })
      }
      const executed: typeof pairs = []
      try {
        for (const pair of pairs) {
          if (!commands.syncExecuteCommand(pair.redo.id, pair.redo.params)) throw new Error('表格更名未执行，修改已撤销')
          executed.push(pair)
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
