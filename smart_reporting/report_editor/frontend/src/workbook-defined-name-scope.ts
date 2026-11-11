import { ICommandService, generateRandomId } from '@univerjs/core'
import { InsertDefinedNameCommand, SetDefinedNameCommand, RemoveDefinedNameCommand, SheetInterceptorService } from '@univerjs/sheets'
import type { DefinedNameAction } from './workbook-defined-names'
import { IFormulaCurrentConfigService, IDefinedNamesService, SetDefinedNameMutation, RemoveDefinedNameMutation, Lexer, LexerTreeBuilder, isReferenceString } from '@univerjs/engine-formula'

import { shiftFormulaText, shiftSpecOf } from '@sheets-web/xlsx-engine/structural'
import { structuralMutation } from './workbook-grid-operations'

const scopedActions = new Set<(workbook: any, action: DefinedNameAction) => boolean>()
export function applyScopedDefinedNameAction(workbook: any, action: DefinedNameAction): boolean {
  for (const apply of scopedActions) if (apply(workbook, action)) return true
  return false
}

const GLOBAL = 'AllDefaultWorkbook'

// 官方 registry 保留所有作用域，但 0.25.1 的 name cache 不区分工作表；计算副本
// 复用官方词法节点展开名称，原公式、registry、保存内容都保持原文。
export function resolveScopedDefinedName(names: any, unitId: string, sheetId: string, name: string) {
  const matches = Object.values(names.getDefinedNameMap(unitId) ?? {}).filter((entry: any) => entry.name.toLowerCase() === name.toLowerCase()) as any[]
  return matches.find(entry => entry.localSheetId === sheetId) ?? matches.find(entry => !entry.localSheetId || entry.localSheetId === GLOBAL)
}

