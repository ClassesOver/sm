import { lazy, Suspense, useState } from 'react'
import { Alert, Button, Card, Input, Select, Space, Table, Tag } from 'antd'
import { useInfiniteQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { z } from 'zod'
import { request, scopeQuery } from '../../api/http'
import { AsyncState, PageHeader } from '../../components/common'
import { useScope } from '../scopes/context'
import { MetricVersionDetails } from './detail'
import { useSession } from '../../app/session'

const MetricEditor = lazy(() => import('./editor').then(module => ({ default: module.MetricEditor })))

const listSchema = z.object({ items: z.array(z.object({ metricId: z.string(), name: z.string(),
  draftVersion: z.number().int().positive().nullable(), publishedRevision: z.number().int().positive().nullable() })), nextCursor: z.string().nullable() })
export default function Metrics() {
  const scope = useScope()
  return <>
    <PageHeader title="业务指标" description="核对精确版本的计算定义，以及依赖它的指标、口径、默认和报告。" />
    {scope ? <ScopedMetrics key={JSON.stringify(scope)} scope={scope} /> : <Alert type="info" title="请先在顶栏选择组织。" />}
  </>
}
function ScopedMetrics({ scope }: { scope: { database: string; companyId: string } }) {
  const { state } = useSession()
  const [params, setParams] = useSearchParams()
  const [newId, setNewId] = useState('')
  const editId = params.get('editMetric')
  const edit = (id: string) => { const next = new URLSearchParams(params); next.set('editMetric', id); setParams(next) }
  const metricId = params.get('metricId'), rawRevision = params.get('revision')
  const revision = rawRevision && /^[1-9]\d*$/.test(rawRevision) && Number.isSafeInteger(Number(rawRevision)) ? Number(rawRevision) : null
  const query = useInfiniteQuery({ queryKey: ['metrics', scope], initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request('/metrics?' + scopeQuery(scope) + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), listSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined,
  })
  const select = (id: string, version: number) => { const next = new URLSearchParams(params); next.set('metricId', id); next.set('revision', String(version)); setParams(next) }
  const selected = query.data?.pages.flatMap(page => page.items).find(item => item.metricId === metricId)
  return <Space orientation="vertical" size="middle" style={{ width: '100%', overflowWrap: 'anywhere' }}>
    <Space wrap>
      <Input aria-label="新指标标识" placeholder="新指标标识，如 budget_amount" value={newId} onChange={e => setNewId(e.target.value)} />
      <Button disabled={!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(newId)} onClick={() => edit(newId)}>创建指标</Button>
    </Space>
    {editId && state.session && <>
      <Button onClick={() => { const next = new URLSearchParams(params); next.delete('editMetric'); setParams(next) }}>收起编辑（保留本地草稿）</Button>
      <Suspense fallback={<Alert type="info" title="正在加载指标编辑器。" />}>
        <MetricEditor key={JSON.stringify([scope, editId, state.session.username])} scope={scope} metricId={editId} username={state.session.username} csrf={state.session.csrfToken} />
      </Suspense>
    </>}
    <Card title="指标目录" extra={<Button onClick={() => void query.refetch()} loading={query.isFetching}>刷新目录</Button>}>
      <AsyncState loading={query.isPending} error={query.error} retry={() => void query.refetch()}>
        <Table rowKey="metricId" pagination={false} scroll={{ x: 550, y: 360 }} dataSource={query.data?.pages.flatMap(page => page.items)} columns={[
          { title: '名称与标识', render: (_, item) => <><strong>{item.name}</strong><div>{item.metricId}</div></> },
          { title: '草稿版本', dataIndex: 'draftVersion', render: value => value ?? '无草稿' },
          { title: '最新发布版本', dataIndex: 'publishedRevision', render: value => value ? <Tag>版本 {value}</Tag> : '尚未发布' },
          { title: '操作', render: (_, item) => <Space wrap><Button disabled={!item.publishedRevision} onClick={() => select(item.metricId, item.publishedRevision!)}>版本与影响</Button><Button onClick={() => edit(item.metricId)}>编辑指标</Button></Space> },
        ]} />
        {query.hasNextPage && <Button onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage}>加载更多指标</Button>}
      </AsyncState>
    </Card>
    {metricId && revision && <Card title="已发布指标版本">
      {selected?.publishedRevision && <><label htmlFor="metric-published-revision">查看发布版本</label>{' '}
        <Select id="metric-published-revision" aria-label="查看发布版本" value={revision} onChange={value => select(metricId, value)}
          options={Array.from({ length: selected.publishedRevision }, (_, index) => ({ value: index + 1, label: '版本 ' + (index + 1) }))} /></>}
      <MetricVersionDetails key={JSON.stringify([metricId, revision])} scope={scope} metricId={metricId} revision={revision} session={state.session ?? undefined} />
    </Card>}
    {metricId && !revision && <Alert type="warning" title="请提供有效的精确发布版本，不会自动改用最新版。" />}
  </Space>
}
