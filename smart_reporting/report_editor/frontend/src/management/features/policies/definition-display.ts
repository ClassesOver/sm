import type { PolicyDefinition } from './editor-contracts'
type Field = Exclude<keyof PolicyDefinition, 'id'>
const empty = (text: string) => text || '无'
export const policyDisplayFields: { key: Field; label: string; display: (d: PolicyDefinition) => string }[] = [
 { key: 'name', label: '口径名称', display: d => d.name },
 { key: 'scenario', label: '报告场景', display: d => d.scenario },
 { key: 'validFrom', label: '生效开始', display: d => d.validFrom },
 { key: 'validTo', label: '生效结束', display: d => d.validTo ?? '无结束日期' },
 { key: 'metricVersions', label: '精确指标版本', display: d => empty(d.metricVersions.map(r => r.metricId + ' / ' + r.revision).join('；')) },
 { key: 'evidenceReleaseId', label: '制度依据集合', display: d => d.evidenceReleaseId },
 { key: 'decisionNotes', label: '口径决策说明', display: d => empty(d.decisionNotes) },
 { key: 'filters', label: '筛选条件', display: d => empty(d.filters.map(f => f.fieldRef + ' ' + ({ eq: '等于', ne: '不等于', lt: '小于', le: '小于等于', gt: '大于', ge: '大于等于', in: '属于', is_null: '为空' }[f.operator]) + ' ' + f.values.map(v => v === null ? '空值' : typeof v === 'string' ? '文本「' + v + '」' : typeof v === 'boolean' ? '布尔 ' + v : '数值 ' + v).join('、')).join('；')) },
 { key: 'joins', label: '表关联', display: d => empty(d.joins.map(j => j.leftKeys.join('、') + ' → ' + j.rightKeys.join('、') + '；多对一；输出粒度 ' + j.outputGrain.join('、')).join('\n')) },
 { key: 'readinessPolicy', label: '数据充分性规则', display: d => [
  '预期期间：' + (d.readinessPolicy.expectedPeriods.map(p => p.start + ' 至 ' + p.end + '（结束不包含）').join('；') || '未指定'),
  '预期分组：' + (d.readinessPolicy.expectedGroups.map(g => g.map(v => v.dimensionId + '=' + JSON.stringify(v.value)).join('、')).join('；') || '未指定'),
  '水位字段：' + (d.readinessPolicy.watermarkField ?? '未指定'), '最大延迟（秒）：' + (d.readinessPolicy.maximumDelaySeconds ?? '未指定'),
  '空观测：' + (d.readinessPolicy.emptyObservation === 'unknown' ? '未知' : '完整时记零'),
 ].join('\n') },
]