export function installDefinedNameScopes(runtime: any) {
  const injector = runtime.univer.__getInjector(), names = injector.get(IDefinedNamesService), config = injector.get(IFormulaCurrentConfigService)
  const lexer = injector.get(Lexer), builder = injector.get(LexerTreeBuilder), original = lexer.treeBuilder
  const expand = (formula: string, unitId: string, sheetId: string, visited: ReadonlySet<string>, used: Set<string>, qualify = false): string => {
    const nodes = builder.sequenceNodesBuilder(formula)
    if (!nodes) return formula
    let result = formula
    const offset = formula.startsWith('=') ? 1 : 0
    for (const node of [...nodes].reverse()) {
      if (typeof node === 'string' || node.nodeType !== 3 && node.nodeType !== 4) continue
      let name = node.token, scope = sheetId
      const bang = name.lastIndexOf('!')
      if (bang >= 0) {
        let sheetName = name.slice(0, bang)
        if (sheetName.includes('[')) continue // 外部工作簿保持官方原语义。
        if (sheetName.startsWith("'") && sheetName.endsWith("'")) sheetName = sheetName.slice(1, -1).replace(/''/g, "'")
        const workbook = runtime.univerAPI?.getActiveWorkbook()
        const sheet = workbook?.getId() === unitId ? workbook.getSheets().find((item: any) => item.getSheetName().toLowerCase() === sheetName.toLowerCase()) : undefined
        if (!sheet) continue
        scope = sheet.getSheetId(); name = name.slice(bang + 1)
      }
      if (isReferenceString(name)) {
        if (qualify && bang < 0) {
          const workbook = runtime.univerAPI?.getActiveWorkbook(), sheet = workbook?.getId() === unitId ? workbook.getSheetBySheetId(scope) : undefined
          if (sheet) result = result.slice(0, node.startIndex + offset) + "'" + sheet.getSheetName().replace(/'/g, "''") + "'!" + node.token + result.slice(node.endIndex + offset + 1)
        }
        continue
      }
      if (!/^[\p{L}_\\][\p{L}\p{N}_.\\]*$/u.test(name)) continue
      const entry = resolveScopedDefinedName(names, unitId, scope, name)
      if (!entry) continue
      used.add(entry.name)
      const key = JSON.stringify([unitId, entry.localSheetId ?? GLOBAL, entry.name.toLowerCase()])
      const nested = new Set(visited); nested.add(key)
      const replacement = visited.has(key) || visited.size >= 256 ? '#NAME?' : '(' + expand('=' + entry.formulaOrRefString.replace(/^=/, ''), unitId, scope, nested, used, true).replace(/^=/, '') + ')'
      result = result.slice(0, node.startIndex + offset) + replacement + result.slice(node.endIndex + offset + 1)
    }
    return result
  }
  const scoped = (formula: string, suffix = true) => {
    const used = new Set<string>()
    const result = builder.treeBuilder(expand(formula, config.getExecuteUnitId() ?? '', config.getExecuteSubUnitId() ?? '', new Set(), used), suffix)
    if (typeof result !== 'string' && used.size) result?.setDefinedNames([...used])
    return result
  }
  lexer.treeBuilder = scoped
  const commands = injector.get(ICommandService)
  const action = (workbook: any, action: DefinedNameAction) => {
    if (!workbook.getWorkbook || runtime.univerAPI.getActiveWorkbook()?.getWorkbook() !== workbook.getWorkbook()) return false
    const unitId = workbook.getId(), all = Object.values(names.getDefinedNameMap(unitId) ?? {}) as any[]
    const scope = action.scopeSheetId ?? GLOBAL
    if (action.scopeSheetId && !workbook.getSheetBySheetId(action.scopeSheetId)) throw new Error('名称的工作表作用域不存在')
    const originalName = action.kind === 'update' ? action.originalName : action.name
    const entry = all.find(item => item.name === originalName && (item.localSheetId ?? GLOBAL) === scope)
    if (action.kind !== 'add' && !entry) throw new Error('该名称已不存在，请刷新列表后重试')
    const params = { ...entry, unitId, id: entry?.id ?? generateRandomId(), name: action.name.trim(), localSheetId: scope,
      ...(action.kind === 'remove' ? {} : { formulaOrRefString: action.ref.replace(/^=/, '').trim() }) }
    const id = action.kind === 'add' ? InsertDefinedNameCommand.id : action.kind === 'update' ? SetDefinedNameCommand.id : RemoveDefinedNameCommand.id
    if (!commands.syncExecuteCommand(id, params)) throw new Error('定义名称未应用')
    return true
  }
  // 官方删除命令给 interceptor 只传 range；按对象身份保留真实目标，
  // 避免对 inactive 工作表调用 facade 时误用 activeSheet。
  const deletionTargets = new WeakMap<object, { unitId: string; subUnitId: string }>()
  const beforeCommand = commands.beforeCommandExecuted((command: any) => {
    if (/^sheet\.command\.remove-(?:row|col)-by-range$/.test(command.id) && command.params?.range) {
      deletionTargets.set(command.params.range, { unitId: command.params.unitId, subUnitId: command.params.subUnitId })
    }
  })
  // 官方引用迁移既忽略 local 作用域，也把 inactive 删除当作 active 表；
  // 按真实目标重算所有名称（包括 global），
  // 并复用原命令的 mutation 历史，避免保存差异把正确的文件基线覆盖。
  const structure = injector.get(SheetInterceptorService).interceptCommand({ priority: -100, getMutations(command: any) {
    const result = { redos: [] as any[], undos: [] as any[] }
    const mutations: Record<string, string> = {
      'sheet.command.insert-row': 'sheet.mutation.insert-row', 'sheet.command.remove-row': 'sheet.mutation.remove-rows',
      'sheet.command.insert-col': 'sheet.mutation.insert-col', 'sheet.command.remove-col': 'sheet.mutation.remove-col',
    }
    const params = { ...command.params, ...(command.params?.range && deletionTargets.get(command.params.range)) }, workbook = runtime.univerAPI.getActiveWorkbook()
    if (params.unitId && params.unitId !== workbook?.getId()) return result
    const target = params?.subUnitId ? workbook?.getSheetBySheetId(params.subUnitId) : workbook?.getActiveSheet()
    const op = params?.range && mutations[command.id] && target ? structuralMutation(mutations[command.id]!, { ...params, subUnitId: target.getSheetId() }) : undefined
    if (!op || !target) return result
    const spec = shiftSpecOf(op.op)
    for (const entry of Object.values(names.getDefinedNameMap(workbook.getId()) ?? {}) as any[]) {
      const before = entry.formulaOrRefString
      const after = shiftFormulaText(before, spec, entry.localSheetId === target.getSheetId(), target.getSheetName())
      const make = (formulaOrRefString: string) => ({ id: SetDefinedNameMutation.id, params: { ...entry, unitId: workbook.getId(), formulaOrRefString } })
      result.redos.push(make(after)); result.undos.push(make(before))
    }
    return result
  } })
  // owned local随表删除，并以完整官方名称元数据并入同一次undo/redo。
  // 官方引用collector会把这些名称改成#REF!；按真实id只替换owned条目。
  const sheetService = injector.get(SheetInterceptorService), originalCollect = sheetService.onCommandExecute
  const collect = function (this: typeof sheetService, command: any) {
    const workbook = runtime.univerAPI.getActiveWorkbook(), params = command.params ?? {}
    const target = command.id === 'sheet.command.remove-sheet' && (!params.unitId || params.unitId === workbook?.getId())
      ? params.subUnitId ? workbook?.getSheetBySheetId(params.subUnitId) : workbook?.getActiveSheet() : undefined
    const owned = target ? (Object.values(names.getDefinedNameMap(workbook.getId()) ?? {}) as any[])
      .filter(entry => entry.localSheetId === target.getSheetId()).map(entry => ({ ...entry, unitId: workbook.getId() })) : []
    const result = originalCollect.call(this, command)
    if (!owned.length) return result
    const ids = new Set(owned.map(entry => entry.id))
    const keep = (mutation: any) => !([SetDefinedNameMutation.id, RemoveDefinedNameMutation.id].includes(mutation.id)
      && mutation.params?.unitId === workbook.getId() && ids.has(mutation.params?.id))
    return { ...result,
      preRedos: result.preRedos?.filter(keep), preUndos: result.preUndos?.filter(keep),
      redos: [...result.redos.filter(keep), ...owned.map(params => ({ id: RemoveDefinedNameMutation.id, params }))],
      undos: [...result.undos.filter(keep), ...owned.map(params => ({ id: SetDefinedNameMutation.id, params }))],
    }
  }
  sheetService.onCommandExecute = collect
  scopedActions.add(action)
  return { dispose() { if (sheetService.onCommandExecute === collect) sheetService.onCommandExecute = originalCollect; beforeCommand.dispose(); structure.dispose(); scopedActions.delete(action); if (lexer.treeBuilder === scoped) lexer.treeBuilder = original } }
}
