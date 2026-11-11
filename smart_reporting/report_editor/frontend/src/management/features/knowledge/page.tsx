import { useRef, useState } from 'react'
import { Alert, Button, Card, Descriptions, Input, Select, Space, Table, Tag } from 'antd'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { z } from 'zod'
import { request, scopeQuery } from '../../api/http'
import { useSession } from '../../app/session'
import { AsyncState, PageHeader } from '../../components/common'
import { useScope } from '../scopes/context'
import { BusinessDocumentPreview } from './document-preview'
import { DocumentReview } from './document-review'
import { DocumentUpload, type UploadTarget } from './document-upload'
import { IngestionTask } from './ingestion-task'
import { RevisionJobs } from './revision-jobs'
import { EvidenceReleaseManager } from './evidence-release'
const itemSchema = z.object({ documentId: z.string(), title: z.string(), version: z.number().int().positive(), revision: z.number().int().positive(),
 kind: z.enum(['rule_evidence', 'background']), recordedAt: z.string(), reviewStatus: z.string(), ingestionStatus: z.string() })
const listSchema = z.object({ items: z.array(itemSchema), nextCursor: z.string().nullable() })
const detailSchema = z.object({ documentId: z.string(), version: z.number().int().positive(), revisions: z.array(z.object({
 revision: z.number().int().positive(), stateVersion: z.number().int().positive(), originalHash: z.string(), reviewStatus: z.string(), ingestionStatus: z.string(),
 reviewReceipt: z.object({ decision: z.string(), reason: z.string() }).nullable(), mediaType: z.string(), sizeBytes: z.number(), recordedAt: z.string(),
 metadata: z.object({ title: z.string(), kind: z.string(), validFrom: z.string().nullable(), validTo: z.string().nullable(), eventTime: z.string().nullable(),
 appliesTo: z.array(z.object({ kind: z.string(), id: z.string() })) }),
 })) })
