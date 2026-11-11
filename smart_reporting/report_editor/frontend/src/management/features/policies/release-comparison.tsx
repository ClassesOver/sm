import { Tag } from 'antd'
import type { PolicyDefinition } from './editor-contracts'
import { policyDisplayFields } from './definition-display'

const sections = [
 { title: '计算与适用范围', fields: ['scenario', 'validFrom', 'validTo', 'metricVersions', 'filters', 'joins', 'readinessPolicy'] },
 { title: '制度依据', fields: ['evidenceReleaseId'] },
 { title: '说明与命名', fields: ['name', 'decisionNotes'] },
]
export function PolicyReleaseComparison({ current, target }: {
 current: { revision: number; document: PolicyDefinition } | null
 target: PolicyDefinition & { revision: number }
}) {
 const changed = policyDisplayFields.filter(p => !current || JSON.stringify(current.document[p.key]) !== JSON.stringify(target[p.key]))
 return <section aria-label="口径发布逐项差异" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
  <strong>当前发布与已保存目标逐项核对</strong>
  <div>当前发布：{current ? '版本 ' + current.revision : '首次发布'}；目标发布：版本 {target.revision} <Tag>{changed.length} 项定义变化</Tag></div>
  {sections.map(group => {
   const fields = changed.filter(p => group.fields.includes(p.key))
   return <section key={group.title} aria-label={group.title + '发布差异'} style={{ display: 'grid', gap: 8 }}>
    <h3 style={{ margin: 0, fontSize: 14 }}>{group.title}</h3>
    {fields.length ? fields.map(p => <article key={p.key} style={{ padding: 12, border: '1px solid #d9dfe8' }}>
     <strong>{p.label}</strong>
     <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,240px),1fr))', gap: 12, marginTop: 8 }}>
      <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}><strong>当前发布</strong><div>{current ? p.display(current.document) : '尚未发布'}</div></div>
      <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}><strong>待发布草稿</strong><div>{p.display(target)}</div></div>
     </div>
    </article>) : <p style={{ margin: 0 }}>与当前发布一致。</p>}
   </section>
  })}
  <p>默认绑定本次不调整；新报告采用哪个口径仍由场景默认或明确选择决定，历史报告继续使用原依据。此对比只包含已保存的目标内容。</p>
 </section>
}
