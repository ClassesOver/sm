import { useEffect, useState } from 'react'
import { Alert, Button, Select, Space } from 'antd'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'

const candidatesSchema = z.object({ items: z.array(z.object({ metricId: z.string(), name: z.string(),
  publishedRevision: z.number().int().positive().nullable() })), nextCursor: z.string().nullable() })
const detailSchema = z.object({ published: z.object({ revision: z.number().int().positive(),
  document: z.object({ id: z.string(), name: z.string(), unit: z.string(), grain: z.array(z.string()) }) }),
  retirement: z.object({ reason: z.string() }).nullable() })
type Reference = { metricId: string; revision: number }

export function MetricDependencyPicker({ scope, label, value, disabled, onChange, onAvailabilityChange }: {
  scope: { database: string; companyId: string }; label: string; value: Reference | null; disabled: boolean
  onChange: (value: Reference) => void; onAvailabilityChange: (available: boolean) => void
}) {
  const [open, setOpen] = useState(false)
  const candidates = useInfiniteQuery({ queryKey: ['metric-dependency-candidates', scope], enabled: open,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request('/metrics?' + scopeQuery(scope)
      + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), candidatesSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined,
  })
  const exact = useQuery({ queryKey: ['metric-dependency-version', scope, value?.metricId, value?.revision],
    enabled: !!value?.metricId && !!value.revision,
    queryFn: async ({ signal }) => {
      const result = await request('/metrics/' + encodeURIComponent(value!.metricId) + '?' + scopeQuery(scope)
        + '&revision=' + value!.revision, detailSchema, { signal })
      if (result.published.document.id !== value!.metricId || result.published.revision !== value!.revision) throw Error('依赖指标身份不一致，请保留原选择核对。')
      return result
    },
  })
  const available = !!value?.revision && exact.isSuccess && !exact.isFetching && !exact.data.retirement
  useEffect(() => { onAvailabilityChange(available) }, [available, onAvailabilityChange])
  const items = candidates.data?.pages.flatMap(page => page.items) ?? []
  const selected = items.find(item => item.metricId === value?.metricId)
  const versionCount = selected?.publishedRevision ?? value?.revision ?? 0
  return <section aria-label={label + '依赖指标'} style={{ display: 'grid', gap: 8 }}>
    <strong>{label}：{value?.metricId ? value.metricId + (value.revision ? ' · 版本 ' + value.revision : ' · 请明确选择发布版本') : '尚未选择'}</strong>
    <Button disabled={disabled} onClick={() => setOpen(current => !current)}>{open ? '收起' : '选择'}{label}指标</Button>
    {open && <AsyncState loading={candidates.isPending} error={candidates.error} retry={() => void candidates.refetch()}>
      <Space wrap>{items.filter(item => item.publishedRevision).map(item => <Button key={item.metricId} disabled={disabled}
        onClick={() => onChange({ metricId: item.metricId, revision: item.metricId === value?.metricId ? value.revision : 0 })}>选择{item.name} · {item.metricId}</Button>)}</Space>
      {candidates.hasNextPage && <Button disabled={disabled} loading={candidates.isFetchingNextPage} onClick={() => void candidates.fetchNextPage()}>加载更多候选</Button>}
      {!items.some(item => item.publishedRevision) && <div>当前页暂无已发布指标；可以继续加载候选。</div>}
    </AsyncState>}
    {value?.metricId && <label>{label}发布版本<Select<number> aria-label={label + '发布版本'} disabled={disabled} style={{ width: '100%' }}
      value={value.revision || undefined} placeholder="请明确选择发布版本"
      options={Array.from({ length: versionCount }, (_, index) => ({ value: index + 1, label: '版本 ' + (index + 1) }))}
      onChange={revision => onChange({ metricId: value.metricId, revision })} /></label>}
    {value?.revision ? <AsyncState loading={exact.isPending} error={exact.error} retry={() => void exact.refetch()}>
      {exact.data && <><div>名称：{exact.data.published.document.name}；单位：{exact.data.published.document.unit}；粒度：{exact.data.published.document.grain.join('、')}</div>
        {exact.data.retirement && <Alert type="warning" title={'所选版本已退役：' + exact.data.retirement.reason + '。保留原选择，不自动改用替代版本。'} />}</>}
    </AsyncState> : <div>请明确选择发布版本，不会自动采用最新版本。</div>}
  </section>
}
