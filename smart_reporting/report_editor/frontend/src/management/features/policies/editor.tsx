import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Input, Space, Tag } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { identity, request, scopeQuery } from '../../api/http'
import { MetricDependencyPicker } from '../metrics/dependency-picker'
import { AsyncState } from '../../components/common'
import { PolicyRuleFields } from './rule-fields'
import { PolicyReleaseComparison } from './release-comparison'
import { PolicyConflictComparison, policyConflictFields, type PolicyConflictChoices } from './conflict-comparison'
import { PolicyEvidencePicker } from './evidence-picker'
import { validatePolicyRules, validPolicyDate } from './rule-validation'
import { policyDefinitionSchema, policyDraftSchema, policyReadSchema, policyPublishedSchema, policyPreviewSchema,
  policyIssuesSchema, samePolicy, type PolicyDefinition } from './editor-contracts'

const pendingSchema = z.object({ action: z.enum(['save', 'publish']), expectedVersion: z.number().int().nonnegative(),
  definition: policyDefinitionSchema, revision: z.number().int().positive().nullable(), contentHash: z.string().nullable(), previewIssues: policyIssuesSchema })
const cacheSchema = z.object({ value: policyDefinitionSchema, baseline: policyDraftSchema.nullable(), pending: pendingSchema.nullable() })
const evidenceSchema = z.object({ releaseId: z.string(), kind: z.enum(['rule_evidence', 'background']),
  documents: z.array(z.object({ reference: z.object({ documentId: z.string(), revision: z.number().int().positive() }), metadata: z.object({ title: z.string() }) })) })
type Draft = z.infer<typeof policyDraftSchema>
type Pending = z.infer<typeof pendingSchema>
const validId = (id: string) => /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(id)
const fields: Record<string, string> = { filters: '筛选条件', joins: '表关联', readinessPolicy: '数据充分性规则', validFrom: '生效开始', validTo: '生效结束', scenario: '报告场景', metrics: '指标计算定义' }
function problem(value: PolicyDefinition) {
  if (!validId(value.id) || !value.name.trim() || value.name.length > 200 || !validId(value.scenario) || !validId(value.evidenceReleaseId)) return '请填写有效的口径名称、场景标识及制度依据集合。'
  if (!validPolicyDate(value.validFrom) || (value.validTo && (!validPolicyDate(value.validTo) || value.validFrom >= value.validTo))) return '生效期采用开始包含、结束不包含的有效日期区间。'
  if (!value.metricVersions.length || value.metricVersions.length > 200 || value.metricVersions.some(ref => !validId(ref.metricId) || ref.revision < 1)
    || new Set(value.metricVersions.map(ref => JSON.stringify(ref))).size !== value.metricVersions.length) return '请明确选择不重复的指标精确发布版本。'
  return validatePolicyRules(value)
}

