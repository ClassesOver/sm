import type { WorkbookModel } from '@sheets-web/xlsx-engine'
import { applyDvRules, type DvWireRule, type DvCellArea } from '@sheets-web/xlsx-engine/data-validation'
import type { WorkbookOperation } from './workbook-draft'

export interface ValidationWorkbook {
  getSheets(): { getSheetName(): string; getDataValidations?(): { rule: Record<string, unknown> & { ranges: DvCellArea[] } }[] }[]
}

export const DV_MUTATION = /^data-validation\.mutation\.(?:addRule|updateRule|removeRule)$/
export const DV_EDIT_COMMAND = /^sheets?\.command\.(?:addDataValidation|updateDataValidationRuleRange|update-data-validation-(?:setting|options)|clear-range-data-validation|remove-data-validation-rule|remove-all-data-validation)$/

export function withWorkbookDataValidations<T extends { sheets: Record<string, { id: string; name: string }> }>(data: T, model: WorkbookModel): T & { resources: { name: string; data: string }[] } {
  const resource: Record<string, unknown[]> = {}
  for (const sheet of Object.values(data.sheets)) {
    const source = model.sheets.find(item => item.name === sheet.name)?.dataValidations
    if (!source || source.readOnlyReason || !source.rules.length) continue
    resource[sheet.id] = source.rules.map((item, index) => ({
      ...item.rule, ranges: item.ranges, uid: `file-dv-${sheet.id}-${index}`,
      ...(item.rule.type === 'list' ? { renderMode: 0 } : {}),
    }))
  }
  const existing = (data as T & { resources?: { name: string; data: string }[] }).resources ?? []
  return Object.assign(data, { resources: [...existing.filter(item => item.name !== 'SHEET_DATA_VALIDATION_PLUGIN'),
    ...(Object.keys(resource).length ? [{ name: 'SHEET_DATA_VALIDATION_PLUGIN', data: JSON.stringify(resource) }] : [])] })
}

const serialize = (rules: readonly DvWireRule[]) => applyDvRules('<worksheet><sheetData/></worksheet>', rules)

/** 在官方命令修改模型前验证可落盘性；不支持的选项不能留到保存时才报错。 */
export function validateDataValidationEdit(id: string, params: Record<string, any>, current: Record<string, any>[], staged: WorkbookOperation[], structuralCount: number): void {
  let proposed = current.map(item => ({ ...item }))
  if (id.endsWith('addDataValidation') || id.endsWith('addRule')) {
    proposed.push(...(Array.isArray(params.rule) ? params.rule : [params.rule]))
  } else {
    const target = proposed.find(item => item.uid === params.ruleId)
    if (!target) return
    if (id.endsWith('update-data-validation-setting')) Object.assign(target, params.setting)
    else if (id.endsWith('update-data-validation-options')) Object.assign(target, params.options)
    else if (id.endsWith('updateDataValidationRuleRange')) target.ranges = params.ranges
    else if (id.endsWith('updateRule')) {
      const update = params.payload
      if (update?.type === 1) target.ranges = update.payload
      else Object.assign(target, update?.payload)
    } else return
  }
  if (proposed.length > 10000 || proposed.some(item => !Array.isArray(item?.ranges) || !item.ranges.length || item.ranges.length > 10000)) throw new Error('数据验证规则或范围数量超限')
  const rules = proposed.map(({ ranges, uid: _uid, ...rule }) => ({ ranges, rule })) as DvWireRule[]
  serialize(rules)
  if (staged.length + structuralCount + 1 > 450 || new TextEncoder().encode(JSON.stringify([...staged, { rules }])).length > 8 * 1024 * 1024) throw new Error('数据验证超出本地草稿预算，请先保存当前修改')
}

export function workbookDataValidationOperations(model: WorkbookModel, workbook: ValidationWorkbook | null): WorkbookOperation[] {
  const operations: WorkbookOperation[] = []
  for (const sheet of workbook?.getSheets() ?? []) {
    const source = model.sheets.find(item => item.name === sheet.getSheetName())?.dataValidations
    if (source?.readOnlyReason || !sheet.getDataValidations) continue
    const rules = sheet.getDataValidations().map(item => {
      const { ranges, uid: _uid, ...rule } = item.rule
      return { ranges: ranges.map(({ startRow, endRow, startColumn, endColumn }) => ({ startRow, endRow, startColumn, endColumn })),
        rule: Object.fromEntries(Object.entries(rule).filter(([, value]) => value !== undefined)) }
    })
    if (serialize(rules) !== serialize(source?.rules ?? [])) {
      operations.push({ kind: 'replaceSheetDataValidations', sheetName: sheet.getSheetName(), rules })
    }
  }
  return operations
}
