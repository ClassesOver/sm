import { useState } from 'react'
import { Alert, Button, Space } from 'antd'
import { useInfiniteQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'
const receipt = z.object({ jobId: z.string(), documentId: z.string(), revision: z.number().int().positive(), attempt: z.number().int().nonnegative(),
 status: z.enum(['queued', 'running', 'parsed', 'failed', 'ready', 'needs_transcription']), issueCodes: z.array(z.string()) })
const schema = z.object({ items: z.array(receipt), nextCursor: z.string().nullable() })
const labels = { queued: '排队中', running: '解析中', parsed: '已解析，待发布', failed: '解析失败', ready: '索引就绪', needs_transcription: '需人工转录' }
export function RevisionJobs({ scope, documentId, revision, onOpen }: {
 scope: { database: string; companyId: string }; documentId: string; revision: number; onOpen: (jobId: string) => void
}) {
 const [open, setOpen] = useState(false)
 const query = useInfiniteQuery({ queryKey: ['business-revision-jobs', scope, documentId, revision], enabled: open, retry: false,
 initialPageParam: undefined as string | undefined,
 queryFn: ({ pageParam, signal }) => request('/business-documents/' + encodeURIComponent(documentId) + '/revisions/' + revision + '/ingestion-jobs?' + scopeQuery(scope)
  + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), schema, { signal }), getNextPageParam: page => page.nextCursor ?? undefined })
 return <section aria-label="此修订解析任务" style={{ display: 'grid', gap: 8 }}>
  <Space wrap><Button onClick={() => setOpen(v => !v)}>{open ? '收起此修订解析任务' : '查看此修订解析任务'}</Button>
   {open && <Button loading={query.isFetching} onClick={() => void query.refetch()}>刷新此修订任务</Button>}</Space>
  {open && <><p>只读取此组织、此原件的精确修订任务；不会自动重新解析。重试使用同一任务，尝试次数不代表全部历史尝试明细。</p>
   <AsyncState loading={query.isPending} error={query.error} retry={() => void query.refetch()}>
    <div role="region" aria-label="修订解析任务目录，可滚动" tabIndex={0} style={{ maxHeight: 300, overflow: 'auto', overflowWrap: 'anywhere' }}>
     {query.data?.pages.flatMap(page => page.items).map(job => <article key={job.jobId}>
      {job.documentId !== documentId || job.revision !== revision ? <Alert type="warning" title="任务身份与所选原件修订不一致，不能打开。" /> : <>
       <p>{job.jobId} · 修订 {job.revision} · {labels[job.status]} · 已尝试 {job.attempt} 次</p>
       <Button style={{ maxWidth: '100%', whiteSpace: 'normal', height: 'auto' }} onClick={() => onOpen(job.jobId)}>查看任务 {job.jobId}</Button>
      </>}
     </article>)}
    </div>
    {!query.data?.pages.some(page => page.items.length) && <p>该修订没有可读取的解析任务，未自动创建任务。</p>}
    {query.hasNextPage && <Button loading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>加载更多修订任务</Button>}
   </AsyncState>
  </>}
 </section>
}
