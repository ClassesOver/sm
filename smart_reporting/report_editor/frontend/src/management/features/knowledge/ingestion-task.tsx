import { useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { identity, request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'
const jobSchema = z.object({ jobId: z.string(), documentId: z.string(), revision: z.number().int().positive(), attempt: z.number().int().nonnegative(),
 status: z.enum(['queued', 'running', 'parsed', 'failed', 'ready', 'needs_transcription']), issueCodes: z.array(z.string()) })
const pendingSchema = z.object({ jobId: z.string(), documentId: z.string(), revision: z.number().int().positive(), expectedAttempt: z.number().int().nonnegative() })
const labels = { queued: '排队中', running: '解析中', parsed: '已解析，待发布', failed: '解析失败', ready: '索引就绪', needs_transcription: '需人工转录' }
export function IngestionTask({ scope, jobId, documentId, revision, username, csrf }: {
 scope: { database: string; companyId: string }; jobId: string; documentId: string | null; revision: number | null; username: string; csrf: string
}) {
 const client = useQueryClient(), running = useRef(false)
 const key = 'management-ingestion-retry:' + JSON.stringify([username, scope.database, scope.companyId, jobId])
 const [cache] = useState(() => { try {
  const raw = sessionStorage.getItem(key), value = raw ? pendingSchema.parse(JSON.parse(raw)) : null
  if (value && (value.jobId !== jobId || value.documentId !== documentId || value.revision !== revision)) throw Error('任务缓存身份不符')
  return { value, invalid: false }
 } catch { return { value: null, invalid: true } } })
 const [pending, setPending] = useState(cache.value), [busy, setBusy] = useState(false), [ack, setAck] = useState(false)
 const [notice, setNotice] = useState(''), [retryReady, setRetryReady] = useState(false)
 const path = '/business-ingestion-jobs/' + encodeURIComponent(jobId)
 const job = useQuery({ queryKey: ['business-ingestion-job', scope, jobId], retry: false,
  queryFn: ({ signal }) => request(path + '?' + scopeQuery(scope), jobSchema, { signal }) })
 const matches = (value: z.infer<typeof jobSchema>) => value.jobId === jobId && value.documentId === documentId && value.revision === revision
 const invalidate = () => {
  void client.invalidateQueries({ queryKey: ['business-document-detail'] }); void client.invalidateQueries({ queryKey: ['business-documents'] })
 }
 const submit = async () => {
  if (running.current || !ack || cache.invalid || !job.data || !matches(job.data) || job.data.status !== 'failed' || pending && !retryReady) return
  const input = pending ?? { jobId, documentId: job.data.documentId, revision: job.data.revision, expectedAttempt: job.data.attempt }
  try { sessionStorage.setItem(key, JSON.stringify(input)) } catch { setNotice('无法保存原重试请求，未重新排队。'); return }
  running.current = true; setBusy(true); setPending(input); setAck(false); setRetryReady(false)
  try {
   const value = await request(path + '/retry', jobSchema, { method: 'POST', csrf, body: { ...identity(scope), expectedAttempt: input.expectedAttempt } })
   if (!matches(value) || value.status !== 'queued' || value.attempt !== input.expectedAttempt) throw Error('重试响应与原任务不一致')
   sessionStorage.removeItem(key); setPending(null); client.setQueryData(['business-ingestion-job', scope, jobId], value)
   setNotice('已请求重新排队；尚未解析成功，请读取后续状态。'); invalidate()
  } catch (error) { setNotice('重试结果待确认：' + (error as Error).message + ' 请读取原重试状态，不自动重发。') }
  finally { running.current = false; setBusy(false) }
 }
 const recover = async () => {
  if (!pending || running.current) return
  running.current = true; setBusy(true); setAck(false); setRetryReady(false)
  try {
   const value = await request(path + '?' + scopeQuery(scope), jobSchema)
   if (!matches(value)) throw Error('任务身份与原重试请求不一致，保留原请求核对。')
   client.setQueryData(['business-ingestion-job', scope, jobId], value)
   if (value.attempt < pending.expectedAttempt) { setNotice('当前尝试版本早于原重试请求，请保留原请求核对。'); return }
   if (value.attempt === pending.expectedAttempt && value.status === 'failed') {
    setRetryReady(true); setNotice('当前仍为原失败尝试；重新确认后可显式重提，不自动判断原请求失败。')
   } else {
    sessionStorage.removeItem(key); setPending(null)
    setNotice('当前任务已推进；这是任务状态读回，不能据此认定唯一重试请求，未自动重新排队。'); invalidate()
   }
  } catch (error) { setNotice((error as Error).message) }
  finally { running.current = false; setBusy(false) }
 }
 return <Card title="本次入库任务" extra={<Button disabled={busy} loading={job.isFetching} onClick={() => { setAck(false); void job.refetch().then(invalidate) }}>读取解析状态</Button>}>
  {cache.invalid && <Alert type="error" title="原重试缓存损坏或身份不符，禁止写入，请保留记录核对。" />}
  {notice && <Alert type="info" title={notice} />}
  {pending && <><Alert type="warning" title="重试结果待确认" /><p>原任务 {pending.jobId} · 修订 {pending.revision} · 原尝试 {pending.expectedAttempt}</p>
   <Button disabled={busy || cache.invalid} onClick={() => void recover()}>读取原重试状态</Button></>}
  <AsyncState loading={job.isPending} error={job.error} retry={() => void job.refetch()}>
   {job.data && !matches(job.data) ? <Alert type="warning" title="任务身份与当前原件修订不一致，请按原任务核对。" /> : job.data && <>
    <p>{labels[job.data.status]} · 修订 {job.data.revision} · 已尝试 {job.data.attempt} 次</p>
    {job.data.issueCodes.map(code => <Alert key={code} type="warning" title={'解析问题：' + code} />)}
    {job.data.status === 'needs_transcription' && <Alert type="warning" title="原件需人工转录；请核对并登记可解析的新修订，不能通过反复重试认定入库成功。" />}
    {job.data.status === 'failed' && <section aria-label="解析失败重试" style={{ display: 'grid', gap: 12 }}>
     <p>仅重新排队此失败任务，不创建原件新修订，不批准或发布。已撤销原件由服务器拒绝重新读取。</p>
     <Checkbox aria-label="确认重新解析" disabled={busy || job.isFetching || cache.invalid || !!pending && !retryReady} checked={ack} onChange={e => setAck(e.target.checked)}>已核对失败原因、原件修订及当前尝试，明确请求重新解析。</Checkbox>
     <Button disabled={!ack || busy || job.isFetching || cache.invalid || !!pending && !retryReady} loading={busy} onClick={() => void submit()}>重新排队解析</Button>
    </section>}
    <p>解析完成后仍需核对原件并明确审核，再另行发布证据集合。状态读取不会重新执行任务。</p>
   </>}
  </AsyncState>
 </Card>
}
