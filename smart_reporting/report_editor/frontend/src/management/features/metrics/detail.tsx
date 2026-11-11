import { Alert, Button, Descriptions, Table } from 'antd'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'
import { MetricRetirement } from './retirement'

const refSchema = z.object({ metricId: z.string(), revision: z.number().int().positive() })
const policyRefSchema = z.object({ policyId: z.string(), revision: z.number().int().positive() })
const detailSchema = z.object({ published: z.object({ revision: z.number().int().positive(), contentHash: z.string(), document: z.object({
  name: z.string(), kind: z.enum(['sum', 'count', 'count_distinct', 'ratio']), unit: z.string(), grain: z.array(z.string()),
  fieldRef: z.string().nullable().optional(), timeField: z.string().nullable().optional(),
  timeZone: z.string().nullable().optional(), storageTimeZone: z.string().nullable().optional(),
  numeratorVersion: refSchema.nullable().optional(), denominatorVersion: refSchema.nullable().optional(),
  aggregationPolicy: z.object({ observationKind: z.string(), timeAggregation: z.string(), reset: z.string().nullable().optional() }),
}) }), retirement: z.object({ reason: z.string(), replacement: refSchema.nullable() }).nullable() })
const impactSchema = z.object({ metricVersion: refSchema, items: z.array(z.object({ kind: z.enum(['metric', 'policy', 'default', 'report']),
  referenceId: z.string(), name: z.string(), revision: z.number().int().positive().nullable(),
  policyVersion: policyRefSchema.nullable(), basisId: z.string().nullable() })), nextCursor: z.string().nullable() })
const kinds = { sum: '求和', count: '计数', count_distinct: '去重计数', ratio: '比率' }
const referenceKinds = { metric: '派生指标', policy: '统计口径', default: '场景默认', report: '历史报告' }
const versionText = (value: z.infer<typeof refSchema> | null | undefined) => value ? `${value.metricId} · 版本 ${value.revision}` : '未登记'
export function MetricVersionDetails({ scope, metricId, revision, session }: {
  scope: { database: string; companyId: string }; metricId: string; revision: number;
  session?: { username: string; csrfToken: string }
}) {
  const path = '/metrics/' + encodeURIComponent(metricId)
  const query = scopeQuery(scope) + '&revision=' + revision
  const detail = useQuery({ queryKey: ['metric-version', scope, metricId, revision],
    queryFn: ({ signal }) => request(path + '?' + query, detailSchema, { signal }) })
  const impact = useInfiniteQuery({ queryKey: ['metric-impact', scope, metricId, revision], initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) => {
      const result = await request(path + '/impact?' + query + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), impactSchema, { signal })
      if (result.metricVersion.metricId !== metricId || result.metricVersion.revision !== revision) throw Error('影响响应与当前指标版本不一致，请重新读取。')
      return result
    }, getNextPageParam: page => page.nextCursor ?? undefined,
  })
  const document = detail.data?.published.document
  const matches = detail.data?.published.revision === revision
  return <section aria-label="指标版本与影响">
    <AsyncState loading={detail.isPending} error={detail.error} retry={() => void detail.refetch()}>
      {detail.data && !matches && <Alert type="error" title="指标响应与所选发布版本不一致。" />}
      {document && matches && <>
        <h2>{document.name} · 发布版本 {revision}</h2>
        {detail.data?.retirement && <Alert type="warning" title="此版本已退役，不能用于新选用；历史定义保留。" description={<>
          <p>{detail.data.retirement.reason}</p>
          {detail.data.retirement.replacement && <p>替代建议：{versionText(detail.data.retirement.replacement)}。须明确选择，不自动切换。</p>}
        </>} />}
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }} items={[
          { key: 'kind', label: '计算方法', children: kinds[document.kind] },
          { key: 'unit', label: '单位', children: document.unit },
          { key: 'grain', label: '计算粒度', children: document.grain.join('、') },
          ...(document.kind === 'ratio' ? [
            { key: 'numerator', label: '分子指标', children: versionText(document.numeratorVersion) },
            { key: 'denominator', label: '分母指标', children: versionText(document.denominatorVersion) },
          ] : [
            { key: 'field', label: '取数字段', children: document.fieldRef },
            { key: 'time', label: '时间字段', children: document.timeField },
          ]),
          { key: 'observation', label: '数据形态', children: ({ flow: '事件流', cumulative_snapshot: '累计快照', stock_snapshot: '存量快照' } as Record<string, string>)[document.aggregationPolicy.observationKind] ?? document.aggregationPolicy.observationKind },
          { key: 'aggregation', label: '时间聚合', children: ({ sum: '求和', last: '期末值', difference: '差分', none: '不聚合' } as Record<string, string>)[document.aggregationPolicy.timeAggregation] ?? document.aggregationPolicy.timeAggregation },
          { key: 'zone', label: '业务 / 存储时区', children: `${document.timeZone ?? '未登记'} / ${document.storageTimeZone ?? '未登记'}` },
        ]} />
        <details><summary>版本技术详情</summary><p>{metricId} · 版本 {revision}</p><p>内容哈希：{detail.data?.published.contentHash}</p></details>
      </>}
    </AsyncState>
    <h3>此精确版本的影响</h3>
    <p>派生依赖按精确版本逐层核对；历史报告按实际冻结依据读取。影响列表不代表已修改这些引用，也不把已加载条数当作全量总数。</p>
    <AsyncState loading={impact.isPending} error={impact.error} retry={() => void impact.refetch()}>
      <div role="region" aria-label="指标影响明细，可滚动" tabIndex={0} style={{ maxHeight: 360, overflow: 'auto' }}>
      <Table rowKey={item => JSON.stringify([item.kind, item.referenceId, item.revision])} pagination={false} style={{ minWidth: 560 }}
        dataSource={impact.data?.pages.flatMap(page => page.items)} columns={[
          { title: '引用类型', dataIndex: 'kind', render: (kind: keyof typeof referenceKinds) => referenceKinds[kind] },
          { title: '名称与标识', render: (_, item) => <><strong>{item.name}</strong>{item.name !== item.referenceId && <div>{item.referenceId}</div>}</> },
          { title: '精确版本', render: (_, item) => item.revision !== null ? '版本 ' + item.revision
            : item.policyVersion ? `${item.policyVersion.policyId} · 口径版本 ${item.policyVersion.revision}` : '未登记' },
          { title: '登记依据', dataIndex: 'basisId', render: value => value ?? '—' },
        ]} />
      </div>
      {impact.hasNextPage && <Button onClick={() => void impact.fetchNextPage()} loading={impact.isFetchingNextPage}>加载更多影响</Button>}
    </AsyncState>
    {session && detail.data && matches && <MetricRetirement scope={scope} metricId={metricId} revision={revision}
      contentHash={detail.data.published.contentHash} username={session.username} csrf={session.csrfToken}
      impactReady={impact.isSuccess && !impact.isFetching && !impact.hasNextPage} retired={!!detail.data.retirement} />}
  </section>
}
