import type { PolicyDefinition } from './editor-contracts'
const identity = (value: string) => /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value)
const field = (value: string) => /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.[A-Za-z_][A-Za-z0-9_$]{0,127}\.[A-Za-z_][A-Za-z0-9_$]{0,127}\.[A-Za-z_][A-Za-z0-9_$]{0,127}$/.test(value)
export function validPolicyDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(value + 'T00:00:00Z')
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}
export function validatePolicyRules(value: Pick<PolicyDefinition, 'filters' | 'joins' | 'readinessPolicy'>) {
  if (value.filters.length > 100 || value.filters.some(item => !field(item.fieldRef) || item.values.length > 200
    || (item.operator === 'is_null' ? item.values.length !== 0 : item.operator === 'in' ? item.values.length === 0 : item.values.length !== 1)))
    return '筛选条件须使用完整字段引用；单值比较填一个值，属于比较至少一个值，为空不填值。'
  if (value.joins.length > 20 || value.joins.some(item => !item.leftKeys.length || item.leftKeys.length > 10 || item.leftKeys.length !== item.rightKeys.length
    || [...item.leftKeys, ...item.rightKeys].some(key => !field(key)) || !item.outputGrain.length || item.outputGrain.length > 20 || item.outputGrain.some(key => !identity(key))))
    return '关联须包含成对的完整字段引用及有效输出粒度。'
  const readiness = value.readinessPolicy
  const periods = [...readiness.expectedPeriods].sort((a, b) => a.start.localeCompare(b.start))
  if (periods.some((p, index) => !validPolicyDate(p.start) || !validPolicyDate(p.end) || p.start >= p.end
    || (index > 0 && periods[index - 1].end > p.start))) return '预期期间须为有效、互不重叠的非空日期区间。'
  if ((readiness.watermarkField !== null && !field(readiness.watermarkField))
    || (readiness.maximumDelaySeconds !== null && (!readiness.watermarkField || !Number.isSafeInteger(readiness.maximumDelaySeconds) || readiness.maximumDelaySeconds < 0)))
    return '水位字段须为完整引用；设置最大延迟必须同时声明水位字段。'
  const groups = readiness.expectedGroups
  if (groups.some(group => !group.length || group.some(item => !identity(item.dimensionId)) || new Set(group.map(item => item.dimensionId)).size !== group.length))
    return '每个预期分组须有不重复的有效维度标识。'
  const signatures = groups.map(group => JSON.stringify([...group].sort((a, b) => a.dimensionId.localeCompare(b.dimensionId))))
  if (new Set(signatures).size !== signatures.length) return '预期分组不能重复。'
  return ''
}
