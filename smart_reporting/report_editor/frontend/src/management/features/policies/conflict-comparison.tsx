import { Checkbox, Radio } from 'antd'
import type { PolicyDefinition } from './editor-contracts'
import { policyDisplayFields } from './definition-display'

type Field = Exclude<keyof PolicyDefinition, 'id'>
export type PolicyConflictChoices = Partial<Record<Field, 'local' | 'server'>>
export const policyConflictFields = (local: PolicyDefinition, server: PolicyDefinition) => policyDisplayFields.filter(p => JSON.stringify(local[p.key]) !== JSON.stringify(server[p.key]))
export function PolicyConflictComparison({ local, server, version, choices, onChoice, acknowledged, onAcknowledge, disabled }: {
 local: PolicyDefinition; server: PolicyDefinition; version: number; choices: PolicyConflictChoices
 onChoice: (field: Field, choice: 'local' | 'server') => void; acknowledged: boolean; onAcknowledge: (value: boolean) => void; disabled: boolean
}) {
 const changes = policyConflictFields(local, server)
 return <section aria-label="口径冲突逐项对照" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
  <strong>本地修改与服务器草稿版本 {version} 对照</strong>
  <p>每个不同项均需明确选择。筛选、关联及充分性规则分别整组采用，避免自动拼接改变业务含义。采用只准备本地编辑；保存和发布仍需另行操作。</p>
  {changes.map(p => <fieldset key={p.key} disabled={disabled} style={{ minWidth: 0, margin: 0, border: '1px solid #d9dfe8', padding: 12 }}>
   <legend>{p.label}</legend>
   <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,240px),1fr))', gap: 12 }}>
    <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}><strong>本地修改</strong><div>{p.display(local)}</div></div>
    <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}><strong>服务器草稿</strong><div>{p.display(server)}</div></div>
   </div>
   <Radio.Group value={choices[p.key]} onChange={e => onChoice(p.key, e.target.value)} aria-label={p.label + '选择'}>
    <Radio value="local" aria-label={p.label + '：保留本地'}>保留本地</Radio><Radio value="server" aria-label={p.label + '：采用服务器'}>采用服务器</Radio>
   </Radio.Group>
  </fieldset>)}
  {!changes.length && <p>定义内容一致，草稿版本已变化；仍需明确采用服务器版本作为保存基准。</p>}
  <Checkbox aria-label="确认口径冲突选择" checked={acknowledged} disabled={disabled} onChange={e => onAcknowledge(e.target.checked)}>已逐项核对选择；保留原提交记录，以当前服务器草稿为基准继续编辑。</Checkbox>
 </section>
}
