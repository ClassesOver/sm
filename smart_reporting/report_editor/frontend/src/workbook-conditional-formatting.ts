import { Rectangle } from '@univerjs/core'
import type { IRange } from '@univerjs/core'
import {
  AddCfCommand, AddConditionalRuleMutation, SetCfCommand, SetConditionalRuleMutation,
  DeleteCfCommand, DeleteConditionalRuleMutation, MoveCfCommand, MoveConditionalRuleMutation,
  ClearRangeCfCommand, ClearWorksheetCfCommand, SHEET_CONDITIONAL_FORMATTING_PLUGIN, moveByAnchor,
} from '@univerjs/sheets-conditional-formatting'
import type { IAnchor } from '@univerjs/sheets-conditional-formatting'
import { cfRuleUnsaveableReason } from '@sheets-web/xlsx-engine/conditional-formatting-source'
import { conditionalFormattingSnapshotRuleSchema } from '@sheets-web/xlsx-engine/conditional-formatting-schema'
import type { WorkbookModel, ConditionalFormattingWireRule } from '@sheets-web/xlsx-engine'
import type { WorkbookOperation } from './workbook-draft'

type Source = NonNullable<WorkbookModel['sheets'][number]['conditionalFormatting']>
export type NativeRule = { cfId?: string; ranges: IRange[]; stopIfTrue?: boolean; rule: object }
export interface ConditionalFormattingWorkbook {
  getSheets(): { getSheetName(): string; getConditionalFormattingRules?(): NativeRule[] }[]
}
export function conditionalFormattingNativeRule(rule: ConditionalFormattingWireRule, cfId: string): NativeRule {
  return { ranges: rule.ranges.map(area => ({ ...area })), stopIfTrue: rule.stopIfTrue, rule: formulaShape(rule.rule, true) as object, cfId }
}

export const CF_MUTATION_IDS = new Set([AddConditionalRuleMutation.id, SetConditionalRuleMutation.id, DeleteConditionalRuleMutation.id, MoveConditionalRuleMutation.id])
export const CF_EDIT_COMMAND_IDS = new Set([AddCfCommand.id, SetCfCommand.id, DeleteCfCommand.id, MoveCfCommand.id, ClearRangeCfCommand.id, ClearWorksheetCfCommand.id])

const identity = (value: unknown): string => JSON.stringify(value, (_key, item: unknown) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).filter(([, value]) => value !== undefined).sort(([a], [b]) => a.localeCompare(b))) : item)
function formulaShape(value: unknown, native: boolean): unknown {
  if (Array.isArray(value)) return value.map(item => formulaShape(item, native))
  if (!value || typeof value !== 'object') return value
  const next: Record<string, unknown> = Object.fromEntries(Object.entries(value).map(([key, item]) => [key, formulaShape(item, native)]))
  if (next.subType === 'number' && next.value !== undefined) {
    const values = Array.isArray(next.value) ? next.value : [next.value]
    next.value = native && next.operator !== 'between' && next.operator !== 'notBetween' ? values[0] : values
  }
  if ((next.type === 'formula' || next.subType === 'formula') && typeof next.value === 'string') {
    const body = next.value.replace(/^=/, '')
    next.value = native ? `=${body}` : body
  }
  return next
}
export function conditionalFormattingWireRule(rule: NativeRule): ConditionalFormattingWireRule {
  return { ranges: rule.ranges.map(({ startRow, endRow, startColumn, endColumn }) => ({ startRow, endRow, startColumn, endColumn })), stopIfTrue: rule.stopIfTrue === true, rule: formulaShape(rule.rule, false) as Record<string, unknown> }
}
function validate(rules: ConditionalFormattingWireRule[], source?: Source): void {
  if (source?.issues.length) throw new Error(`条件格式来源不完整：${source.issues.join('; ')}`)
  if (rules.length > 10000) throw new Error('条件格式规则数量超限')
  for (const item of rules) {
    const reason = cfRuleUnsaveableReason(item.rule)
    if (reason !== null) throw new Error(reason)
    conditionalFormattingSnapshotRuleSchema.parse(item)
  }
  for (const linked of source?.linkedRules ?? []) {
    if (rules.filter(item => identity(item) === identity(conditionalFormattingWireRule(linked as NativeRule))).length !== 1) throw new Error('关联 linked 条件格式必须保持原始完整身份')
  }
}