const reviews: Record<string, string> = { pending: '待审核', approved: '已批准', rejected: '已拒绝', revoked: '已撤销' }
const ingestion: Record<string, string> = { queued: '排队中', running: '解析中', parsed: '已解析，待发布', failed: '解析失败', ready: '索引就绪', needs_transcription: '需人工转录' }
export default function Knowledge() {
 const scope = useScope(), { state } = useSession()
 return <><PageHeader title="业务知识" description="登记并核对制度和背景原件，审核修订后再明确发布依据集合。" />
 {scope && state.session ? <ScopedKnowledge key={JSON.stringify([state.session.username, scope])} scope={scope} username={state.session.username} csrf={state.session.csrfToken} />
 : <Alert type="info" title="请先在顶栏选择组织。" />}</>
}
function ScopedKnowledge({ scope, username, csrf }: { scope: { database: string; companyId: string }; username: string; csrf: string }) {
 const [params, setParams] = useSearchParams(), [search, setSearch] = useState(''), [query, setQuery] = useState('')
 const [kind, setKind] = useState(''), [review, setReview] = useState('')
 const [uploadTarget, setUploadTarget] = useState<UploadTarget | undefined>()
 const documentId = params.get('document'), revisionText = params.get('revision')
 const revision = revisionText && /^[1-9][0-9]*$/.test(revisionText) && Number.isSafeInteger(Number(revisionText)) ? Number(revisionText) : null
 const catalog = useInfiniteQuery({ queryKey: ['business-documents', scope, query, kind, review], initialPageParam: undefined as string | undefined,
 queryFn: ({ pageParam, signal }) => request('/business-documents?' + scopeQuery(scope) + '&q=' + encodeURIComponent(query)
  + (kind ? '&kind=' + kind : '') + (review ? '&reviewStatus=' + review : '') + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), listSchema, { signal }),
 getNextPageParam: page => page.nextCursor ?? undefined })
 const open = (id: string, version: number) => { const next = new URLSearchParams(params); next.set('document', id); next.set('revision', String(version)); next.delete('job'); setParams(next) }
 return <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
  <DocumentUpload key={JSON.stringify(uploadTarget ?? 'new')} scope={scope} username={username} csrf={csrf} initial={uploadTarget} onUploaded={receipt => {
   const next = new URLSearchParams(params); next.set('document', receipt.documentId); next.set('revision', String(receipt.revision)); next.set('job', receipt.jobId); setParams(next)
  }} />
  {params.get('job') && <IngestionTask key={JSON.stringify([params.get('job'), documentId, revision])} scope={scope} jobId={params.get('job')!} documentId={documentId} revision={revision} username={username} csrf={csrf} />}
  <EvidenceReleaseManager scope={scope} username={username} csrf={csrf} />
  <Card title="原件目录">
   <Space wrap><Input aria-label="搜索业务原件" value={search} maxLength={200} placeholder="标题或原件标识" onChange={e => setSearch(e.target.value)} onPressEnter={() => setQuery(search)} />
    <Button onClick={() => setQuery(search)}>搜索原件</Button>
    <Select aria-label="原件用途" value={kind} style={{ width: 150 }} onChange={setKind} options={[{ value: '', label: '全部用途' }, { value: 'rule_evidence', label: '制度依据' }, { value: 'background', label: '背景材料' }]} />
    <Select aria-label="原件审核状态" value={review} style={{ width: 150 }} onChange={setReview} options={[{ value: '', label: '全部审核状态' }, ...Object.entries(reviews).map(([value, label]) => ({ value, label }))]} />
    <Button loading={catalog.isFetching} onClick={() => void catalog.refetch()}>刷新原件目录</Button></Space>
   <p>列表显示每份原件的最新登记修订及当前状态；已解析、已审核与已发布分别核对，不以已加载数量表示全部原件数。</p>
   <AsyncState loading={catalog.isPending} error={catalog.error} retry={() => void catalog.refetch()}>
    <div role="region" aria-label="业务原件目录，可滚动" tabIndex={0} style={{ overflow: 'auto', maxHeight: 400 }}>
    <Table rowKey="documentId" pagination={false} style={{ minWidth: 650 }} dataSource={catalog.data?.pages.flatMap(p => p.items)} columns={[
     { title: '原件名称与标识', render: (_, item) => <><strong>{item.title}</strong><div>{item.documentId}</div></> },
     { title: '用途', render: (_, item) => item.kind === 'rule_evidence' ? '制度依据' : '背景材料' },
     { title: '最新修订', dataIndex: 'revision' },
     { title: '状态', render: (_, item) => <><Tag>{reviews[item.reviewStatus] ?? item.reviewStatus}</Tag><div>{ingestion[item.ingestionStatus] ?? item.ingestionStatus}</div></> },
     { title: '操作', render: (_, item) => <Button onClick={() => open(item.documentId, item.revision)}>查看原件 {item.documentId}</Button> },
    ]} /></div>
    {catalog.hasNextPage && <Button loading={catalog.isFetchingNextPage} onClick={() => void catalog.fetchNextPage()}>加载更多原件</Button>}
   </AsyncState>
  </Card>
  {documentId && (revision ? <DocumentDetails key={JSON.stringify([documentId, revision])} scope={scope} documentId={documentId} revision={revision} username={username} csrf={csrf} onRevision={value => open(documentId, value)} onNewRevision={setUploadTarget} onTask={jobId => { const next = new URLSearchParams(params); next.set('job', jobId); setParams(next) }} />
   : <Alert type="warning" title="请明确选择有效原件修订，不自动回退最新版本。" />)}
 </Space>
}
function DocumentDetails({ scope, documentId, revision, username, csrf, onRevision, onNewRevision, onTask }: { scope: { database: string; companyId: string }; documentId: string; revision: number; username: string; csrf: string; onRevision: (revision: number) => void; onNewRevision: (target: UploadTarget) => void; onTask: (jobId: string) => void }) {
 const [preview, setPreview] = useState(false), trigger = useRef<HTMLElement | null>(null)
 const detail = useQuery({ queryKey: ['business-document-detail', scope, documentId], queryFn: ({ signal }) => request('/business-documents/' + encodeURIComponent(documentId) + '?' + scopeQuery(scope), detailSchema, { signal }) })
 const target = detail.data?.documentId === documentId ? detail.data.revisions.find(r => r.revision === revision) : undefined
 return <Card title="原件修订详情" extra={<Button loading={detail.isFetching} onClick={() => void detail.refetch()}>刷新原件状态</Button>}>
  <AsyncState loading={detail.isPending} error={detail.error} retry={() => void detail.refetch()}>
   {detail.data && !target && <Alert type="warning" title="所选原件身份或精确修订不存在。" />}
   {target && <section aria-label="原件修订详情" style={{ display: 'grid', gap: 12, overflowWrap: 'anywhere' }}>
    <label>查看原件修订<Select aria-label="查看原件修订" value={revision} onChange={onRevision} style={{ width: '100%' }} options={detail.data!.revisions.map(r => ({ value: r.revision, label: '修订 ' + r.revision }))} /></label>
    <RevisionJobs key={'jobs:' + JSON.stringify([scope, documentId, revision])} scope={scope} documentId={documentId} revision={revision} onOpen={onTask} />
    <h2>{target.metadata.title} · 修订 {revision}</h2>
    <Descriptions size="small" column={{ xs: 1, sm: 2 }} items={[
     { key: 'kind', label: '用途', children: target.metadata.kind === 'rule_evidence' ? '制度依据' : '背景材料' },
     { key: 'review', label: '审核', children: reviews[target.reviewStatus] ?? target.reviewStatus },
     { key: 'ingestion', label: '入库', children: ingestion[target.ingestionStatus] ?? target.ingestionStatus },
     { key: 'period', label: '适用期', children: (target.metadata.validFrom ?? '未登记') + ' 至 ' + (target.metadata.validTo ?? '未登记') + '（结束不含）' },
     { key: 'event', label: '事件时间', children: target.metadata.eventTime ?? '未登记，不推断事件归因' },
     { key: 'recorded', label: '登记时间', children: target.recordedAt },
     { key: 'applies', label: '适用对象', children: target.metadata.appliesTo.map(r => r.kind + ':' + r.id).join('、') || '未登记' },
    ]} />
    {target.reviewReceipt && <Alert type="info" title={'当前审核理由：' + target.reviewReceipt.reason} />}
    <Button onClick={() => onNewRevision({ expectedVersion: detail.data!.version, metadata: { ...target.metadata, id: documentId, kind: target.metadata.kind as 'rule_evidence' | 'background', appliesTo: target.metadata.appliesTo as UploadTarget['metadata']['appliesTo'] } })}>登记此原件新修订</Button>
    <Space wrap><Button disabled={target.reviewStatus === 'revoked'} onClick={e => { trigger.current = e.currentTarget; setPreview(true) }}>预览待核对原文</Button>
     {target.reviewStatus !== 'revoked' && <Button href={'/management/api/v1/business-documents/' + encodeURIComponent(documentId) + '/revisions/' + revision + '/original?' + scopeQuery(scope)}>下载此修订原件</Button>}</Space>
    <details><summary>原件技术身份</summary><p>内容哈希：{target.originalHash}</p><p>{target.mediaType} · {target.sizeBytes} 字节 · 状态版本 {target.stateVersion}</p></details>
    <DocumentReview key={JSON.stringify([scope, documentId, revision])} scope={scope} documentId={documentId} target={target} username={username} csrf={csrf} />
    {preview && <BusinessDocumentPreview scope={scope} documentId={documentId} revision={revision} reviewMode onClose={() => { setPreview(false); requestAnimationFrame(() => trigger.current?.focus()) }} />}
   </section>}
  </AsyncState>
 </Card>
}
