import { useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Input, Select, Space, Tag } from 'antd'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { ApiError, identity, request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'
import { metadataSchema } from './document-upload'
import { BusinessDocumentPreview } from './document-preview'
const kindSchema = z.enum(['rule_evidence', 'background'])
const refSchema = z.object({ documentId: z.string().min(1), revision: z.number().int().positive() })
const selectedSchema = refSchema.extend({ metadata: metadataSchema, originalHash: z.string().regex(/^[a-f0-9]{64}$/) })
const detailSchema = z.object({ documentId: z.string(), revisions: z.array(z.object({ revision: z.number().int().positive(), metadata: metadataSchema,
 originalHash: z.string(), reviewStatus: z.string(), ingestionStatus: z.string() })) })
const optionsSchema = z.object({ items: z.array(z.object({ documentId: z.string(), title: z.string(), revision: z.number().int().positive(), kind: kindSchema, reviewStatus: z.string(), ingestionStatus: z.string() })), nextCursor: z.string().nullable() })
const pendingSchema = z.object({ requestId: z.string().min(1).max(128), kind: kindSchema, documents: z.array(selectedSchema).min(1).max(200) }).refine(input =>
 new Set(input.documents.map(d => JSON.stringify([d.documentId, d.revision]))).size === input.documents.length
 && input.documents.every(d => d.metadata.id === d.documentId && d.metadata.kind === input.kind), '集合成员重复或原件身份、用途不一致')
const releaseSchema = z.object({ releaseId: z.string(), requestId: z.string(), kind: kindSchema,
 documents: z.array(z.object({ reference: refSchema, metadata: metadataSchema })).min(1).max(200) })
const catalogSchema = z.object({ items: z.array(z.object({ releaseId: z.string(), kind: kindSchema, publishedAt: z.string(), availableForSelection: z.boolean(),
 documents: z.array(z.object({ documentId: z.string(), revision: z.number().int().positive(), title: z.string(), reviewStatus: z.string(), ingestionStatus: z.string() })) })), nextCursor: z.string().nullable() })
const memberKey = (ref: z.infer<typeof refSchema>) => JSON.stringify([ref.documentId, ref.revision])
const sameMetadata = (a: z.infer<typeof metadataSchema>, b: z.infer<typeof metadataSchema>) => JSON.stringify(a) === JSON.stringify(b)
const available = (v: z.infer<typeof detailSchema>['revisions'][number]) => v.reviewStatus === 'approved' && ['parsed', 'ready'].includes(v.ingestionStatus)
export function EvidenceReleaseManager({ scope, username, csrf }: { scope: { database: string; companyId: string }; username: string; csrf: string }) {
 const client = useQueryClient(), running = useRef(false), previewTrigger = useRef<HTMLElement | null>(null)
 const key = 'management-evidence-publication:' + JSON.stringify([username, scope.database, scope.companyId])
 const [cache] = useState(() => { try { const raw = sessionStorage.getItem(key); return { value: raw ? pendingSchema.parse(JSON.parse(raw)) : null, invalid: false } } catch { return { value: null, invalid: true } } })
 const [pending, setPending] = useState(cache.value), [kind, setKind] = useState<z.infer<typeof kindSchema>>(cache.value?.kind ?? 'rule_evidence')
 const [selected, setSelected] = useState<z.infer<typeof selectedSchema>[]>(cache.value?.documents ?? [])
 const [picking, setPicking] = useState(false), [search, setSearch] = useState(''), [query, setQuery] = useState('')
 const [detail, setDetail] = useState<z.infer<typeof detailSchema> | null>(null), [busy, setBusy] = useState(false), [ack, setAck] = useState(false)
 const [notice, setNotice] = useState(''), [retryReady, setRetryReady] = useState(false), [published, setPublished] = useState<z.infer<typeof releaseSchema> | null>(null)
 const [preview, setPreview] = useState<z.infer<typeof refSchema> | null>(null)
 const blocked = busy || cache.invalid || !!pending || !!published
 const options = useInfiniteQuery({ queryKey: ['evidence-publication-options', scope, kind, query], enabled: picking,
 initialPageParam: undefined as string | undefined,
 queryFn: ({ pageParam, signal }) => request('/business-documents?' + scopeQuery(scope) + '&kind=' + kind + '&q=' + encodeURIComponent(query)
  + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), optionsSchema, { signal }), getNextPageParam: p => p.nextCursor ?? undefined })
 const catalog = useInfiniteQuery({ queryKey: ['evidence-release-management', scope, kind], initialPageParam: undefined as string | undefined,
 queryFn: ({ pageParam, signal }) => request('/business-evidence-releases/catalog?' + scopeQuery(scope) + '&kind=' + kind
  + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), catalogSchema, { signal }), getNextPageParam: p => p.nextCursor ?? undefined })
 const read = async (documentId: string) => {
  if (running.current) return
  running.current = true; setBusy(true); setDetail(null); setNotice('')
  try { const value = await request('/business-documents/' + encodeURIComponent(documentId) + '?' + scopeQuery(scope), detailSchema)
   if (value.documentId !== documentId) throw Error('原件身份与候选不一致'); setDetail(value)
  } catch (error) { setNotice((error as Error).message) } finally { running.current = false; setBusy(false) }
 }
 const verify = async (input: z.infer<typeof pendingSchema>) => {
  for (const member of input.documents) {
   const document = await request('/business-documents/' + encodeURIComponent(member.documentId) + '?' + scopeQuery(scope), detailSchema)
   const current = document.documentId === member.documentId ? document.revisions.find(r => r.revision === member.revision) : undefined
   if (!current || !available(current) || current.metadata.kind !== input.kind || current.originalHash !== member.originalHash || !sameMetadata(current.metadata, member.metadata))
    throw Error('所选原件修订已不可发布或身份变化，请保留选择并重新核对。')
  }
 }
 const accept = (result: z.infer<typeof releaseSchema>, input: z.infer<typeof pendingSchema>, recovered: boolean) => {
  const members = new Map(input.documents.map(d => [memberKey(d), d]))
  if (result.requestId !== input.requestId || result.kind !== input.kind || result.documents.length !== members.size
   || new Set(result.documents.map(d => memberKey(d.reference))).size !== members.size
   || result.documents.some(d => !members.has(memberKey(d.reference)) || !sameMetadata(members.get(memberKey(d.reference))!.metadata, d.metadata)))
   throw Error('集合身份或用途与原请求不一致，请保留原请求核对。')
  setPublished(result); setRetryReady(false); setNotice(recovered ? '原请求集合已发布；当前审核可用性需另行刷新核对。' : '集合已发布；当前审核可用性需另行刷新核对。')
  void client.invalidateQueries({ queryKey: ['evidence-release-management'] }); void client.invalidateQueries({ queryKey: ['policy-evidence-catalog'] })
  void client.invalidateQueries({ queryKey: ['business-document-detail'] }); void client.invalidateQueries({ queryKey: ['business-documents'] })
 }
 const submit = async () => {
  if (running.current || !ack || cache.invalid || published || !selected.length || pending && !retryReady) return
  running.current = true; setBusy(true); setNotice('')
  try {
   const input = pending ?? pendingSchema.parse({ requestId: crypto.randomUUID(), kind, documents: selected })
   await verify(input)
   try { sessionStorage.setItem(key, JSON.stringify(input)) } catch { throw Error('无法保存原集合发布请求，未提交。') }
   setPending(input); setRetryReady(false); setAck(false)
   try { accept(await request('/business-evidence-releases', releaseSchema, { method: 'POST', csrf,
    body: { ...identity(scope), requestId: input.requestId, kind: input.kind, revisionIds: input.documents.map(d => ({ documentId: d.documentId, revision: d.revision })) } }), input, false) }
   catch (error) { setNotice('集合发布结果待确认：' + (error as Error).message + ' 请读取原集合发布结果，不自动重发。') }
  } catch (error) { setNotice((error as Error).message); setAck(false) }
  finally { running.current = false; setBusy(false) }
 }
 const recover = async () => {
  if (!pending || running.current) return
  running.current = true; setBusy(true); setAck(false); setRetryReady(false)
  try { const result = await request('/business-evidence-releases?' + scopeQuery(scope) + '&requestId=' + encodeURIComponent(pending.requestId), releaseSchema); accept(result, pending, true) }
  catch (error) {
   if (error instanceof ApiError && error.status === 404 && error.code === 'management_evidence_not_found') {
    try { await verify(pending); setRetryReady(true); setNotice('尚未找到原请求集合，所选修订已重新核对；再次确认后可显式重提原请求。') }
    catch (verifyError) { setNotice((verifyError as Error).message) }
   } else setNotice((error as Error).message)
  } finally { running.current = false; setBusy(false) }
 }
 return <Card title="证据集合发布与目录">
  <section aria-label="证据集合发布" style={{ display: 'grid', gap: 12, overflowWrap: 'anywhere' }}>
   <p>制度依据用于计算口径，背景材料用于解释支持；必须分别发布。不会自动调整口径、默认或历史报告。</p>
   <label>集合用途<Select aria-label="集合用途" style={{ width: '100%' }} value={kind} disabled={blocked || selected.length > 0} onChange={v => { setKind(v); setDetail(null); setAck(false) }}
    options={[{ value: 'rule_evidence', label: '制度依据' }, { value: 'background', label: '背景材料' }]} /></label>
   {cache.invalid && <Alert type="error" title="原集合发布缓存损坏，禁止写入，请保留核对。" />}
   {notice && <Alert type="info" title={notice} />}
   {pending && <><div>原请求 {pending.requestId} · {pending.documents.length} 份精确修订</div><Button disabled={busy || cache.invalid} onClick={() => void recover()}>读取原集合发布结果</Button></>}
   <Button disabled={blocked} onClick={() => setPicking(v => !v)}>{picking ? '收起集合原件' : '选择集合原件'}</Button>
   {picking && <>
    <Space wrap><Input aria-label="搜索集合候选原件" value={search} maxLength={200} disabled={blocked} onChange={e => setSearch(e.target.value)} onPressEnter={() => { setQuery(search); setDetail(null) }} />
     <Button disabled={blocked} onClick={() => { setQuery(search); setDetail(null) }}>搜索候选原件</Button><Button disabled={blocked} loading={options.isFetching} onClick={() => void options.refetch()}>刷新候选原件</Button></Space>
    <AsyncState loading={options.isPending} error={options.error} retry={() => void options.refetch()}>
     <div role="region" aria-label="集合原件候选，可滚动" tabIndex={0} style={{ maxHeight: 300, overflow: 'auto' }}>
      {options.data?.pages.flatMap(p => p.items).map(d => <div key={d.documentId}><strong>{d.title}</strong> · {d.documentId} · 最新修订 {d.revision}
       <Button disabled={blocked} onClick={() => void read(d.documentId)}>读取修订 {d.documentId}</Button></div>)}
     </div>
     {options.hasNextPage && <Button disabled={blocked} loading={options.isFetchingNextPage} onClick={() => void options.fetchNextPage()}>加载更多候选原件</Button>}
    </AsyncState>
    {detail && <div role="region" aria-label="明确选择原件修订" tabIndex={0} style={{ maxHeight: 300, overflow: 'auto' }}>
     {detail.revisions.map(r => <article key={r.revision} style={{ paddingBlock: 8 }}><strong>{r.metadata.title}</strong> · {detail.documentId} · 修订 {r.revision} · {r.reviewStatus === 'approved' ? '已审核' : '未通过审核'}
      <div>{available(r) ? '解析可用于发布预检' : '不可发布'} · 适用期 {r.metadata.validFrom ?? '未登记'} 至 {r.metadata.validTo ?? '未登记'}（结束不含）</div>
      <Space wrap><Button disabled={blocked || !available(r) || r.metadata.kind !== kind || selected.length >= 200 || selected.some(d => d.documentId === detail.documentId && d.revision === r.revision)} onClick={() => {
       setSelected(v => [...v, { documentId: detail.documentId, revision: r.revision, originalHash: r.originalHash, metadata: r.metadata }]); setAck(false)
      }}>加入 {detail.documentId} 修订 {r.revision}</Button>
      <Button disabled={busy} onClick={e => { previewTrigger.current = e.currentTarget; setPreview({ documentId: detail.documentId, revision: r.revision }) }}>预览集合原件 {detail.documentId} 修订 {r.revision}</Button></Space>
     </article>)}
    </div>}
   </>}
   <div>已选 {selected.length} 份精确修订，最多200份。搜索和分页不会清空所选修订。</div>
   <div role="region" aria-label="已选集合原件" tabIndex={0} style={{ maxHeight: 300, overflow: 'auto' }}>{selected.map(d => <div key={memberKey(d)}>{d.metadata.title} · {d.documentId} · 修订 {d.revision}
    <Button disabled={blocked} onClick={() => { setSelected(v => v.filter(row => memberKey(row) !== memberKey(d))); setAck(false) }}>移除 {d.documentId} 修订 {d.revision}</Button></div>)}</div>
   <Checkbox aria-label="确认发布证据集合" checked={ack} disabled={busy || cache.invalid || !!published || !selected.length || !!pending && !retryReady} onChange={e => setAck(e.target.checked)}>已核对用途、精确修订、适用期及原文，明确发布本集合。</Checkbox>
   <Button type="primary" disabled={!ack || busy || cache.invalid || !!published || !selected.length || !!pending && !retryReady} loading={busy} onClick={() => void submit()}>发布证据集合</Button>
   {published && <><div>已发布集合 {published.releaseId} · {published.documents.length} 份修订</div><Button onClick={() => {
    try { sessionStorage.removeItem(key); setPending(null); setPublished(null); setSelected([]); setDetail(null); setAck(false); setNotice('本次发布已核对，可明确选择下一集合。') }
    catch { setNotice('无法清除原请求，请保留核对。') }
   }}>结束本次集合发布</Button></>}
   <h3>当前用途的已发布集合</h3><Button loading={catalog.isFetching} onClick={() => void catalog.refetch()}>刷新已发布集合</Button>
   <AsyncState loading={catalog.isPending} error={catalog.error} retry={() => void catalog.refetch()}>
    <div role="region" aria-label="已发布集合目录，可滚动" tabIndex={0} style={{ maxHeight: 320, overflow: 'auto' }}>{catalog.data?.pages.flatMap(p => p.items).map(item => <article key={item.releaseId} style={{ paddingBlock: 8 }}>
     <strong>{item.documents.map(d => d.title).join('、')}</strong><div>{item.releaseId} · {item.publishedAt}</div><Tag>{item.availableForSelection ? '当前登记可供选择' : '当前包含不可用修订'}</Tag>
     {item.documents.map(d => <div key={memberKey(d)}>{d.documentId} · 修订 {d.revision}</div>)}
    </article>)}</div>
    {!catalog.data?.pages.some(p => p.items.length) && <p>当前用途暂无已发布集合。</p>}
    {catalog.hasNextPage && <Button loading={catalog.isFetchingNextPage} onClick={() => void catalog.fetchNextPage()}>加载更多已发布集合</Button>}
   </AsyncState>
   {preview && <BusinessDocumentPreview key={memberKey(preview)} scope={scope} {...preview} reviewMode onClose={() => { setPreview(null); requestAnimationFrame(() => previewTrigger.current?.focus()) }} />}
  </section>
 </Card>
}
