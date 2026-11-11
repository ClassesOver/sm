import { useRef, useState } from 'react'
import { Alert, Button, Input, Space, Tag } from 'antd'
import { useInfiniteQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'
import { BusinessDocumentPreview } from '../knowledge/document-preview'

const itemSchema = z.object({ releaseId: z.string(), kind: z.enum(['rule_evidence', 'background']), publishedAt: z.string(),
  availableForSelection: z.boolean(), documents: z.array(z.object({ documentId: z.string(), revision: z.number().int().positive(),
    title: z.string(), reviewStatus: z.string(), ingestionStatus: z.string() })) })
const catalogSchema = z.object({ items: z.array(itemSchema), nextCursor: z.string().nullable() })
const releaseSchema = z.object({ releaseId: z.string(), kind: z.enum(['rule_evidence', 'background']),
  documents: z.array(z.object({ reference: z.object({ documentId: z.string(), revision: z.number().int().positive() }), metadata: z.object({ title: z.string() }) })) })
const memberKey = (id: string, revision: number) => JSON.stringify([id, revision])

export function PolicyEvidencePicker({ scope, value, disabled, onChange, kind = 'rule_evidence' }: {
  scope: { database: string; companyId: string }; value: string; kind?: 'rule_evidence' | 'background'; disabled: boolean; onChange: (releaseId: string) => void
}) {
  const label = kind === 'background' ? '背景材料' : '制度依据'
  const [open, setOpen] = useState(false), [search, setSearch] = useState(''), [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState('')
  const [preview, setPreview] = useState<{ documentId: string; revision: number } | null>(null)
  const previewTrigger = useRef<HTMLElement | null>(null)
  const base = '/business-evidence-releases/catalog?' + scopeQuery(scope) + '&kind=' + kind
  const catalog = useInfiniteQuery({ queryKey: ['policy-evidence-catalog', scope, kind, query], enabled: open,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request(base + '&q=' + encodeURIComponent(query)
      + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), catalogSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined,
  })
  const select = async (item: z.infer<typeof itemSchema>) => {
    setBusy(true); setNotice('')
    try {
      const current = await request(base + '&q=' + encodeURIComponent(item.releaseId), catalogSchema)
      const candidate = current.items.find(row => row.releaseId === item.releaseId)
      if (!candidate || candidate.kind !== kind || !candidate.availableForSelection) throw Error('所选集合的当前审核状态已不可用，请刷新核对，原选择保留。')
      const result = await request('/business-evidence-releases/' + encodeURIComponent(item.releaseId) + '?' + scopeQuery(scope), releaseSchema)
      const members = new Map(candidate.documents.map(d => [memberKey(d.documentId, d.revision), d.title]))
      if (result.releaseId !== item.releaseId || result.kind !== kind || result.documents.length !== members.size
        || new Set(result.documents.map(d => memberKey(d.reference.documentId, d.reference.revision))).size !== members.size
        || result.documents.some(d => members.get(memberKey(d.reference.documentId, d.reference.revision)) !== d.metadata.title))
        throw Error('集合身份或用途与所选' + label + '不一致，请保留原选择核对。')
      onChange(result.releaseId); setNotice(kind === 'background' ? '已选择明确的背景材料集合；调整默认仍需核对确认，不改变计算公式。' : '已选择明确的制度依据集合；保存与发布仍需分别确认。')
    } catch (error) { setNotice((error as Error).message) }
    finally { setBusy(false) }
  }
  return <section aria-label={label + '集合选择'} style={{ display: 'grid', gap: 8 }}>
    <Button disabled={disabled || busy} onClick={() => setOpen(current => !current)}>{open ? '收起已发布' + label + '目录' : '从已发布' + label + '中选择'}</Button>
    {notice && <Alert type="info" title={notice} />}
    {open && <>
      <Space wrap><Input aria-label={'搜索' + label + '集合'} placeholder="文档标题、标识或集合标识" maxLength={200} disabled={disabled || busy} value={search} onChange={e => setSearch(e.target.value)}
        onPressEnter={() => setQuery(search)} /><Button disabled={disabled || busy} onClick={() => setQuery(search)}>搜索集合</Button>
        <Button disabled={disabled || busy} loading={catalog.isFetching} onClick={() => void catalog.refetch()}>刷新集合目录</Button></Space>
      <div>仅列出本组织已发布的{label}；审核状态是本次读取结果，不代表原件或业务正确性已复核。</div>
      <AsyncState loading={catalog.isPending} error={catalog.error} retry={() => void catalog.refetch()}>
        <div role="region" aria-label={label + '集合目录，可滚动'} tabIndex={0} style={{ display: 'grid', gap: 12, maxHeight: 420, overflow: 'auto' }}>
          {catalog.data?.pages.flatMap(page => page.items).map(item => <article key={item.releaseId} style={{ padding: 12, border: '1px solid #d9dfe8', borderRadius: 6, overflowWrap: 'anywhere' }}>
            <strong>{item.documents.map(d => d.title).join('、')}</strong>
            <div>集合：{item.releaseId} {value === item.releaseId && <Tag>当前选择</Tag>}</div>
            <div>发布于 {item.publishedAt}</div>
            {item.documents.map(d => <div key={memberKey(d.documentId, d.revision)}>{d.title} · {d.documentId} · 修订 {d.revision} · {d.reviewStatus === 'approved' ? '已审核' : d.reviewStatus === 'revoked' ? '已撤销' : '审核状态不可用'}
              <Button style={{ maxWidth: '100%', whiteSpace: 'normal', height: 'auto' }} disabled={disabled || busy} onClick={event => { previewTrigger.current = event.currentTarget; setPreview({ documentId: d.documentId, revision: d.revision }) }}>预览原文 {d.title} 修订 {d.revision}</Button>
            </div>)}
            {!item.availableForSelection && <Alert type="warning" title={'包含已撤销或未就绪修订，不能作为新' + (kind === 'background' ? '报告背景' : '口径依据') + '。'} />}
            <Button style={{ maxWidth: '100%', whiteSpace: 'normal', height: 'auto' }} disabled={disabled || busy || !item.availableForSelection || item.kind !== kind} onClick={() => void select(item)}>选择集合 {item.releaseId}</Button>
          </article>)}
        </div>
        {!catalog.data?.pages.some(page => page.items.length) && <div>没有匹配的已发布{label}集合。</div>}
        {catalog.hasNextPage && <Button disabled={disabled || busy} loading={catalog.isFetchingNextPage} onClick={() => void catalog.fetchNextPage()}>加载更多集合</Button>}
      </AsyncState>
    </>}
    {preview && <BusinessDocumentPreview key={JSON.stringify([scope, preview])} scope={scope} {...preview} kind={kind} onClose={() => { setPreview(null); requestAnimationFrame(() => previewTrigger.current?.focus()) }} />}
  </section>
}
