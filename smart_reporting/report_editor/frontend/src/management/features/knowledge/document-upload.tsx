import { useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Input, Select, Space } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { ApiError, identity, request, scopeQuery } from '../../api/http'
const idSchema = z.string().min(1).max(128).regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/)
export const metadataSchema = z.object({ id: idSchema, title: z.string().trim().min(1).max(200), kind: z.enum(['rule_evidence', 'background']),
 validFrom: z.string().nullable(), validTo: z.string().nullable(), eventTime: z.string().nullable(),
 appliesTo: z.array(z.object({ kind: z.enum(['metric', 'project', 'organization']), id: idSchema })).max(200) })
export const uploadReceiptSchema = z.object({ documentId: idSchema, revision: z.number().int().positive(), version: z.number().int().positive(),
 jobId: idSchema, status: z.string(), issueCodes: z.array(z.string()) })
const pendingSchema = z.object({ requestId: idSchema, expectedVersion: z.number().int().nonnegative(), filename: z.string().min(1),
 originalHash: z.string().regex(/^[a-f0-9]{64}$/), sizeBytes: z.number().int().positive().max(20971520), metadata: metadataSchema })
const registrationSchema = pendingSchema.omit({ sizeBytes: true }).extend({ receipt: uploadReceiptSchema })
const versionSchema = z.object({ documentId: idSchema, version: z.number().int().positive() })
const blank: z.infer<typeof metadataSchema> = { id: '', title: '', kind: 'rule_evidence', validFrom: null, validTo: null, eventTime: null, appliesTo: [] }
export type UploadTarget = { expectedVersion: number; metadata: z.infer<typeof metadataSchema> }
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const validDate = (value: string | null) => value === null || /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
async function fileHash(file: File) { return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())), v => v.toString(16).padStart(2, '0')).join('') }
export function DocumentUpload({ scope, username, csrf, initial, onUploaded }: {
 scope: { database: string; companyId: string }; username: string; csrf: string; initial?: UploadTarget; onUploaded: (receipt: z.infer<typeof uploadReceiptSchema>) => void
}) {
 const client = useQueryClient(), running = useRef(false)
 const key = 'management-document-upload:' + JSON.stringify([username, scope.database, scope.companyId])
 const [cache] = useState(() => { try { const raw = sessionStorage.getItem(key); return { value: raw ? pendingSchema.parse(JSON.parse(raw)) : null, invalid: false } } catch { return { value: null, invalid: true } } })
 const [pending, setPending] = useState(cache.value), [metadata, setMetadata] = useState(initial?.metadata ?? blank)
 const expectedVersion = initial?.expectedVersion ?? 0
 const [file, setFile] = useState<File | null>(null), [ack, setAck] = useState(false), [busy, setBusy] = useState(false)
 const [retryReady, setRetryReady] = useState(false), [notice, setNotice] = useState(''), [receipt, setReceipt] = useState<z.infer<typeof uploadReceiptSchema> | null>(null)
 const change = (patch: Partial<z.infer<typeof metadataSchema>>) => { setMetadata(v => ({ ...v, ...patch })); setAck(false) }
 const accept = (result: z.infer<typeof uploadReceiptSchema>, original: z.infer<typeof pendingSchema>) => {
  if (result.documentId !== original.metadata.id || result.revision !== original.expectedVersion + 1 || result.version !== result.revision) throw Error('登记身份与原上传不一致，请保留原请求核对。')
  setReceipt(result); setRetryReady(false); setNotice('原上传请求已登记，尚未审核或发布；请查看解析状态。')
  void client.invalidateQueries({ queryKey: ['business-documents'] }); void client.invalidateQueries({ queryKey: ['business-document-detail'] }); onUploaded(result)
 }
 const submit = async () => {
  if (running.current || cache.invalid || receipt || !ack || !file || pending && !retryReady) return
  running.current = true; setBusy(true)
  try {
   if (!/\.(txt|md|pdf|docx)$/i.test(file.name) || /[/\\]/.test(file.name) || !file.size || file.size > 20971520) throw Error('请选择不超过20MiB的UTF-8文本、Markdown、PDF或DOCX文件。')
   const originalHash = await fileHash(file)
   const input = pending ?? pendingSchema.parse({ requestId: crypto.randomUUID(), expectedVersion, filename: file.name, originalHash, sizeBytes: file.size, metadata })
   if (!validDate(input.metadata.validFrom) || !validDate(input.metadata.validTo) || !validDate(input.metadata.eventTime)
     || input.metadata.validFrom && input.metadata.validTo && input.metadata.validFrom >= input.metadata.validTo) throw Error('请填写真实日期和非空半开适用期。')
   if (pending && (input.filename !== file.name || input.originalHash !== originalHash || input.sizeBytes !== file.size)) throw Error('重选文件与原上传身份不一致，未提交。')
   try { sessionStorage.setItem(key, JSON.stringify(input)) } catch { throw Error('无法保存原上传请求，未发送文件，请检查会话存储。') }
   setPending(input); setRetryReady(false); setAck(false)
   const form = new FormData()
   form.set('file', file); form.set('scopeDatabase', scope.database); form.set('companyId', scope.companyId)
   form.set('expectedVersion', String(input.expectedVersion)); form.set('requestId', input.requestId); form.set('metadata', JSON.stringify(input.metadata))
   try { accept(await request('/business-documents', uploadReceiptSchema, { method: 'POST', body: form, csrf }), input) }
   catch (error) { setNotice('上传登记结果待确认：' + (error as Error).message + ' 请先读取原上传结果，不自动重发。') }
  } catch (error) { setNotice(error instanceof z.ZodError ? '请填写有效的原件标识、标题及适用对象。' : (error as Error).message) }
  finally { running.current = false; setBusy(false) }
 }
 const recover = async () => {
  if (!pending || running.current) return
  running.current = true; setBusy(true); setRetryReady(false); setAck(false)
  try {
   const found = await request('/business-document-requests/' + encodeURIComponent(pending.requestId) + '?' + scopeQuery(scope), registrationSchema)
   if (found.requestId !== pending.requestId || found.expectedVersion !== pending.expectedVersion || found.originalHash !== pending.originalHash
    || found.filename !== pending.filename || !same(found.metadata, pending.metadata)) throw Error('登记身份与原上传不一致，请保留原请求核对。')
   accept(found.receipt, pending)
  } catch (error) {
   if (error instanceof ApiError && error.status === 404 && error.code === 'management_registration_not_found') {
    try {
     let version = 0
     try { const current = await request('/business-documents/' + encodeURIComponent(pending.metadata.id) + '?' + scopeQuery(scope), versionSchema)
      if (current.documentId !== pending.metadata.id) throw Error('原件身份不一致'); version = current.version
     } catch (readError) { if (!(readError instanceof ApiError && readError.status === 404 && readError.code === 'management_document_not_found')) throw readError }
     if (version === pending.expectedVersion) { setRetryReady(true); setNotice('尚未找到原上传登记，当前版本未变。重选相同文件并重新确认后可显式重提原请求。') }
     else setNotice('尚未找到原上传登记，但原件已有其他修订；保留原输入，禁止覆盖。')
    } catch (readError) { setNotice((readError as Error).message) }
   } else setNotice((error as Error).message)
  } finally { running.current = false; setBusy(false) }
 }
 const blocked = busy || cache.invalid || !!pending || !!receipt
 return <Card title={initial ? '登记原件新修订' : '登记业务原件'}>
  <section aria-label="原件上传登记" style={{ display: 'grid', gap: 12, overflowWrap: 'anywhere' }}>
   <p>支持UTF-8文本、Markdown、可提取文本PDF及DOCX，单文件≤20MiB。扫描件或解析不完整会标记需人工转录；登记不会批准或发布。</p>
   {cache.invalid && <Alert type="error" title="原上传缓存损坏，禁止写入，请保留并核对记录。" />}
   {notice && <Alert type="info" title={notice} />}
   {pending ? <><div>原请求：{pending.requestId} · {pending.metadata.title}（{pending.metadata.id}）· 预期版本 {pending.expectedVersion} · {pending.filename}</div>
    <Button disabled={busy || cache.invalid} onClick={() => void recover()}>读取原上传结果</Button></> : <>
    <label>原件标识<Input aria-label="原件标识" value={metadata.id} maxLength={128} disabled={blocked || !!initial} onChange={e => change({ id: e.target.value })} /></label>
    <label>原件标题<Input aria-label="原件标题" value={metadata.title} maxLength={200} disabled={blocked} onChange={e => change({ title: e.target.value })} /></label>
    <label>原件用途<Select aria-label="登记原件用途" value={metadata.kind} disabled={blocked} style={{ width: '100%' }} onChange={kind => change({ kind })} options={[{ value: 'rule_evidence', label: '制度依据' }, { value: 'background', label: '背景材料' }]} /></label>
    <Space wrap>{(['validFrom', 'validTo', 'eventTime'] as const).map((field, i) => <label key={field}>{['适用开始（含）', '适用结束（不含）', '事件时间（可选）'][i]}<Input type="date" aria-label={['原件适用开始', '原件适用结束', '原件事件时间'][i]} value={metadata[field] ?? ''} disabled={blocked} onChange={e => change({ [field]: e.target.value || null })} /></label>)}</Space>
    <fieldset><legend>适用对象（可选）</legend>{metadata.appliesTo.map((ref, i) => <Space wrap key={i}>
     <Select aria-label={'对象 '+(i+1)+' 类型'} value={ref.kind} disabled={blocked} onChange={kind => change({ appliesTo: metadata.appliesTo.map((v,j)=>j===i?{...v,kind}:v) })} options={[{value:'metric',label:'指标'},{value:'project',label:'项目'},{value:'organization',label:'组织'}]} />
     <Input aria-label={'对象 '+(i+1)+' 标识'} value={ref.id} disabled={blocked} maxLength={128} onChange={e=>change({appliesTo:metadata.appliesTo.map((v,j)=>j===i?{...v,id:e.target.value}:v)})} />
     <Button disabled={blocked} onClick={()=>change({appliesTo:metadata.appliesTo.filter((_,j)=>j!==i)})}>移除对象 {i+1}</Button></Space>)}
     <Button disabled={blocked || metadata.appliesTo.length>=200} onClick={()=>change({appliesTo:[...metadata.appliesTo,{kind:'metric',id:''}]})}>添加适用对象</Button></fieldset>
    <div>预期当前登记版本：{expectedVersion}；{initial ? '创建下一修订，保留历史原件。' : '新原件从0开始，已有原件请从修订详情登记新版。'}</div>
   </>}
   {!receipt && <><label>选择原件文件<input aria-label="选择原件文件" type="file" accept=".txt,.md,.pdf,.docx" disabled={busy || cache.invalid || !!pending && !retryReady} onChange={e => { setFile(e.target.files?.[0] ?? null); setAck(false) }} /></label>
    <Checkbox aria-label="确认上传登记" checked={ack} disabled={busy || cache.invalid || !!pending && !retryReady} onChange={e => setAck(e.target.checked)}>已核对组织、原件身份、适用信息和版本，明确登记此次修订。</Checkbox>
    <Button type="primary" loading={busy} disabled={!file || !ack || cache.invalid || !!pending && !retryReady} onClick={()=>void submit()}>登记原件修订</Button></>}
   {receipt && <><div>修订 {receipt.revision} · 入库任务 {receipt.jobId} · 状态 {receipt.status}</div><Button onClick={()=>{
    try { sessionStorage.removeItem(key); setPending(null); setReceipt(null); setFile(null); setAck(false); setNotice('原请求已核对，可开始下一份登记。') }
    catch { setNotice('无法清除原请求，请保留并核对会话存储。') }
   }}>结束本次登记</Button></>}
  </section>
 </Card>
}
