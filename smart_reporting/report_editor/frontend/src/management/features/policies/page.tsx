import { lazy, Suspense, useState } from 'react'
import { Alert, Button, Card, Input, Select, Space, Table, Tag } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { useSession } from '../../app/session'
import { request, scopeQuery } from '../../api/http'
import { AsyncState, PageHeader } from '../../components/common'
import { useScope } from '../scopes/context'
import { PolicyRetirement } from './retirement'
import { PolicyDefaultBinding } from './default-binding'
const PolicyEditor = lazy(() => import('./editor').then(module => ({ default: module.PolicyEditor })))

const listSchema = z.object({ items: z.array(z.object({ policyId: z.string(), name: z.string(),
  draftVersion: z.number().int().positive().nullable(), publishedRevision: z.number().int().positive().nullable() })), nextCursor: z.string().nullable() })
type Policy = z.infer<typeof listSchema>['items'][number]
export default function Policies() {
  const scope = useScope()
  const { state } = useSession()
  return <>
    <PageHeader title="统计口径" description="核对已发布的计算规则及其影响，明确管理版本的使用范围。" />
    {scope && state.session ? <ScopedPolicies key={JSON.stringify([state.session.username, scope])} scope={scope}
      username={state.session.username} csrf={state.session.csrfToken} /> : <Alert type="info" title="请先在顶栏选择组织。" />}
  </>
}
function ScopedPolicies({ scope, username, csrf }: { scope: { database: string; companyId: string }; username: string; csrf: string }) {
  const [selected, setSelected] = useState<Policy | null>(null)
  const [revision, setRevision] = useState(1)
  const [params, setParams] = useSearchParams()
  const [newId, setNewId] = useState('')
  const editId = params.get('editPolicy')
  const edit = (id: string) => { const next = new URLSearchParams(params); next.set('editPolicy', id); setParams(next) }
  const query = useInfiniteQuery({ queryKey: ['statistical-policies', scope], initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request('/statistical-policies?' + scopeQuery(scope)
      + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), listSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined,
  })
  return <Space orientation="vertical" style={{ width: '100%' }} size="middle">
    <Space wrap><Input aria-label="新口径标识" placeholder="新口径标识，如 monthly_budget" value={newId} onChange={e => setNewId(e.target.value)} />
      <Button disabled={!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(newId)} onClick={() => edit(newId)}>创建口径</Button></Space>
    {editId && <>
      <Button onClick={() => { const next = new URLSearchParams(params); next.delete('editPolicy'); setParams(next) }}>收起口径编辑（保留本地草稿）</Button>
      <Suspense fallback={<Alert type="info" title="正在加载口径编辑器。" />}>
        <PolicyEditor key={JSON.stringify([username, scope, editId])} scope={scope} policyId={editId} username={username} csrf={csrf} />
      </Suspense>
    </>}
    <Card title="口径目录" extra={<Button onClick={() => void query.refetch()} loading={query.isFetching}>刷新目录</Button>}>
      <AsyncState loading={query.isPending} error={query.error} retry={() => void query.refetch()}>
        <Table rowKey="policyId" pagination={false} scroll={{ x: 580, y: 360 }} dataSource={query.data?.pages.flatMap(page => page.items)} columns={[
          { title: '口径名称与标识', render: (_, item: Policy) => <><strong>{item.name}</strong><div>{item.policyId}</div></> },
          { title: '草稿版本', dataIndex: 'draftVersion', render: value => value ?? '无草稿' },
          { title: '最新发布版本', dataIndex: 'publishedRevision', render: value => value ? <Tag>版本 {value}</Tag> : '尚未发布' },
          { title: '操作', render: (_, item: Policy) => <Space wrap><Button disabled={!item.publishedRevision} onClick={() => { setSelected(item); setRevision(item.publishedRevision!) }}>版本与影响</Button><Button onClick={() => edit(item.policyId)}>编辑口径</Button></Space> },
        ]} />
        {query.hasNextPage && <Button onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage}>加载更多口径</Button>}
      </AsyncState>
    </Card>
    {selected?.publishedRevision && <Card title="已发布版本管理">
      <label htmlFor="policy-published-revision">查看发布版本</label>{' '}
      <Select id="policy-published-revision" aria-label="查看发布版本" value={revision} onChange={setRevision}
        options={Array.from({ length: selected.publishedRevision }, (_, i) => ({ value: i + 1, label: '版本 ' + (i + 1) }))} />
      <PolicyRetirement key={JSON.stringify([selected.policyId, revision])} scope={scope} policyId={selected.policyId}
        revision={revision} username={username} csrf={csrf} />
      <PolicyDefaultBinding key={'default:' + JSON.stringify([selected.policyId, revision])} scope={scope} policyId={selected.policyId}
        revision={revision} username={username} csrf={csrf} />
    </Card>}
  </Space>
}
