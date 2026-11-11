import { useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, Select, Space } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { identity, request, scopeQuery } from '../../api/http'
import { DocumentImpact } from './document-impact'

const decisionSchema = z.enum(['approved', 'rejected', 'revoked'])
const pendingSchema = z.object({ documentId: z.string(), revision: z.number().int().positive(), originalHash: z.string(),
 expectedVersion: z.number().int().positive(), decision: decisionSchema, reason: z.string().min(1).max(4000) })
const stateSchema = z.object({ stateVersion: z.number().int().positive(), reviewStatus: z.string(), ingestionStatus: z.string() })
const detailSchema = z.object({ documentId: z.string(), revisions: z.array(stateSchema.extend({ revision: z.number().int().positive(), originalHash: z.string(),
 reviewReceipt: z.object({ decision: z.string(), reason: z.string() }).nullable() })) })
type Target = z.infer<typeof detailSchema>['revisions'][number]
export function DocumentReview({ scope, documentId, target, username, csrf }: {
 scope: { database: string; companyId: string }; documentId: string; target: Target; username: string; csrf: string
}) {
 const client = useQueryClient(), running = useRef(false)
 const cacheKey = 'management-document-review:' + JSON.stringify([username, scope, documentId, target.revision])
 const [cache] = useState(() => { try {
  const raw = sessionStorage.getItem(cacheKey), stored = raw ? pendingSchema.parse(JSON.parse(raw)) : null
  if (stored && (stored.documentId !== documentId || stored.revision !== target.revision || stored.originalHash !== target.originalHash)) throw Error('审核缓存身份不一致')
  return { pending: stored, invalid: false }
 } catch { return { pending: null, invalid: true } } })
 const [pending, setPending] = useState(cache.pending)
 const [decision, setDecision] = useState<z.infer<typeof decisionSchema>>('approved'), [reason, setReason] = useState(''), [ack, setAck] = useState(false)
 const [busy, setBusy] = useState(false), [notice, setNotice] = useState(''), [retryReady, setRetryReady] = useState(false), [finished, setFinished] = useState(false)
 const invalidate = () => { void client.invalidateQueries({ queryKey: ['business-documents'] }); void client.invalidateQueries({ queryKey: ['business-document-detail'] }) }
 const clear = () => { sessionStorage.removeItem(cacheKey); setPending(null); setRetryReady(false) }
 const submit = async () => {
  if (running.current || !ack || !reason.trim() && !pending || cache.invalid || finished) return
  const input = pending ?? { documentId, revision: target.revision, originalHash: target.originalHash, expectedVersion: target.stateVersion, decision, reason: reason.trim() }
  if (pending && !retryReady) return
  try { sessionStorage.setItem(cacheKey, JSON.stringify(input)) } catch { setNotice('无法保存原审核请求，未提交，请检查会话存储。'); return }
  running.current = true; setBusy(true); setPending(input); setAck(false); setRetryReady(false)
  try {
   const result = await request('/business-documents/' + encodeURIComponent(documentId) + '/revisions/' + input.revision + '/review', stateSchema,
    { method: 'POST', csrf, body: { ...identity(scope), expectedVersion: input.expectedVersion, decision: input.decision, reason: input.reason } })
   if (result.stateVersion !== input.expectedVersion + 1 || result.reviewStatus !== input.decision) throw Error('审核响应身份不一致')
   clear(); setFinished(true); setNotice('审核决定已登记；不会发布证据集合或改写报告依据。'); invalidate()
  } catch { setNotice('原件审核结果待确认，请读取原审核结果，不要重复提交。') }
  finally { running.current = false; setBusy(false) }
 }
 const recover = async () => {
  if (!pending || running.current) return
  running.current = true; setBusy(true); setRetryReady(false); setAck(false)
  try {
   const result = await request('/business-documents/' + encodeURIComponent(documentId) + '?' + scopeQuery(scope), detailSchema)
   const current = result.documentId === documentId ? result.revisions.find(r => r.revision === pending.revision) : undefined
   if (!current || pending.documentId !== documentId || current.originalHash !== pending.originalHash) { setNotice('当前原件身份与原审核请求不一致，保留原请求核对。'); return }
   if (current.stateVersion === pending.expectedVersion + 1 && current.reviewStatus === pending.decision
    && current.reviewReceipt?.decision === pending.decision && current.reviewReceipt.reason === pending.reason) {
    clear(); setFinished(true); setNotice('当前状态与原审核决定一致；此为状态读回，不是独立请求回执。'); invalidate()
   } else if (current.stateVersion === pending.expectedVersion) { setRetryReady(true); setNotice('当前状态版本未变；重新明确确认后可显式提交原请求。') }
   else setNotice('当前状态与原审核请求不一致，保留原理由和决定供核对，不自动覆盖。')
  } catch (error) { setNotice((error as Error).message) }
  finally { running.current = false; setBusy(false) }
 }
 if (target.reviewStatus === 'revoked' && !pending) return <><Alert type="warning" title="已撤销修订不可重新启用，请登记新修订。" /><DocumentImpact scope={scope} documentId={documentId} revision={target.revision} /></>
 return <section aria-label="原件修订审核" style={{ display: 'grid', gap: 12 }}>
  <p>审核仅针对原件修订 {target.revision}；不会发布证据集合或改写既有报告依据。</p>
  {notice && <Alert type="info" title={notice} />}
  {cache.invalid && <Alert type="error" title="原审核缓存损坏，禁止写入，请保留并核对会话记录。" />}
  {pending ? <><Alert type="warning" title="原件审核结果待确认" /><div>原决定：{pending.decision} · 状态版本 {pending.expectedVersion} · 理由：{pending.reason}</div>
   <Button disabled={busy || cache.invalid} onClick={() => void recover()}>读取原审核结果</Button></> : <>
   <label>审核决定<Select aria-label="审核决定" style={{ width: '100%' }} value={decision} disabled={busy || finished || cache.invalid} onChange={v => { setDecision(v); setAck(false) }}
    options={[{ value: 'approved', label: '批准原件修订' }, { value: 'rejected', label: '拒绝原件修订' }, { value: 'revoked', label: '撤销原件访问' }]} /></label>
   <label>审核理由<Input.TextArea aria-label="审核理由" value={reason} maxLength={4000} rows={3} disabled={busy || finished || cache.invalid} onChange={e => { setReason(e.target.value); setAck(false) }} /></label>
  </>}
  {(pending?.decision ?? decision) === 'revoked' && <DocumentImpact scope={scope} documentId={documentId} revision={target.revision} />}
  <Checkbox aria-label="确认原件审核" disabled={busy || finished || cache.invalid || !!pending && !retryReady} checked={ack} onChange={e => setAck(e.target.checked)}>已核对精确修订原件与解析状态，明确登记上述决定和理由。</Checkbox>
  <Space wrap><Button type="primary" loading={busy} disabled={!ack || finished || cache.invalid || (!pending && (!reason.trim() || decision === 'approved' && !['parsed', 'ready'].includes(target.ingestionStatus))) || !!pending && !retryReady} onClick={() => void submit()}>提交原件审核</Button></Space>
 </section>
}
