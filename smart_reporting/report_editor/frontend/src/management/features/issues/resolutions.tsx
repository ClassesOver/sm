import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Input, Radio, Space } from 'antd'
import { z } from 'zod'
import { ApiError, identity, request, scopeQuery } from '../../api/http'
import { approvalRequestHash } from './business-approvals'
import { correctedVersionSchema } from './fix-versions'

const id = z.string().min(1).max(128).regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/)
const requestSchema = z.object({ requestId: id, expectedIssueVersion: z.number().int().positive(),
  regressionReceiptIds: z.array(id).min(1).max(50), businessApprovalRequestId: id,
  mode: z.enum(['recalculated', 'not_recalculated']), decisionReason: z.string().min(1).max(10000),
  notRecalculatedReason: z.string().max(2000), originalReportUnchanged: z.literal(true),
}).refine(value => !!value.decisionReason.trim() && (value.mode === 'not_recalculated' ? !!value.notRecalculatedReason.trim() : value.notRecalculatedReason === ''))
const pendingSchema = z.object({ issueId: id, request: requestSchema, correctedVersions: z.array(correctedVersionSchema) })
const receiptSchema = z.object({ receiptId: id, issueId: id, request: requestSchema,
  requestHash: z.string().regex(/^[a-f0-9]{64}$/), correctedVersions: z.array(correctedVersionSchema),
  issueClosed: z.literal(true), historicalResult: z.literal(true), resolvedIssueVersion: z.number().int().positive(),
  resolvedByUsername: z.string(), resolvedByAccountId: z.number().int().positive(), createdAt: z.string(),
  evidence: z.object({ regressionEvidenceReady: z.literal(true), originalEvidenceReady: z.literal(true), businessApprovalReady: z.literal(true),
    deliveryReady: z.boolean(), factPresentationReady: z.boolean(), newReportRevision: id.nullable(),
    deliveries: z.array(z.object({ targetRunId: id, outputRevision: z.number().int().positive(), validationPassed: z.boolean(),
      artifacts: z.array(z.object({ format: z.enum(['pdf', 'docx', 'pptx', 'xlsx']), path: z.string(), sha256: z.string(), size: z.number().int().positive() })) })) }) })
