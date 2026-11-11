import { ICommandService } from '@univerjs/core'
import { DataValidationFormulaService, DataValidationListCacheService } from '@univerjs/sheets-data-validation'
import { DataValidatorRegistryService } from '@univerjs/data-validation'
import { IDefinedNamesService, isReferenceString } from '@univerjs/engine-formula'
import { resolveScopedDefinedName } from './workbook-defined-name-scope'
import { resolveTableListSource } from './workbook-tables'

// 只扩展官方列表校验的名称解析；规则本身与计算仍由 Univer 管理。
export function installDataValidationNames(runtime: any) {
  const injector = runtime.univer.__getInjector()
  const validator = injector.get(DataValidatorRegistryService).getValidatorItem('list')
  const names = injector.get(IDefinedNamesService)
  const original = validator.validatorFormula
  const resolve = (formula: string, unitId: string, subUnitId: string) => {
    const visited = new Set<string>()
    while (typeof formula === 'string' && /^=[\p{L}_\\][\p{L}\p{N}_.\\]*$/u.test(formula)) {
      if (isReferenceString(formula.slice(1))) break
      const name = formula.slice(1).toLowerCase(), key = JSON.stringify([subUnitId, name])
      if (visited.has(key)) return '=#NAME?'
      visited.add(key)
      const entry = resolveScopedDefinedName(names, unitId, subUnitId, name)
      if (!entry) return '=#NAME?'
      formula = '=' + entry.formulaOrRefString.replace(/^=/, '')
    }
    return resolveTableListSource(formula, runtime.univerAPI.getActiveWorkbook())
  }
  const validate = function (this: any, rule: any, unitId: string, subUnitId: string) {
    return original.call(this, { ...rule, formula1: resolve(rule.formula1, unitId, subUnitId) }, unitId, subUnitId)
  }
  const formulas = injector.get(DataValidationFormulaService)
  const originalAdd = formulas.addRule
  // 官方词法缓存不跟踪间接名称变更；只展开计算副本，文件规则保留名称。
  const add = function (this: any, unitId: string, subUnitId: string, rule: any) {
    const result = originalAdd.call(this, unitId, subUnitId, rule.type === 'list' ? { ...rule, formula1: resolve(rule.formula1, unitId, subUnitId) } : rule)
    // 引用迁移服务读取此公开信息；计算注册已取得展开文本，这里必须恢复规则原文。
    const info = this.getRuleFormulaInfo(unitId, subUnitId, rule.uid)
    if (rule.type === 'list' && info?.[0]) info[0].text = rule.formula1
    return result
  }
  formulas.addRule = add
  const refresh = (unitId: string) => {
    const workbook = runtime.univerAPI.getActiveWorkbook()
    if (!workbook || workbook.getId() !== unitId) return
    const cache = injector.get(DataValidationListCacheService)
    for (const sheet of workbook.getSheets()) for (const { rule } of sheet.getDataValidations()) {
      if (rule.type !== 'list' || !rule.formula1?.startsWith('=')) continue
      cache.markRuleDirty(workbook.getId(), sheet.getSheetId(), rule.uid)
      formulas.removeRule(workbook.getId(), sheet.getSheetId(), rule.uid)
      formulas.addRule(workbook.getId(), sheet.getSheetId(), rule)
    }
  }
  const listener = injector.get(ICommandService).onCommandExecuted((command: any) => {
    if (/^formula\.mutation\.(?:set|remove)-(?:defined-name|super-table)$/.test(command.id) ||
        command.id === 'sheet.mutation.set-worksheet-name') refresh(command.params.unitId)
  })
  refresh(runtime.univerAPI.getActiveWorkbook()?.getId())
  validator.validatorFormula = validate
  return { dispose() {
    listener.dispose()
    if (formulas.addRule === add) formulas.addRule = originalAdd
    if (validator.validatorFormula === validate) validator.validatorFormula = original
  } }
}