/** 官方resource一次导入，不执行编辑命令，不向原生undo历史添加项。 */
export function withWorkbookConditionalFormatting<T extends { sheets: Record<string, { id: string; name: string }> }>(data: T, model: WorkbookModel): T & { resources: { name: string; data: string }[] } {
  const resource: Record<string, unknown[]> = {}
  for (const sheet of Object.values(data.sheets)) {
    const source = model.sheets.find(item => item.name === sheet.name)?.conditionalFormatting
    if (!source || source.issues.length || !source.rules.length) continue
    for (const rule of source.rules) conditionalFormattingSnapshotRuleSchema.parse(rule)
    // CF可能覆盖源dimension之外的空白区域，官方引用迁移需要完整sheet边界。
    const geometry = sheet as typeof sheet & { rowCount?: number; columnCount?: number }
    for (const rule of source.rules) for (const range of rule.ranges) {
      geometry.rowCount = Math.max(geometry.rowCount ?? 0, range.endRow + 1)
      geometry.columnCount = Math.max(geometry.columnCount ?? 0, range.endColumn + 1)
    }
    resource[sheet.id] = source.rules.map((item, index) => ({ ...item, rule: formulaShape(item.rule, true), cfId: `file-cf-${sheet.id}-${index}` }))
  }
  const existing = (data as T & { resources?: { name: string; data: string }[] }).resources ?? []
  return Object.assign(data, { resources: [...existing.filter(item => item.name !== SHEET_CONDITIONAL_FORMATTING_PLUGIN),
    ...(Object.keys(resource).length ? [{ name: SHEET_CONDITIONAL_FORMATTING_PLUGIN, data: JSON.stringify(resource) }] : [])] })
}

/** model由调用方每次提供，必须是结构操作重放后的baseline。 */
export function workbookConditionalFormattingOperations(model: WorkbookModel, workbook: ConditionalFormattingWorkbook | null): WorkbookOperation[] {
  const operations: WorkbookOperation[] = []
  for (const sheet of workbook?.getSheets() ?? []) {
    const source = model.sheets.find(item => item.name === sheet.getSheetName())?.conditionalFormatting
    // 未知规则保持原XML；该sheet的CF编辑应由前置guard拒绝。
    if (source?.issues.length || !sheet.getConditionalFormattingRules) continue
    const rules = sheet.getConditionalFormattingRules().map(conditionalFormattingWireRule)
    if (identity(rules) === identity((source?.rules ?? []).map(item => conditionalFormattingWireRule(item as NativeRule)))) continue
    validate(rules, source)
    operations.push({ kind: 'replaceSheetConditionalFormats', sheetName: sheet.getSheetName(), rules })
  }
  return operations
}

/** 在官方命令/原生mutation修改前验证候选快照；undo/redo复用相同可落盘性规则。 */
export function validateConditionalFormattingEdit(id: string, params: Record<string, any>, current: NativeRule[], source?: Source): void {
  if (!CF_EDIT_COMMAND_IDS.has(id) && !CF_MUTATION_IDS.has(id)) return
  let proposed = current.map(item => ({ ...item, ranges: [...item.ranges] }))
  if (id === AddCfCommand.id || id === AddConditionalRuleMutation.id) proposed.unshift(params.rule)
  else if (id === SetCfCommand.id || id === SetConditionalRuleMutation.id) {
    const index = proposed.findIndex(item => item.cfId === (params.cfId || params.rule?.cfId))
    if (index >= 0) proposed[index] = params.rule
  } else if (id === DeleteCfCommand.id || id === DeleteConditionalRuleMutation.id) proposed = proposed.filter(item => item.cfId !== params.cfId)
  else if (id === ClearWorksheetCfCommand.id) proposed = []
  else if (id === ClearRangeCfCommand.id) {
    if (!params.ranges) {
      if (source?.issues.length || source?.linkedRules.length) throw new Error('条件格式来源不完整或含关联规则，无法清除选区')
      return
    }
    proposed = proposed.map(item => ({ ...item, ranges: Rectangle.subtractMulti(item.ranges, params.ranges) })).filter(item => item.ranges.length)
  } else if (params.start && params.end) moveByAnchor(params.start as IAnchor, params.end as IAnchor, proposed, item => item.cfId!)
  validate(proposed.map(conditionalFormattingWireRule), source)
}