type Pending = z.infer<typeof pendingSchema>
type Receipt = z.infer<typeof receiptSchema>
export type ResolutionPreparation = { approvalRequestId: string; regressionReceiptIds: string[]; regressionReady: boolean;
  originalReady: boolean; approvalReady: boolean; deliveryReady: boolean; factsReady: boolean }
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export function IssueResolution({ scope, issueId, version, username, csrf, correctedVersions, preparation, disabled, resolutionRequestId, onResolved }: {
  scope: { database: string; companyId: string }; issueId: string; version: number; username: string; csrf: string;
  correctedVersions: z.infer<typeof correctedVersionSchema>[]; preparation: ResolutionPreparation | null; disabled: boolean; resolutionRequestId?: string | null; onResolved?: () => void
}) {
  const path = '/report-issue-reviews/' + encodeURIComponent(issueId) + '/resolutions'
  const cacheKey = 'management-issue-resolution:' + JSON.stringify([username, scope.database, scope.companyId, issueId])
  const [cached] = useState(() => {
    try {
      const raw = sessionStorage.getItem(cacheKey)
      return { pending: raw === null ? null : pendingSchema.parse(JSON.parse(raw)), unreadable: false }
    } catch { return { pending: null, unreadable: true } }
  })
  const [pending, setPending] = useState<Pending | null>(cached.pending)
  const [prior, setPrior] = useState<Pending | null>(() => { try { return pendingSchema.parse(JSON.parse(sessionStorage.getItem(cacheKey + ':prior') ?? 'null')) } catch { return null } })
  const [mode, setMode] = useState<'recalculated' | 'not_recalculated' | null>(null)
  const [reason, setReason] = useState(''), [notRecalculated, setNotRecalculated] = useState('')
  const [acknowledged, setAcknowledged] = useState(false), [knownId, setKnownId] = useState('')
  const [receipt, setReceipt] = useState<Receipt | null>(null), [notice, setNotice] = useState(cached.unreadable ? '原关闭缓存无法读取；请先按原请求标识读回核对，不覆盖缓存或提交新关闭。' : '')
  const [outcome, setOutcome] = useState<'retry' | 'changed' | 'mismatch' | null>(null), [busy, setBusy] = useState(false)
  const running = useRef(false), readButton = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (pending && !busy) readButton.current?.focus() }, [pending, busy])
  useEffect(() => { setAcknowledged(false) }, [preparation, version, correctedVersions])
  const ready = !disabled && !cached.unreadable && !!preparation?.regressionReady && preparation.originalReady && preparation.approvalReady
  const deliveryReady = ready && preparation!.deliveryReady && preparation!.factsReady
  const matches = async (value: Receipt, original?: Pending) => value.issueId === issueId
    && value.resolvedIssueVersion === value.request.expectedIssueVersion + 1
    && value.requestHash === await approvalRequestHash(value.request)
    && (value.request.mode !== 'recalculated' || value.evidence.deliveryReady && value.evidence.factPresentationReady
      && !!value.evidence.newReportRevision && value.evidence.deliveries.length === value.request.regressionReceiptIds.length)
    && (value.request.mode !== 'not_recalculated' || value.evidence.newReportRevision === null)
    && (!original || same(value.request, original.request) && same(value.correctedVersions, original.correctedVersions))
  const accept = (value: Receipt, message: string) => {
    setReceipt(value); setOutcome(null); setNotice(message)
    try { sessionStorage.removeItem(cacheKey); setPending(null) }
    catch { setNotice(message + ' 本地请求缓存尚未清除，请继续保留原登记。') }
    onResolved?.()
  }
  const post = async (original: Pending) => {
    if (running.current || disabled) return
    try { sessionStorage.setItem(cacheKey, JSON.stringify(pendingSchema.parse(original))) }
    catch { setNotice('无法保存关闭请求，请启用会话存储后再提交。'); return }
    running.current = true; setBusy(true); setPending(original); setOutcome(null)
    try {
      const value = await request(path, receiptSchema, { method: 'POST', csrf, body: { ...identity(scope), ...original.request } })
      if (!await matches(value, original)) { setOutcome('mismatch'); setNotice('关闭响应与原请求不一致，保留输入，请读取原关闭结果核对。'); return }
      accept(value, '关闭已登记。原报告保留，处理证据已存档。')
    } catch (error) { setNotice('关闭结果待确认，请先读取原关闭结果；不会自动重发。' + (error instanceof ApiError ? ` ${error.message}` : '')) }
    finally { running.current = false; setBusy(false) }
  }
  const read = async (registeredId?: string) => {
    const requestId = pending?.request.requestId ?? registeredId ?? knownId.trim()
    if (running.current || !id.safeParse(requestId).success) { setNotice('请输入有效的原关闭请求标识。'); return }
    running.current = true; setBusy(true); setOutcome(null)
    try {
      const value = await request(path + '/' + encodeURIComponent(requestId) + '?' + scopeQuery(scope), receiptSchema)
      if (value.request.requestId !== requestId || !await matches(value, pending ?? undefined)) {
        setOutcome('mismatch'); setNotice('关闭登记与本地完整请求不一致，请保留输入核对。'); return
      }
      accept(value, '已确认原关闭登记；此记录只证明当时处理，不证明原件当前仍可用。')
    } catch (error) {
      if (pending && error instanceof ApiError && error.status === 404 && error.code === 'management_issue_resolution_not_found') {
        try {
          const current = await request('/report-issue-reviews?' + scopeQuery(scope) + '&issueId=' + encodeURIComponent(issueId),
            z.object({ items: z.array(z.object({ version: z.number(), review: z.object({ issueId: z.string(), status: z.string(), correctedVersions: z.array(correctedVersionSchema) }) })) }))
          const item = current.items.find(item => item.review.issueId === issueId)
          const unchanged = item?.version === pending.request.expectedIssueVersion && item.review.status === 'accepted'
            && same(item.review.correctedVersions, pending.correctedVersions)
          setOutcome(unchanged ? 'retry' : 'changed')
          setNotice(unchanged ? '原关闭未登记，问题及修复版本未变。核对原完整请求后，可明确重提；服务端将再次检查当前证据。'
            : '问题或修复版本已变化，请保留原关闭输入并重新核对，不能直接重提。')
        } catch { setNotice('无法确认当前问题状态，请继续读取原结果；不会重提关闭。') }
      } else setNotice('原关闭结果仍未知，请显式重试读取；不会重复提交。')
    } finally { running.current = false; setBusy(false) }
  }
  const submit = () => {
    if (!ready || !acknowledged || !mode || mode === 'recalculated' && !deliveryReady) return
    const parsed = pendingSchema.safeParse({ issueId, correctedVersions, request: { requestId: crypto.randomUUID(), expectedIssueVersion: version,
      regressionReceiptIds: preparation!.regressionReceiptIds, businessApprovalRequestId: preparation!.approvalRequestId, mode,
      decisionReason: reason, notRecalculatedReason: mode === 'not_recalculated' ? notRecalculated.trim() : '', originalReportUnchanged: true } })
    if (!parsed.success) { setNotice('请明确处理方式、关闭裁定理由和本次不重算理由。'); return }
    void post(parsed.data)
  }
  return <section aria-label="正式关闭报告问题">
    <h3>正式关闭问题</h3>
    <p>关闭时重新核验当前证据，原报告始终保留。关闭不代表整份报告验收通过，也不改变下载许可。</p>
    {notice && <Alert type="info" title={notice} />}
    {pending && <Card size="small" title="待确认的原关闭请求">
      <p>{pending.request.mode === 'not_recalculated' ? '本次不重算' : '已生成新报告'} · {pending.request.decisionReason}</p>
      {pending.request.notRecalculatedReason && <p>不重算理由：{pending.request.notRecalculatedReason}</p>}
      <details><summary>原完整关闭请求</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(pending, null, 2)}</pre></details>
      <Space wrap><Button ref={readButton} aria-label="读取原关闭结果" aria-busy={busy} loading={busy} onClick={() => void read()}>读取原关闭结果</Button>
        {outcome === 'retry' && <Button disabled={disabled} loading={busy} onClick={() => void post(pending)}>确认重提原关闭</Button>}
        {outcome === 'changed' && <Button disabled={busy} onClick={() => {
          try {
            sessionStorage.setItem(cacheKey + ':prior', JSON.stringify(pending)); sessionStorage.removeItem(cacheKey)
            setPrior(pending); setReason(pending.request.decisionReason); setMode(pending.request.mode)
            setNotRecalculated(pending.request.notRecalculatedReason); setPending(null); setOutcome(null); setAcknowledged(false)
            setNotice('原完整输入与理由已保留，请重新选择并检查当前证据，再明确确认。')
          }
          catch { setNotice('无法更新关闭缓存，请先核对会话存储。') }
        }}>保留原输入，重新核对关闭条件</Button>}
      </Space>
    </Card>}
    {!pending && !receipt && !resolutionRequestId && <fieldset disabled={busy || disabled}>
      <legend>选择本次处理方式</legend>
      {!ready && <p>请先明确选择业务预期签认，并检查回归、原件与新报告关系。</p>}
      <Radio.Group aria-label="关闭处理方式" value={mode} onChange={event => { setMode(event.target.value); setAcknowledged(false) }}>
        <Space orientation="vertical"><Radio value="recalculated" disabled={!deliveryReady}>已生成并核对新报告</Radio>
          <Radio value="not_recalculated" disabled={!ready}>本次不重算，明确裁定保留原报告</Radio></Space>
      </Radio.Group>
      {!deliveryReady && <p>新报告交付或纠错事实尚未完整核验，“已生成新报告”暂不可选。</p>}
      <label>关闭裁定理由<Input.TextArea aria-label="关闭裁定理由" rows={3} maxLength={10000} value={reason} onChange={event => { setReason(event.target.value); setAcknowledged(false) }} /></label>
      {mode === 'not_recalculated' && <label>本次不重算的理由<Input.TextArea aria-label="本次不重算的理由" rows={3} maxLength={2000} value={notRecalculated} onChange={event => { setNotRecalculated(event.target.value); setAcknowledged(false) }} /></label>}
      <Checkbox aria-label="确认关闭并保留原报告" checked={acknowledged} disabled={!ready || !mode} onChange={event => setAcknowledged(event.target.checked)}>我已核对本次处理与独立预期，明确关闭问题并保留原报告。</Checkbox>
      <p>本次关联 {preparation?.regressionReceiptIds.length ?? 0} 条回归、{correctedVersions.length} 项正式修复；签认只限精确回归预期。</p>
      <Button type="primary" aria-label="确认关闭问题" aria-busy={busy} loading={busy} disabled={!ready || !mode || !acknowledged || !reason.trim() || mode === 'not_recalculated' && !notRecalculated.trim()} onClick={submit}>确认关闭问题</Button>
    </fieldset>}
    {receipt && <div role="status">
      <p>问题已关闭 · {receipt.request.mode === 'not_recalculated' ? '本次不重算，原报告保留' : '新报告已交付并核对纠错事实'}。</p>
      <p>处理人：{receipt.resolvedByUsername} · {receipt.createdAt} · 问题版本 {receipt.resolvedIssueVersion}</p>
      <p>裁定理由：{receipt.request.decisionReason}</p>
      {receipt.request.notRecalculatedReason && <p>不重算理由：{receipt.request.notRecalculatedReason}</p>}
      <p>历史处理不代表当前原件仍可读取，也不代表整份报告验收通过。</p>
      {receipt.evidence.deliveries.map((item, index) => <p key={index}>新报告修订 {item.outputRevision} · {item.artifacts.map(file => file.format.toUpperCase()).join('、')}
        {!item.validationPassed && ' · 原交付验收未通过，文件及处理记录仍保留。'}</p>)}
      <details><summary>关闭回执与原请求标识</summary><p>{receipt.receiptId}</p><p>{receipt.request.requestId}</p></details>
    </div>}
    {prior && <details><summary>上次关闭输入（仅供核对）</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(prior, null, 2)}</pre></details>}
    {!pending && !receipt && resolutionRequestId && <Button loading={busy} onClick={() => void read(resolutionRequestId)}>读取本问题关闭记录</Button>}
    {!pending && <Space wrap><Input aria-label="已有关闭请求标识" placeholder="原关闭请求标识，可只读恢复" maxLength={128} value={knownId} onChange={event => setKnownId(event.target.value)} />
      <Button disabled={!knownId.trim() || busy} onClick={() => void read()}>读取已有关闭记录</Button></Space>}
  </section>
}
