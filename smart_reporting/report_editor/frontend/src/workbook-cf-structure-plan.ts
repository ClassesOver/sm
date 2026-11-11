import { AddConditionalRuleMutation, DeleteConditionalRuleMutation } from '@univerjs/sheets-conditional-formatting'
import { conditionalFormattingSnapshotRuleSchema } from '@sheets-web/xlsx-engine/conditional-formatting-schema'
import { planConditionalFormattingStructure } from '@sheets-web/xlsx-engine/conditional-formatting-structure'
import type { ShiftSpec } from '@sheets-web/xlsx-engine/structural'
import { renameSheetInFormula } from '@sheets-web/xlsx-engine/sheets-edit'
import { conditionalFormattingWireRule, conditionalFormattingNativeRule, type NativeRule } from './workbook-conditional-formatting'

/** 复用文件侧计划生成原生事务；完整sheet替换保持父规则槽位和原生undo身份。 */
export function planNativeConditionalFormattingStructure(current: NativeRule[], unitId: string, subUnitId: string, hostSheetName: string, editedSheetName: string, spec: ShiftSpec, allocateId: () => string, options?: Parameters<typeof planConditionalFormattingStructure>[4]) {
  const source = current.map(conditionalFormattingWireRule)
  for (const rule of source) conditionalFormattingSnapshotRuleSchema.parse(rule)
  const parents = planConditionalFormattingStructure(source, hostSheetName, editedSheetName, spec, options)
  const next = parents.flatMap(parent => parent.groups)
  if (JSON.stringify(source) === JSON.stringify(next)) return { redos: [], undos: [] }
  for (const rule of next) conditionalFormattingSnapshotRuleSchema.parse(rule)
  if (next.length > 10000 || new TextEncoder().encode(JSON.stringify(next)).length > 8 * 1024 * 1024) throw new Error('条件格式结构迁移超出草稿预算')
  // 校验整批成功之后才分配新身份；第一个分区保留父cfId，其余分区获得独立id。
  const installed = parents.flatMap(parent => parent.groups.map((group, index) => conditionalFormattingNativeRule(group,
    index === 0 ? current[parent.sourceRuleIndex]!.cfId! : allocateId())))
  return conditionalFormattingTransaction(current, installed, unitId, subUnitId)
}

/** 改名仅变换带类型的公式值；复用文件引擎的限定符语义，不改变规则身份/父槽位。 */
export function planNativeConditionalFormattingRename(current: NativeRule[], unitId: string, subUnitId: string, oldName: string, newName: string) {
  const source = current.map(conditionalFormattingWireRule)
  for (const rule of source) conditionalFormattingSnapshotRuleSchema.parse(rule)
  const rename = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(rename)
    if (!value || typeof value !== 'object') return value
    const next: Record<string, unknown> = Object.fromEntries(Object.entries(value).map(([key, item]) => [key, rename(item)]))
    if ((next.type === 'formula' || next.subType === 'formula') && typeof next.value === 'string') next.value = renameSheetInFormula(next.value, oldName, newName)
    return next
  }
  const next = source.map(rule => ({ ...rule, rule: rename(rule.rule) as Record<string, unknown> }))
  if (JSON.stringify(source) === JSON.stringify(next)) return { redos: [], undos: [] }
  for (const rule of next) conditionalFormattingSnapshotRuleSchema.parse(rule)
  if (next.length > 10000 || new TextEncoder().encode(JSON.stringify(next)).length > 8 * 1024 * 1024) throw new Error('条件格式结构迁移超出草稿预算')
  return conditionalFormattingTransaction(current, next.map((rule, index) => conditionalFormattingNativeRule(rule, current[index]!.cfId!)), unitId, subUnitId)
}

function conditionalFormattingTransaction(current: NativeRule[], installed: NativeRule[], unitId: string, subUnitId: string) {
  const remove = (rules: NativeRule[]) => rules.map(rule => ({ id: DeleteConditionalRuleMutation.id, params: { unitId, subUnitId, cfId: rule.cfId } }))
  const add = (rules: NativeRule[]) => [...rules].reverse().map(rule => ({ id: AddConditionalRuleMutation.id, params: { unitId, subUnitId, rule: structuredClone(rule) } }))
  return { redos: [...remove(current), ...add(installed)], undos: [...remove(installed), ...add(current)] }
}
