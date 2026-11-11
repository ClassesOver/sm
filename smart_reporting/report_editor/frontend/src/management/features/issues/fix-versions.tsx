import { useState } from 'react'
import { Alert, Button, Checkbox, Input, Radio, Space, Tag } from 'antd'
import { useInfiniteQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'

export const assetNames = { metric: '指标', statistical_policy: '统计口径', document: '原件修订', evidence_release: '证据集合' }
export const correctedVersionSchema = z.object({ assetType: z.enum(['metric', 'statistical_policy', 'document', 'evidence_release']),
  assetId: z.string(), revision: z.number().int().positive().nullable() })
type Reference = z.infer<typeof correctedVersionSchema>
const optionsSchema = z.object({ items: z.array(z.object({ reference: correctedVersionSchema, name: z.string(),
  available: z.boolean(), reason: z.string() })), nextCursor: z.string().nullable() })
const referenceKey = (ref: Reference) => JSON.stringify(ref)

export function FixVersions({ scope, issueId, value = [], onChange }: {
  scope: { database: string; companyId: string }; issueId: string; value?: Reference[]; onChange?: (value: Reference[]) => void
}) {
  const [type, setType] = useState<Reference['assetType']>('metric')
  const [search, setSearch] = useState('')
  const [notice, setNotice] = useState('')
  const query = useInfiniteQuery({ queryKey: ['issue-fix-options', scope, issueId, type, search],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request('/report-issue-reviews/' + encodeURIComponent(issueId)
      + '/fix-options?' + scopeQuery(scope) + '&assetType=' + type + '&q=' + encodeURIComponent(search)
      + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), optionsSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined,
  })
  const change = (ref: Reference, selected: boolean) => {
    const others = value.filter(item => item.assetType !== ref.assetType || item.assetId !== ref.assetId)
    if (selected && others.length >= 50) { setNotice('最多关联50个正式修复对象。'); return }
    setNotice(''); onChange?.(selected ? [...others, ref] : others)
  }
  return <div className="issue-fix-versions">
    <p>可先登记候选改动，正式发布后再关联修复版本。关联仍待回归核验，不改写原报告。</p>
    <Space wrap>{value.map(ref => <Tag key={referenceKey(ref)} closable onClose={() => change(ref, false)}>
      {assetNames[ref.assetType]} · {ref.assetId}{ref.revision === null ? '' : ` · 修订 ${ref.revision}`}
    </Tag>)}</Space>
    <p>已选 {value.length} 个正式修复对象；搜索与翻页保留选择，同一对象只保留一个版本。</p>
    <Radio.Group aria-label="修复对象类型" value={type} onChange={event => setType(event.target.value)}
      options={Object.entries(assetNames).map(([value, label]) => ({ value, label }))} />
    <Input.Search aria-label="搜索正式修复版本" placeholder="按名称或标识搜索" maxLength={128} allowClear
      enterButton="搜索版本" onSearch={setSearch} onPressEnter={event => event.preventDefault()} />
    {notice && <Alert type="warning" title={notice} />}
    <AsyncState loading={query.isPending} error={query.error} retry={() => void query.refetch()}>
      {query.data?.pages.flatMap(page => page.items).map(option => {
        const checked = value.some(ref => referenceKey(ref) === referenceKey(option.reference))
        const revision = option.reference.revision
        return <div key={referenceKey(option.reference)}>
          <Checkbox aria-label={`选择${option.name}，${revision === null ? '不可变集合' : `修订${revision}`}`}
            checked={checked} disabled={!option.available && !checked}
            onChange={event => change(option.reference, event.target.checked)}>
            {option.name} · {revision === null ? '不可变集合' : `修订 ${revision}`}
          </Checkbox>
          {option.reason && <p>{option.reason}</p>}
          <details><summary>版本登记标识</summary>{option.reference.assetId}</details>
        </div>
      })}
      {query.data?.pages.every(page => !page.items.length) && <p>没有匹配的正式版本；请先在现有发布流程中发布。</p>}
      {query.hasNextPage && <Button onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage}>加载更多正式版本</Button>}
    </AsyncState>
    <p>保存前会再次核对版本状态与口径依赖，列表可用不等于组合依赖有效。</p>
  </div>
}
