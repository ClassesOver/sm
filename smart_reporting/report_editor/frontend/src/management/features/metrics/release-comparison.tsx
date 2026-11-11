import { Alert, Tag } from 'antd'
import type { Definition } from './editor'

const kinds = { sum: '求和', count: '非空计数', count_distinct: '去重计数', ratio: '比率' }
const reference = (value: Definition['numeratorVersion']) => value ? `${value.metricId} · 版本 ${value.revision}` : '无'
const formula = (value: Definition) => value.kind === 'ratio'
  ? `${reference(value.numeratorVersion)} ÷ ${reference(value.denominatorVersion)}${value.unit === '%' ? '，显示为百分比' : ''}`
  : `${kinds[value.kind]}（${value.fieldRef}）`
const properties: { key: keyof Definition; label: string; display: (value: Definition) => string }[] = [
  { key: 'name', label: '指标名称', display: d => d.name },
  { key: 'kind', label: '计算方法', display: d => kinds[d.kind] },
  { key: 'fieldRef', label: '取数字段', display: d => d.fieldRef ?? '无' },
  { key: 'timeField', label: '时间字段', display: d => d.timeField ?? '无' },
  { key: 'unit', label: '显示单位', display: d => d.unit },
  { key: 'numeratorVersion', label: '分子指标版本', display: d => reference(d.numeratorVersion) },
  { key: 'denominatorVersion', label: '分母指标版本', display: d => reference(d.denominatorVersion) },
  { key: 'dimensions', label: '维度字段', display: d => d.dimensions.map(v => `${v.id}：${v.fieldRef}`).join('；') || '无' },
  { key: 'grain', label: '计算粒度', display: d => d.grain.join('、') || '无' },
  { key: 'aggregationPolicy', label: '时间聚合规则', display: d => [
    d.aggregationPolicy.observationKind === 'flow' ? '事件流' : '累计快照',
    { sum: '期间求和', difference: '期末减期初', none: '不聚合' }[d.aggregationPolicy.timeAggregation],
    d.aggregationPolicy.reset === 'calendar_year_zero' ? '每年归零' : d.aggregationPolicy.reset === 'none' ? '不重置' : '未声明重置',
  ].join('；') },
  { key: 'timeZone', label: '业务时区', display: d => d.timeZone ?? '未声明' },
  { key: 'storageTimeZone', label: '存储时区', display: d => d.storageTimeZone ?? '未声明' },
  { key: 'aliases', label: '别名', display: d => d.aliases.join('、') || '无' },
]

export function MetricReleaseComparison({ current, target, dirty }: {
  current: { revision: number; document: Definition } | null
  target: Definition & { revision: number }
  dirty: boolean
}) {
  const changes = properties.filter(p => !current || JSON.stringify(current.document[p.key]) !== JSON.stringify(target[p.key]))
  return <section aria-label="指标发布变更" style={{ display: 'grid', gap: 8 }}>
    <strong>发布前核对</strong>
    <div>当前发布：{current ? `版本 ${current.revision}` : '尚未发布'}；目标发布：版本 {target.revision} <Tag>{changes.length} 项变化</Tag></div>
    {dirty && <Alert type="warning" title="以下对比仅包含已保存草稿；请先保存本地修改，再核对发布。" />}
    <div>目标计算说明（{kinds[target.kind]}）：{formula(target)}</div>
    {changes.length ? <div role="region" aria-label="指标发布字段对比，可滚动" tabIndex={0} style={{ overflowX: 'auto', maxHeight: 420 }}>
      <table style={{ width: '100%', minWidth: 520, borderCollapse: 'collapse', textAlign: 'left', tableLayout: 'fixed' }}>
        <caption style={{ textAlign: 'left' }}>已发布定义与已保存草稿的变化</caption>
        <thead><tr>{['字段', '当前发布', '待发布草稿'].map(label => <th key={label} scope="col" style={{ padding: 8, borderBottom: '1px solid #d9dfe8' }}>{label}</th>)}</tr></thead>
        <tbody>{changes.map(p => <tr key={p.key}>
          <th scope="row" style={{ padding: 8, borderBottom: '1px solid #edf0f4', verticalAlign: 'top' }}>{p.label}</th>
          <td style={{ padding: 8, borderBottom: '1px solid #edf0f4', verticalAlign: 'top' }}>{current ? p.display(current.document) : '尚未发布'}</td>
          <td style={{ padding: 8, borderBottom: '1px solid #edf0f4', verticalAlign: 'top' }}>{p.display(target)}</td>
        </tr>)}</tbody>
      </table>
    </div> : <div>定义内容与当前发布一致。</div>}
    <div>本次只发布指标定义。口径引用、场景默认和历史报告保持原版本，采用新指标须另行明确发布口径。</div>
  </section>
}
