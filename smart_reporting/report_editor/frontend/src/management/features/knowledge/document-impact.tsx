import { useState } from 'react'
import { Alert, Button, Space } from 'antd'
import { useInfiniteQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'

const schema = z.object({ documentRevision: z.object({ documentId: z.string(), revision: z.number().int().positive() }),
 items: z.array(z.object({ kind: z.enum(['evidence_release', 'policy', 'default', 'report']), referenceId: z.string(),
  revision: z.number().int().positive().nullable(), name: z.string(), basisId: z.string().nullable(),
  policyVersion: z.object({ policyId: z.string(), revision: z.number().int().positive() }).nullable(),
  evidenceKind: z.enum(['rule_evidence', 'background']).nullable() })), nextCursor: z.string().nullable() })
const labels = { evidence_release: '证据集合', policy: '已发布口径', default: '当前默认配置', report: '历史报告依据' }
export function DocumentImpact({ scope, documentId, revision }: {
 scope: { database: string; companyId: string }; documentId: string; revision: number
}) {
 const [open, setOpen] = useState(false)
 const query = useInfiniteQuery({ queryKey: ['business-document-impact', scope, documentId, revision], enabled: open, retry: false,
  initialPageParam: undefined as string | undefined,
  queryFn: async ({ pageParam, signal }) => {
   const page = await request('/business-documents/' + encodeURIComponent(documentId) + '/revisions/' + revision + '/impact?' + scopeQuery(scope)
    + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), schema, { signal })
   if (page.documentRevision.documentId !== documentId || page.documentRevision.revision !== revision) throw Error('影响结果与所选原件修订不一致，不能使用。')
   return page
  }, getNextPageParam: page => page.nextCursor ?? undefined })
 return <section aria-label="原件撤销影响" style={{ display: 'grid', gap: 8, minWidth: 0 }}>
  <Alert type="warning" title="撤销后，该修订不能再读取或用于知识检索；集合、口径、默认配置和历史报告依据不会自动改写。已生成且身份核验通过的报告仍可下载。" />
  <p>以下仅核对已登记关联，不代表报告实际引用了每份原件。查询失败或未核对时仍可明确提交撤销，请记录理由并安排后续处理。</p>
  <Space wrap><Button onClick={() => setOpen(v => !v)}>{open ? '收起撤销影响' : '核对撤销影响'}</Button>
   {open && <Button loading={query.isFetching} onClick={() => void query.refetch()}>刷新撤销影响</Button>}</Space>
  {open && <AsyncState loading={query.isPending} error={query.error} retry={() => void query.refetch()}>
   <div role="region" aria-label="原件登记关联，可滚动" tabIndex={0} style={{ maxHeight: 300, overflow: 'auto', overflowWrap: 'anywhere' }}>
    {query.data?.pages.flatMap(page => page.items).map(row => <article key={row.kind + ':' + row.referenceId + ':' + row.revision}>
     <p><strong>{labels[row.kind]}</strong> · {row.name} · {row.referenceId}{row.revision !== null && ' · 版本 ' + row.revision}
      {row.evidenceKind && ' · ' + (row.evidenceKind === 'background' ? '背景材料' : '制度依据')}</p>
     {row.policyVersion && <p>口径 {row.policyVersion.policyId} / {row.policyVersion.revision}</p>}
     {row.basisId && <p>依据编号：{row.basisId}</p>}
    </article>)}
   </div>
   {query.data && !query.data.pages.some(page => page.items.length) && <p>未发现登记关联；这不等于原件内容已经获得业务确认。</p>}
   {query.hasNextPage && <><p>仍有关联未加载，当前展示不是全部影响范围。</p><Button loading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>加载更多关联</Button></>}
  </AsyncState>}
 </section>
}
