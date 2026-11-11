import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, Select, Space } from 'antd'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { identity, request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'

const refSchema = z.object({ metricId: z.string(), revision: z.number().int().positive() }).strict()
const receiptSchema = z.object({ assetType: z.literal('metric'), assetId: z.string(), revision: z.number().int().positive(),
  reason: z.string(), replacement: refSchema.nullable() })
const readSchema = z.object({ published: z.object({ revision: z.number().int().positive(), contentHash: z.string() }), retirement: receiptSchema.nullable() })
const pendingSchema = z.object({ metricId: z.string(), revision: z.number().int().positive(), contentHash: z.string(),
  reason: z.string().min(1).max(4000), replacement: refSchema.nullable() }).strict()
const listSchema = z.object({ items: z.array(z.object({ metricId: z.string(), name: z.string(),
  publishedRevision: z.number().int().positive().nullable() })), nextCursor: z.string().nullable() })
type Pending = z.infer<typeof pendingSchema>
export function MetricRetirement({ scope, metricId, revision, contentHash, username, csrf, impactReady, retired }: {
  scope: { database: string; companyId: string }; metricId: string; revision: number; contentHash: string;
  username: string; csrf: string; impactReady: boolean; retired: boolean
}) {
  const client = useQueryClient()
  const path = '/metrics/' + encodeURIComponent(metricId)
  const storageKey = 'management-metric-retirement:' + JSON.stringify([username, scope.database, scope.companyId, metricId, revision])
  const [cache] = useState(() => {
    try { const raw = sessionStorage.getItem(storageKey); return { value: raw === null ? null : pendingSchema.parse(JSON.parse(raw)), invalid: false } }
    catch { return { value: null, invalid: true } }
  })
  const [pending, setPending] = useState<Pending | null>(cache.value)
  const [reason, setReason] = useState(cache.value?.reason ?? '')
  const [replacementEnabled, setReplacementEnabled] = useState(!!cache.value?.replacement)
  const [replacementId, setReplacementId] = useState(cache.value?.replacement?.metricId ?? '')
  const [replacementRevision, setReplacementRevision] = useState<number | null>(cache.value?.replacement?.revision ?? null)
  const [ack, setAck] = useState(false)
  const [busy, setBusy] = useState(false)
  const [retryReady, setRetryReady] = useState(false)
  const [canReselect, setCanReselect] = useState(false)
  const [registered, setRegistered] = useState(false)
  const [notice, setNotice] = useState(cache.invalid ? '指标退役缓存无法读取，请保留缓存核对，禁止覆盖。' : '')
  const recovery = useRef<HTMLButtonElement>(null)
  const candidates = useInfiniteQuery({ queryKey: ['metric-replacement-candidates', scope], enabled: replacementEnabled,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request('/metrics?' + scopeQuery(scope)
      + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), listSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined,
  })
  const replacement = replacementEnabled && replacementId && replacementRevision ? { metricId: replacementId, revision: replacementRevision } : null
  const target = useQuery({ queryKey: ['metric-replacement-version', scope, replacementId, replacementRevision], enabled: !!replacement,
    queryFn: ({ signal }) => request('/metrics/' + encodeURIComponent(replacementId) + '?' + scopeQuery(scope)
      + '&revision=' + replacementRevision, readSchema, { signal }) })
  const isSelf = replacement?.metricId === metricId && replacement.revision === revision
  const replacementReady = !replacementEnabled || (!!replacement && target.isSuccess && !target.isFetching
    && target.data.published.revision === replacement.revision && !target.data.retirement && !isSelf)
  useEffect(() => { if (pending && !busy) recovery.current?.focus() }, [pending, busy])
  const matches = (value: z.infer<typeof receiptSchema>, original: Pending) => value.assetId === original.metricId
    && value.revision === original.revision && value.reason === original.reason
    && value.replacement?.metricId === original.replacement?.metricId && value.replacement?.revision === original.replacement?.revision
  const finish = (message: string) => {
    setRegistered(true); setRetryReady(false)
    void client.invalidateQueries({ queryKey: ['metric-version', scope, metricId, revision] })
    void client.invalidateQueries({ queryKey: ['metric-impact', scope, metricId, revision] })
    void client.invalidateQueries({ queryKey: ['policy-default', scope] })
    try { sessionStorage.removeItem(storageKey); setPending(null); setNotice(message) }
    catch { setNotice(message + '；缓存清理失败，请读回核对。') }
  }
  const submit = async (original: Pending) => {
    try { sessionStorage.setItem(storageKey, JSON.stringify(original)) }
    catch { setNotice('无法保存指标退役请求，未提交。'); return }
    setPending(original); setBusy(true); setRetryReady(false); setCanReselect(false)
    try {
      const value = await request(path + '/versions/' + revision + '/retire', receiptSchema,
        { method: 'POST', csrf, body: { ...identity(scope), reason: original.reason, replacement: original.replacement } })
      if (!matches(value, original)) { setNotice('退役记录与原输入不同，请保留原请求并核对。'); return }
      finish('指标退役已登记。历史定义和报告保持原版本，不自动替换。')
    } catch { setNotice('指标退役结果待确认，请读取原指标退役结果；不会自动重发。') }
    finally { setBusy(false) }
  }
  const read = async () => {
    if (!pending) return
    setBusy(true); setRetryReady(false); setCanReselect(false); setAck(false)
    try {
      const result = await request(path + '?' + scopeQuery(scope) + '&revision=' + revision, readSchema)
      if (pending.metricId !== metricId || pending.revision !== revision || result.published.revision !== revision
        || result.published.contentHash !== pending.contentHash) { setNotice('指标版本身份与原请求不同，请保留原输入核对。'); return }
      if (result.retirement) {
        if (matches(result.retirement, pending)) finish('已确认原指标退役登记。历史定义和报告保持原版本。')
        else setNotice('退役记录与原输入不同，请保留原请求并核对。')
      } else {
        if (pending.replacement) {
          const originalTarget = await request('/metrics/' + encodeURIComponent(pending.replacement.metricId) + '?' + scopeQuery(scope)
            + '&revision=' + pending.replacement.revision, readSchema)
          if (originalTarget.retirement || originalTarget.published.revision !== pending.replacement.revision) {
            setCanReselect(true)
            setNotice('原替代指标版本已不可用，请保留原请求核对，不能直接重提。'); return
          }
        }
        await client.invalidateQueries({ queryKey: ['metric-impact', scope, metricId, revision] })
        setRetryReady(true); setNotice('此精确版本尚未退役，重新核对全部影响并确认后可显式重提原请求。')
      }
    } catch (error) { setNotice((error as Error).message) }
    finally { setBusy(false) }
  }
  const ready = impactReady && !retired && !registered && !busy && !cache.invalid && ack && !!reason.trim() && replacementReady
  const reselect = () => {
    if (!pending || !canReselect) return
    try {
      const prior = JSON.parse(sessionStorage.getItem(storageKey + ':prior') ?? '[]')
      if (!Array.isArray(prior)) throw Error('invalid archive')
      sessionStorage.setItem(storageKey + ':prior', JSON.stringify([...prior, pending]))
      sessionStorage.removeItem(storageKey)
      setPending(null); setReplacementId(''); setReplacementRevision(null); setAck(false); setCanReselect(false)
      setNotice('原指标退役请求已保留，请重新选择替代指标并核对全部影响后确认。')
    } catch { setNotice('无法保留原输入，未清除指标退役请求。') }
  }
  return <section aria-label="指标版本退役">
    <h3>退役此指标版本</h3>
    <p>退役会使依赖此版本的口径不能被新报告选用；不会替换依赖、迁移默认或改写历史报告。请先读完上方全部影响。</p>
    {notice && <Alert type="info" title={notice} />}
    <Checkbox aria-label="登记替代指标版本" checked={replacementEnabled} disabled={busy || !!pending || retired || registered || cache.invalid}
      onChange={event => { setReplacementEnabled(event.target.checked); setReplacementId(''); setReplacementRevision(null); setAck(false) }}>
      登记替代指标建议（可选，不自动替换依赖或默认）
    </Checkbox>
    {replacementEnabled && <div>
      <p>替代建议不等于公式、单位或粒度等价；实际采用须重新核对并明确发布口径。</p>
      {!pending && !retired && !registered && <AsyncState loading={candidates.isPending} error={candidates.error} retry={() => void candidates.refetch()}>
        <Space wrap>{candidates.data?.pages.flatMap(page => page.items).filter(item => item.publishedRevision).map(item =>
          <Button key={item.metricId} disabled={busy} onClick={() => { setReplacementId(item.metricId); setReplacementRevision(null); setAck(false) }}>选择{item.name} · {item.metricId}</Button>)}</Space>
        {candidates.hasNextPage && <Button onClick={() => void candidates.fetchNextPage()} loading={candidates.isFetchingNextPage}>加载更多替代指标</Button>}
      </AsyncState>}
      {replacementId && <><p>替代指标：{replacementId}</p>
        <Select aria-label="替代指标发布版本" placeholder="明确选择发布版本" value={replacementRevision ?? undefined}
          disabled={busy || !!pending || retired || registered} onChange={value => { setReplacementRevision(value); setAck(false) }}
          options={Array.from({ length: candidates.data?.pages.flatMap(page => page.items).find(item => item.metricId === replacementId)?.publishedRevision
            ?? replacementRevision ?? 0 }, (_, i) => ({ value: i + 1, label: '版本 ' + (i + 1) }))} /></>}
      {replacement && <AsyncState loading={target.isPending} error={target.error} retry={() => void target.refetch()}>
        {isSelf && <Alert type="warning" title="替代指标不能指向自身版本。" />}
        {target.data?.retirement && <Alert type="warning" title="替代指标版本已退役，请选择有效版本。" />}
      </AsyncState>}
    </div>}
    <label htmlFor="metric-retirement-reason">指标退役原因</label>
    <Input.TextArea id="metric-retirement-reason" aria-label="指标退役原因" rows={3} maxLength={4000} value={reason}
      disabled={busy || !!pending || retired || registered || cache.invalid} onChange={event => setReason(event.target.value)} />
    <Checkbox aria-label="确认指标退役影响" checked={ack} disabled={busy || retired || registered || cache.invalid}
      onChange={event => setAck(event.target.checked)}>已核对精确指标版本及全部影响，确认停止新选用并保留历史报告。</Checkbox>
    <Space wrap>
      <Button danger disabled={!ready || !!pending} onClick={() => void submit({ metricId, revision, contentHash, reason: reason.trim(), replacement })}>确认退役指标版本</Button>
      {pending && <Button ref={recovery} disabled={busy} onClick={() => void read()}>读取原指标退役结果</Button>}
      {pending && retryReady && <Button danger disabled={!ready} onClick={() => void submit(pending)}>确认重提原指标退役</Button>}
      {pending && canReselect && <Button disabled={busy} onClick={reselect}>保留原请求并重选替代指标</Button>}
    </Space>
  </section>
}
