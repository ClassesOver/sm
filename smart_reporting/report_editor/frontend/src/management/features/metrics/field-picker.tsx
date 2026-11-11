import { useState } from 'react'
import { Button, Input, Space } from 'antd'
import { useInfiniteQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'
const sourcesSchema = z.object({ items: z.array(z.object({ source_id: z.string(), name: z.string(), enabled: z.boolean(), publishedRevision: z.number().int().positive().nullable() })), nextCursor: z.string().nullable() })
const reference = z.object({ sourceId: z.string(), revision: z.number().int().positive(), contentHash: z.string() })
const fieldsSchema = z.object({ sourceVersion: reference, catalogVersion: reference, items: z.array(z.object({ fieldRef: z.string(), database: z.string(), table: z.string(), column: z.string(), dataType: z.string(), nullable: z.boolean(), description: z.string(), tableDescription: z.string() })), nextCursor: z.string().nullable() })
export function MetricFieldPicker({ scope, label, value, disabled, onChange }: {
 scope: { database: string; companyId: string }; label: string; value: string | null; disabled: boolean; onChange: (field: string) => void
}) {
 const [open, setOpen] = useState(false), [selected, setSelected] = useState<{ id: string; revision: number } | null>(null)
 const [search, setSearch] = useState(''), [query, setQuery] = useState('')
 const sources = useInfiniteQuery({ queryKey: ['metric-field-sources', scope], enabled: open, retry: false, initialPageParam: undefined as string | undefined,
  queryFn: ({ pageParam, signal }) => request('/sources?' + scopeQuery(scope) + '&publicationState=published' + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), sourcesSchema, { signal }), getNextPageParam: page => page.nextCursor ?? undefined })
 const fields = useInfiniteQuery({ queryKey: ['metric-field-catalog', scope, selected, query], enabled: open && !!selected, retry: false, initialPageParam: undefined as string | undefined,
  queryFn: async ({ pageParam, signal }) => {
   const result = await request('/metric-field-catalog?' + scopeQuery(scope) + '&sourceId=' + encodeURIComponent(selected!.id) + '&sourceRevision=' + selected!.revision + '&q=' + encodeURIComponent(query) + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), fieldsSchema, { signal })
   if (result.sourceVersion.sourceId !== selected!.id || result.sourceVersion.revision !== selected!.revision || result.catalogVersion.sourceId !== selected!.id
    || result.items.some(f => f.fieldRef !== [selected!.id, f.database, f.table, f.column].join('.'))) throw Error('字段目录身份与所选发布版本不一致，不能采用。')
   return result
  }, getNextPageParam: page => page.nextCursor ?? undefined })
 return <section aria-label={label + '目录选择'} style={{ display: 'grid', gap: 8, minWidth: 0 }}>
  <Button style={{ maxWidth: '100%', whiteSpace: 'normal', height: 'auto' }} disabled={disabled} onClick={() => setOpen(v => !v)}>{open ? '收起' : '从已发布目录选择'}{label}</Button>
  {open && <>
   <p>当前引用：{value || '未填写'}。仅浏览已发布数据源的暴露目录，不读取业务数据；点击采用才修改此字段，不自动调整维度、公式或其他字段。</p>
   <AsyncState loading={sources.isPending} error={sources.error} retry={() => void sources.refetch()}>
    <Space wrap>{sources.data?.pages.flatMap(p => p.items).filter(s => s.enabled && s.publishedRevision).map(s => <Button key={s.source_id} disabled={disabled} style={{ maxWidth: '100%', whiteSpace: 'normal', height: 'auto' }} onClick={() => { setSelected({ id: s.source_id, revision: s.publishedRevision! }); setSearch(''); setQuery('') }}>浏览 {s.name} · {s.source_id} 版本 {s.publishedRevision}</Button>)}</Space>
    {sources.data && !sources.data.pages.some(p => p.items.some(s => s.enabled && s.publishedRevision)) && <p>当前页没有可用的已发布数据源；手填引用保留，可继续加载候选或先发布数据源。</p>}
    {sources.hasNextPage && <Button disabled={disabled} loading={sources.isFetchingNextPage} onClick={() => void sources.fetchNextPage()}>加载更多数据源</Button>}
   </AsyncState>
   {selected && <>
    <Space wrap><Input aria-label={'搜索' + label + '目录'} value={search} maxLength={200} disabled={disabled} onChange={e => setSearch(e.target.value)} onPressEnter={() => setQuery(search)} /><Button disabled={disabled} onClick={() => setQuery(search)}>搜索{label}目录</Button><Button disabled={disabled} loading={fields.isFetching} onClick={() => void fields.refetch()}>刷新{label}目录</Button></Space>
    <AsyncState loading={fields.isPending} error={fields.error} retry={() => void fields.refetch()}>
     {fields.data && <p>数据源 {selected.id} 发布版本 {selected.revision} · 目录版本 {fields.data.pages[0].catalogVersion.revision}；仅表示此版本登记结构，不代表取数健康或业务口径批准。</p>}
     <div role="region" aria-label={label + '候选字段，可滚动'} tabIndex={0} style={{ maxHeight: 320, overflow: 'auto', overflowWrap: 'anywhere' }}>
      {fields.data?.pages.flatMap(p => p.items).map(f => <article key={f.fieldRef} style={{ padding: '8px 0', borderBottom: '1px solid #edf0f4' }}>
       <strong>{f.fieldRef}</strong><div>{f.dataType} · {f.nullable ? '可空' : '非空'} · {f.description || '未登记字段说明'}</div>
       {f.tableDescription && <div>表说明：{f.tableDescription}</div>}
       <Button disabled={disabled} style={{ maxWidth: '100%', whiteSpace: 'normal', height: 'auto' }} onClick={() => onChange(f.fieldRef)}>采用字段 {f.fieldRef}</Button>
      </article>)}
     </div>
     {fields.data && !fields.data.pages.some(p => p.items.length) && <p>该版本暴露目录没有匹配字段；保留当前引用，不扩大表范围。</p>}
     {fields.hasNextPage && <Button disabled={disabled} loading={fields.isFetchingNextPage} onClick={() => void fields.fetchNextPage()}>加载更多字段</Button>}
    </AsyncState>
   </>}
  </>}
 </section>
}
