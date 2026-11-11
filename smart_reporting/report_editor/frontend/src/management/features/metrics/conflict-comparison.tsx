import { Checkbox, Radio } from 'antd'
import type { Definition } from './editor'

type Group = 'name' | 'calculation' | 'dimensions' | 'timeZones' | 'aliases'
export type MetricConflictChoices = Partial<Record<Group, 'local' | 'server'>>
const kinds = { sum: '求和', count: '非空计数', count_distinct: '去重计数', ratio: '比率' }
const ref = (r: Definition['numeratorVersion']) => r ? r.metricId + ' / ' + r.revision : '无'
const groups: { key: Group; label: string; fields: (keyof Definition)[]; display: (d: Definition) => string }[] = [
 { key: 'name', label: '指标名称', fields: ['name'], display: d => d.name },
 { key: 'calculation', label: '计算定义', fields: ['kind', 'fieldRef', 'timeField', 'unit', 'numeratorVersion', 'denominatorVersion', 'aggregationPolicy'], display: d => [
  '方法：' + kinds[d.kind], '取数字段：' + (d.fieldRef ?? '无'), '时间字段：' + (d.timeField ?? '无'), '单位：' + d.unit,
  '分子：' + ref(d.numeratorVersion), '分母：' + ref(d.denominatorVersion),
  '观测：' + (d.aggregationPolicy.observationKind === 'flow' ? '事件流' : '累计快照'),
  '时间聚合：' + ({ sum: '期间求和', difference: '期末减期初', none: '不聚合' }[d.aggregationPolicy.timeAggregation]),
  '重置：' + (d.aggregationPolicy.reset === 'calendar_year_zero' ? '每年归零' : d.aggregationPolicy.reset === 'none' ? '不重置' : '未声明'),
 ].join('\n') },
 { key: 'dimensions', label: '维度与计算粒度', fields: ['dimensions', 'grain'], display: d => '维度：' + (d.dimensions.map(v => v.id + '：' + v.fieldRef).join('；') || '无') + '\n粒度：' + (d.grain.join('、') || '无') },
 { key: 'timeZones', label: '业务与存储时区', fields: ['timeZone', 'storageTimeZone'], display: d => '业务时区：' + (d.timeZone ?? '未声明') + '\n存储时区：' + (d.storageTimeZone ?? '未声明') },
 { key: 'aliases', label: '别名', fields: ['aliases'], display: d => d.aliases.join('、') || '无' },
]
export const metricConflictGroups = (local: Definition, server: Definition) => groups.filter(g => g.fields.some(f => JSON.stringify(local[f]) !== JSON.stringify(server[f])))
export function MetricConflictComparison({ local, server, version, choices, onChoice, acknowledged, onAcknowledge, disabled }: {
 local: Definition; server: Definition; version: number; choices: MetricConflictChoices; onChoice: (group: Group, choice: 'local' | 'server') => void
 acknowledged: boolean; onAcknowledge: (value: boolean) => void; disabled: boolean
}) {
 const changes = metricConflictGroups(local, server)
 return <section aria-label="指标冲突逐项对照" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
  <strong>本地修改与服务器指标草稿版本 {version} 对照</strong>
  <p>计算方法、单位、字段及公式依赖整组采用；维度与粒度、两个时区也分别成组，避免拼接出未经核对的计算定义。采用只准备本地编辑，保存与发布须另行确认。</p>
  {changes.map(g => <fieldset key={g.key} disabled={disabled} style={{ minWidth: 0, margin: 0, padding: 12, border: '1px solid #d9dfe8' }}>
   <legend>{g.label}</legend>
   <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,240px),1fr))', gap: 12 }}>
    <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}><strong>本地修改</strong><div>{g.display(local)}</div></div>
    <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}><strong>服务器草稿</strong><div>{g.display(server)}</div></div>
   </div>
   <Radio.Group aria-label={g.label + '选择'} value={choices[g.key]} onChange={e => onChoice(g.key, e.target.value)}>
    <Radio value="local" aria-label={g.label + '：保留本地'}>保留本地</Radio><Radio value="server" aria-label={g.label + '：采用服务器'}>采用服务器</Radio>
   </Radio.Group>
  </fieldset>)}
  {!changes.length && <p>定义内容一致，草稿版本已变化；仍需明确采用服务器版本作为保存基准。</p>}
  <Checkbox aria-label="确认指标冲突选择" checked={acknowledged} disabled={disabled} onChange={e => onAcknowledge(e.target.checked)}>已核对各组选择；保留原提交记录，以当前服务器草稿为基准继续编辑。</Checkbox>
 </section>
}