export function PolicyEditor({ scope, policyId, username, csrf }: {
  scope: { database: string; companyId: string }; policyId: string; username: string; csrf: string
}) {
  const client = useQueryClient(), path = '/statistical-policies/' + encodeURIComponent(policyId)
  const key = 'management-policy-editor:' + JSON.stringify([username, scope.database, scope.companyId, policyId])
  const [cache] = useState(() => { try {
    const raw = sessionStorage.getItem(key), saved = raw ? cacheSchema.parse(JSON.parse(raw)) : null
    if (saved && (saved.value.id !== policyId || (saved.baseline && saved.baseline.document.id !== policyId)
      || (saved.pending && saved.pending.definition.id !== policyId))) throw Error('identity')
    return { value: saved, invalid: false }
  } catch { return { value: null, invalid: true } } })
  const [value, setValue] = useState<PolicyDefinition>(cache.value?.value ?? { id: policyId, name: '', scenario: '', validFrom: '', validTo: null,
    metricVersions: [], evidenceReleaseId: '', decisionNotes: '', filters: [], joins: [],
    readinessPolicy: { expectedPeriods: [], expectedGroups: [], watermarkField: null, maximumDelaySeconds: null, emptyObservation: 'unknown' } })
  const [baseline, setBaseline] = useState<Draft | null>(cache.value?.baseline ?? null)
  const [published, setPublished] = useState<z.infer<typeof policyPublishedSchema> | null>(null)
  const [pending, setPending] = useState<Pending | null>(cache.value?.pending ?? null)
  const [preview, setPreview] = useState<z.infer<typeof policyPreviewSchema> | null>(null)
  const [previewHash, setPreviewHash] = useState('')
  const [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [ack, setAck] = useState(false)
  const [retryReady, setRetryReady] = useState(false), [notice, setNotice] = useState(cache.invalid ? '口径缓存无法读取，请保留原缓存，禁止覆盖。' : '')
  const [conflict, setConflict] = useState<Draft | null>(null), [choices, setChoices] = useState<PolicyConflictChoices>({}), [conflictAck, setConflictAck] = useState(false)
  const recovery = useRef<HTMLButtonElement>(null)
  const evidence = useQuery({ queryKey: ['policy-editor-evidence', scope, value.evidenceReleaseId], enabled: !!value.evidenceReleaseId,
    queryFn: async ({ signal }) => {
      const result = await request('/business-evidence-releases/' + encodeURIComponent(value.evidenceReleaseId) + '?' + scopeQuery(scope), evidenceSchema, { signal })
      if (result.releaseId !== value.evidenceReleaseId || result.kind !== 'rule_evidence') throw Error('口径只接受该组织已发布的制度依据集合，不能使用背景集合。')
      return result
    } })
  useEffect(() => { if (pending && !busy) recovery.current?.focus() }, [pending, busy])
  useEffect(() => {
    const controller = new AbortController()
    request(path + '?' + scopeQuery(scope), policyReadSchema, { signal: controller.signal }).then(data => {
      if ((data.draft && data.draft.document.id !== policyId) || (data.published && data.published.document.id !== policyId)) throw Error('identity')
      setPublished(data.published)
      if (!cache.value && !cache.invalid) { setBaseline(data.draft); if (data.draft || data.published) setValue(policyDefinitionSchema.parse((data.draft ?? data.published)!.document)) }
      setLoaded(true)
    }).catch(error => { if (controller.signal.aborted) return; if (error.status === 404 && !cache.value) setLoaded(true); else setNotice('口径读取失败，本地输入保留，请重新进入核对。') })
    return () => controller.abort()
  }, [path, scope.database, scope.companyId, policyId, cache])
  const persist = (next: PolicyDefinition, base: Draft | null, original: Pending | null) => sessionStorage.setItem(key, JSON.stringify({ value: next, baseline: base, pending: original }))
  const change = (patch: Partial<PolicyDefinition>) => {
    const next = { ...value, ...patch }; setValue(next); setPreview(null); setPreviewHash(''); setAck(false)
    try { persist(next, baseline, pending) } catch { setNotice('本地草稿保存失败，提交前必须能够保存原请求。') }
  }
  const finish = (base: Draft | null, message: string) => {
    persist(value, base, null); setBaseline(base); setPending(null); setPreview(null); setPreviewHash(''); setAck(false); setRetryReady(false); setNotice(message)
    void client.invalidateQueries({ queryKey: ['statistical-policies', scope] })
    void client.invalidateQueries({ queryKey: ['policy-impact', scope] })
    void client.invalidateQueries({ queryKey: ['policy-default-target', scope] })
  }
  const submit = async (original: Pending) => {
    try { persist(value, baseline, original) } catch { setNotice('无法保存原口径提交请求，未提交。'); return }
    setPending(original); setBusy(true); setRetryReady(false)
    try {
      if (original.action === 'save') {
        const saved = await request(path + '/draft', policyDraftSchema, { method: 'PUT', csrf, body: { ...identity(scope), expectedVersion: original.expectedVersion, definition: original.definition } })
        if (saved.version !== original.expectedVersion + 1 || !samePolicy(saved.document, original.definition)) throw Error('identity')
        finish(saved, '口径草稿已保存；发布和设为默认需分别明确确认。')
      } else {
        const result = await request(path + '/publish', policyPublishedSchema.extend({ issues: policyIssuesSchema }),
          { method: 'POST', csrf, body: { ...identity(scope), expectedVersion: original.expectedVersion } })
        if (result.revision !== original.revision || result.contentHash !== original.contentHash || !samePolicy(result.document, original.definition)) throw Error('identity')
        setPublished(result); finish(baseline, '口径版本已发布，默认未改变。' + result.issues.map(issue => issue.message).join('；'))
      }
    } catch { setNotice('口径提交结果待确认，请读取原口径提交结果；不会自动重发。') }
    finally { setBusy(false) }
  }
  const recover = async () => {
    if (!pending) return
    setBusy(true); setAck(false); setRetryReady(false); setConflict(null); setChoices({}); setConflictAck(false)
    try {
      let data: z.infer<typeof policyReadSchema>
      try { data = await request(path + '?' + scopeQuery(scope) + (pending.action === 'publish' ? '&revision=' + pending.revision : ''), policyReadSchema) }
      catch (error) {
        if (!(error instanceof Error) || !('status' in error) || error.status !== 404) throw error
        if (pending.action === 'save' && pending.expectedVersion === 0) data = { draft: null, published: null }
        else if (pending.action === 'publish') { data = await request(path + '?' + scopeQuery(scope), policyReadSchema); if (data.published?.revision === pending.revision) throw Error('identity') }
        else throw error
      }
      if ((data.draft && (data.draft.document.id !== policyId || baseline && data.draft.document.scopeId !== baseline.document.scopeId))
        || data.published && data.published.document.id !== policyId) throw Error('identity')
      setPublished(data.published)
      if (pending.action === 'save' && data.draft?.version === pending.expectedVersion + 1 && samePolicy(data.draft.document, pending.definition)) finish(data.draft, '当前草稿与原提交一致；这是状态核对，不是独立请求回执。')
      else if (pending.action === 'publish' && data.published?.revision === pending.revision && data.published.contentHash === pending.contentHash && samePolicy(data.published.document, pending.definition))
        finish(baseline, '当前发布与原提交一致；默认绑定和历史报告未改变。'
          + (pending.previewIssues.length ? '原发布核对告警：' + pending.previewIssues.map(issue => issue.message).join('；') : '')
          + '这是原请求的核对记录，当前可用性需重新核对。')
      else if ((data.draft?.version ?? 0) === pending.expectedVersion && (pending.action === 'save' || data.draft?.contentHash === pending.contentHash)) { setRetryReady(true); setNotice('原口径请求尚未登记，重新确认后可显式重提。') }
      else { setConflict(data.draft); setNotice('服务器版本与原请求冲突，已保留本地输入，禁止直接覆盖。') }
    } catch { setNotice('原口径提交结果仍无法确认，保留原请求，不会自动重发。') }
    finally { setBusy(false) }
  }
  const adoptConflict = async () => {
    if (!conflict || !pending || !conflictAck || busy || policyConflictFields(value, conflict.document).some(p => !choices[p.key])) return
    setBusy(true); setAck(false); setConflictAck(false)
    try {
      const current = await request(path + '?' + scopeQuery(scope), policyReadSchema)
      if (!current.draft || current.draft.document.id !== policyId || current.draft.document.scopeId !== conflict.document.scopeId
        || current.published && current.published.document.id !== policyId) throw Error('identity')
      if (current.draft.version !== conflict.version || current.draft.contentHash !== conflict.contentHash || !samePolicy(current.draft.document, conflict.document)) {
        setConflict(current.draft); setChoices({}); setNotice('服务器草稿再次变化，请重新逐项核对；原提交记录与本地输入保留。'); return
      }
      const merged = policyDefinitionSchema.parse(current.draft.document)
      for (const field of policyConflictFields(value, current.draft.document)) if (choices[field.key] === 'local') Object.assign(merged, { [field.key]: value[field.key] })
      const archiveKey = 'management-policy-conflict:' + JSON.stringify([username, scope.database, scope.companyId, policyId, pending.action, pending.expectedVersion, conflict.version, conflict.contentHash])
      sessionStorage.setItem(archiveKey, JSON.stringify({ value, baseline, pending, server: current.draft, choices }))
      persist(merged, current.draft, null)
      setValue(merged); setBaseline(current.draft); setPublished(current.published); setPending(null); setConflict(null); setChoices({}); setPreview(null); setPreviewHash(''); setRetryReady(false)
      setNotice('已按服务器草稿版本 ' + current.draft.version + ' 准备本地修改；原提交与选择已保存在本次账号和组织的会话记录。请核对后明确保存，再重新核对发布。')
    } catch { setNotice('冲突核对未完成或无法保存核对记录，原提交与本地输入保留，未写入服务器。') }
    finally { setBusy(false) }
  }
  const check = async () => {
    if (!baseline || !samePolicy(value, baseline.document)) return
    setBusy(true); setAck(false); setPreview(null)
    try {
      const current = await request(path + '?' + scopeQuery(scope), policyReadSchema)
      if (!current.draft || current.draft.document.id !== policyId || current.draft.document.scopeId !== baseline.document.scopeId
        || current.published && (current.published.document.id !== policyId || current.published.document.scopeId !== baseline.document.scopeId)) throw Error('口径读取身份不一致')
      if (current.draft.version !== baseline.version || current.draft.contentHash !== baseline.contentHash || !samePolicy(current.draft.document, baseline.document)) {
        setNotice('服务器草稿已变化，本地内容保留；请先保存并处理版本冲突，再核对发布。'); return
      }
      setPublished(current.published)
      const result = await request(path + '/preview', policyPreviewSchema, { method: 'POST', csrf, body: { ...identity(scope), definition: policyDefinitionSchema.parse(baseline.document) } })
      setPreview(result); setPreviewHash(baseline.contentHash)
    } catch (error) { setNotice('发布核对未完成：' + (error as Error).message) }
    finally { setBusy(false) }
  }
  const dirty = !baseline || !samePolicy(value, baseline.document), blocked = !loaded || busy || cache.invalid || !!pending
  const input = (label: string, id: string, content: string | null, update: (value: string) => void, type = 'text') => <label style={{ display: 'grid', gap: 4 }}>{label}<Input id={id} type={type} disabled={blocked} value={content ?? ''} onChange={event => update(event.target.value)} /></label>
  return <Card title={'编辑统计口径 · ' + policyId} role="region" aria-label="统计口径定义编辑">
    <Space orientation="vertical" size="middle" style={{ width: '100%', overflowWrap: 'anywhere' }}>
      {notice && <Alert type="info" title={notice} />}
      {conflict && pending && <>
        <PolicyConflictComparison key={conflict.version + ':' + conflict.contentHash} local={value} server={conflict.document} version={conflict.version}
          choices={choices} onChoice={(field, choice) => { setChoices(previous => ({ ...previous, [field]: choice })); setConflictAck(false) }}
          acknowledged={conflictAck} onAcknowledge={setConflictAck} disabled={busy} />
        <Button disabled={busy || !conflictAck || policyConflictFields(value, conflict.document).some(p => !choices[p.key])} onClick={() => void adoptConflict()}>采用核对结果继续编辑</Button>
      </>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,260px),1fr))', gap: 12 }}>
        {input('口径名称', 'policy-name', value.name, name => change({ name }))}
        {input('报告场景标识', 'policy-scenario', value.scenario, scenario => change({ scenario }))}
        {input('生效开始（包含）', 'policy-valid-from', value.validFrom, validFrom => change({ validFrom }), 'date')}
        {input('生效结束（不包含，可留空）', 'policy-valid-to', value.validTo, validTo => change({ validTo: validTo || null }), 'date')}
      </div>
      <fieldset disabled={blocked}><legend>采用的精确指标版本</legend>
        {value.metricVersions.map((reference, index) => <div key={index} style={{ marginBottom: 12 }}>
          <MetricDependencyPicker scope={scope} label={'指标 ' + (index + 1)} value={reference} disabled={blocked}
            onChange={next => change({ metricVersions: value.metricVersions.map((ref, i) => i === index ? next : ref) })} onAvailabilityChange={() => {}} />
          <Button disabled={blocked} onClick={() => change({ metricVersions: value.metricVersions.filter((_, i) => i !== index) })}>移除指标 {index + 1}</Button>
        </div>)}
        <Button disabled={blocked || value.metricVersions.length >= 200} onClick={() => change({ metricVersions: [...value.metricVersions, { metricId: '', revision: 0 }] })}>添加指标</Button>
      </fieldset>
      {input('已发布制度依据集合标识', 'policy-evidence', value.evidenceReleaseId, evidenceReleaseId => change({ evidenceReleaseId }))}
      <PolicyEvidencePicker scope={scope} value={value.evidenceReleaseId} disabled={blocked} onChange={evidenceReleaseId => change({ evidenceReleaseId })} />
      {!!value.evidenceReleaseId && <AsyncState loading={evidence.isPending} error={evidence.error} retry={() => void evidence.refetch()}>
        {evidence.data?.documents.map(document => <div key={document.reference.documentId + ':' + document.reference.revision}>{document.metadata.title} · {document.reference.documentId} · 修订 {document.reference.revision}</div>)}
      </AsyncState>}
      <label>口径决策说明<Input.TextArea id="policy-notes" disabled={blocked} rows={3} maxLength={20000} value={value.decisionNotes} onChange={e => change({ decisionNotes: e.target.value })} /></label>
      <PolicyRuleFields scope={scope} value={value} disabled={blocked} onChange={change} />
      <div>草稿版本：{baseline?.version ?? '未保存'}；当前发布：{published?.revision ?? '尚未发布'}；目标发布：{baseline?.document.revision ?? '保存后确定'}；{dirty ? '有未保存修改' : '与已保存草稿一致'}。</div>
      <Button disabled={blocked || !dirty} onClick={() => { const issue = problem(value); if (issue) setNotice(issue); else void submit({ action: 'save', expectedVersion: baseline?.version ?? 0, definition: value, revision: null, contentHash: null, previewIssues: [] }) }}>保存口径草稿</Button>
      <Button disabled={blocked || dirty || !baseline} onClick={() => void check()}>核对发布变更</Button>
      {preview && <section aria-label="口径发布核对" style={{ display: 'grid', gap: 8 }}>
        <strong>已保存草稿的发布核对</strong>
        {baseline && <PolicyReleaseComparison current={published} target={baseline.document} />}
        <div><Tag>{preview.calculationChanged ? '计算规则变化' : '计算规则未变'}</Tag><Tag>{preview.evidenceChanged ? '制度依据变化' : '制度依据未变'}</Tag><Tag>{preview.metricVersionsChanged ? '指标引用版本变化' : '指标引用版本未变'}</Tag></div>
        {!!preview.changedFields.length && <div>计算变化：{preview.changedFields.map(field => fields[field] ?? field).join('、')}</div>}
        {preview.issues.map((issue, i) => <Alert key={i} type="warning" title={issue.message} />)}
        <div>默认绑定不在本次发布中调整；已运行报告继续使用原依据。语义疑点如实保留，不冒充已通过业务核对。</div>
      </section>}
      <Checkbox aria-label="确认口径发布" checked={ack} disabled={busy || cache.invalid || (!!pending && !retryReady)} onChange={e => setAck(e.target.checked)}>已核对适用期、精确指标、制度依据及告警；仅发布本口径版本</Checkbox>
      <Button disabled={blocked || dirty || !baseline || !ack || !preview || previewHash !== baseline.contentHash
        || (published?.revision === baseline.document.revision && published.contentHash === baseline.contentHash)} onClick={() => { if (baseline && preview) void submit({ action: 'publish', expectedVersion: baseline.version, definition: value, revision: baseline.document.revision, contentHash: baseline.contentHash, previewIssues: preview.issues }) }}>发布口径版本</Button>
      {pending && <Button ref={recovery} disabled={busy} onClick={() => void recover()}>读取原口径提交结果</Button>}
      {pending && retryReady && <Button disabled={busy || !ack} onClick={() => void submit(pending)}>确认重提原口径请求</Button>}
    </Space>
  </Card>
}
