import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Input, Select, Space } from 'antd'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { identity, request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'

const replacementSchema = z.object({ policyId: z.string(), revision: z.number().int().positive() }).strict()
const retirementSchema = z.object({ assetType: z.literal('statistical_policy'), assetId: z.string(),
  revision: z.number().int().positive(), reason: z.string(),
  replacement: replacementSchema.nullable() })
const detailSchema = z.object({ published: z.object({ revision: z.number().int().positive(),
  document: z.object({ name: z.string() }), contentHash: z.string() }), retirement: retirementSchema.nullable() })
const impactSchema = z.object({ items: z.array(z.object({ kind: z.enum(['default', 'report']), referenceId: z.string(),
  policyRevision: z.number().int().positive(), basisId: z.string().nullable() })), nextCursor: z.string().nullable() })
const pendingSchema = z.object({ policyId: z.string(), revision: z.number().int().positive(), contentHash: z.string(),
  reason: z.string().min(1).max(4000), replacement: replacementSchema.nullable() }).strict()
const candidatesSchema = z.object({ items: z.array(z.object({ policyId: z.string(), name: z.string(),
  publishedRevision: z.number().int().positive().nullable() })), nextCursor: z.string().nullable() })
type Pending = z.infer<typeof pendingSchema>

export function PolicyRetirement({ scope, policyId, revision, username, csrf }: {
  scope: { database: string; companyId: string }; policyId: string; revision: number; username: string; csrf: string
}) {
  const client = useQueryClient()
  const path = '/statistical-policies/' + encodeURIComponent(policyId)
  const exactQuery = scopeQuery(scope) + '&revision=' + revision
  const storageKey = 'management-policy-retirement:' + JSON.stringify([username, scope.database, scope.companyId, policyId, revision])
  const [cached] = useState(() => {
    try {
      const raw = sessionStorage.getItem(storageKey)
      if (raw === null) return { value: null, invalid: false }
      return { value: pendingSchema.parse(JSON.parse(raw)), invalid: false }
    } catch { return { value: null, invalid: true } }
  })
  const [pending, setPending] = useState<Pending | null>(cached.value)
  const [reason, setReason] = useState(cached.value?.reason ?? '')
  const [chooseReplacement, setChooseReplacement] = useState(!!cached.value?.replacement)
  const [replacementId, setReplacementId] = useState(cached.value?.replacement?.policyId ?? '')
  const [replacementRevision, setReplacementRevision] = useState<number | null>(cached.value?.replacement?.revision ?? null)
  const [ack, setAck] = useState(false)
  const [notice, setNotice] = useState(cached.invalid ? '退役请求缓存无法读取，请保留缓存并核对，禁止覆盖提交。' : '')
  const [busy, setBusy] = useState(false)
  const [retryReady, setRetryReady] = useState(false)
  const [canReselect, setCanReselect] = useState(false)
  const [result, setResult] = useState<z.infer<typeof retirementSchema> | null>(null)
  const recovery = useRef<HTMLButtonElement>(null)
  const detail = useQuery({ queryKey: ['policy-version', scope, policyId, revision],
    queryFn: ({ signal }) => request(path + '?' + exactQuery, detailSchema, { signal }) })
  const impact = useInfiniteQuery({ queryKey: ['policy-impact', scope, policyId, revision],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request(path + '/impact?' + exactQuery
      + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), impactSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined,
  })
  const candidates = useInfiniteQuery({ queryKey: ['policy-replacement-candidates', scope], enabled: chooseReplacement,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request('/statistical-policies?' + scopeQuery(scope)
      + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), candidatesSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined,
  })
  const replacement = chooseReplacement && replacementId && replacementRevision
    ? { policyId: replacementId, revision: replacementRevision } : null
  const replacementDetail = useQuery({ queryKey: ['policy-replacement-version', scope, replacementId, replacementRevision], enabled: !!replacement,
    queryFn: ({ signal }) => request('/statistical-policies/' + encodeURIComponent(replacementId) + '?' + scopeQuery(scope)
      + '&revision=' + replacementRevision, detailSchema, { signal }) })
  const replacementIsSelf = replacement?.policyId === policyId && replacement.revision === revision
  const replacementReady = !chooseReplacement || (!!replacement && replacementDetail.isSuccess && !replacementDetail.isFetching
    && replacementDetail.data.published.revision === replacementRevision && !replacementDetail.data.retirement && !replacementIsSelf)
  useEffect(() => { if (pending && !busy) recovery.current?.focus() }, [pending, busy])
  const matches = (value: z.infer<typeof retirementSchema>, original: Pending) => value.assetId === original.policyId
    && value.revision === original.revision && value.reason === original.reason
    && value.replacement?.policyId === original.replacement?.policyId && value.replacement?.revision === original.replacement?.revision
  const finish = (value: z.infer<typeof retirementSchema>, message: string) => {
    setResult(value); setRetryReady(false)
    void client.invalidateQueries({ queryKey: ['policy-default-target', scope, policyId, revision] })
    void client.invalidateQueries({ queryKey: ['policy-default', scope] })
    try { sessionStorage.removeItem(storageKey); setPending(null); setNotice(message) }
    catch { setNotice(message + '；缓存清理失败，请读取原退役结果，勿再次提交。') }
  }
  const submit = async (original: Pending) => {
    try { sessionStorage.setItem(storageKey, JSON.stringify(original)) }
    catch { setNotice('无法保存退役请求，请启用会话存储后再提交。'); return }
    setPending(original); setRetryReady(false); setCanReselect(false); setBusy(true)
    try {
      const value = await request(path + '/versions/' + revision + '/retire', retirementSchema,
        { method: 'POST', csrf, body: { ...identity(scope), reason: original.reason, replacement: original.replacement } })
      if (!matches(value, original)) { setNotice('退役记录与原提交不同，请保留原请求并核对。'); return }
      finish(value, '退役已登记。')
    } catch { setNotice('退役结果待确认，请读取原退役结果；不会自动重发。') }
    finally { setBusy(false) }
  }
  const read = async () => {
    if (!pending) return
    setBusy(true); setRetryReady(false); setCanReselect(false)
    try {
      const current = await request(path + '?' + exactQuery, detailSchema)
      if (pending.policyId !== policyId || pending.revision !== revision || current.published.revision !== revision
        || current.published.contentHash !== pending.contentHash) {
        setNotice('发布版本身份与原请求不同，保留原请求供核对。'); return
      }
      if (current.retirement) {
        if (matches(current.retirement, pending)) finish(current.retirement, '已确认原退役登记。')
        else { setResult(current.retirement); setNotice('退役记录与原提交不同，请保留原请求并核对。') }
      } else {
        if (pending.replacement) {
          const selected = await request('/statistical-policies/' + encodeURIComponent(pending.replacement.policyId) + '?'
            + scopeQuery(scope) + '&revision=' + pending.replacement.revision, detailSchema)
          if (selected.retirement || selected.published.revision !== pending.replacement.revision) {
            setCanReselect(true)
            setNotice('原替代版本已不可用，保留原退役请求供核对，不能直接重提。'); return
          }
        }
        setRetryReady(true); setAck(false)
        setNotice('该精确版本尚无退役记录，核对影响并重新确认后可显式重提原请求。')
        await impact.refetch()
      }
    } catch (error) { setNotice((error as Error).message) }
    finally { setBusy(false) }
  }
  const currentRetirement = result ?? detail.data?.retirement
  const reselect = () => {
    if (!pending || !canReselect) return
    try {
      const prior = JSON.parse(sessionStorage.getItem(storageKey + ':prior') ?? '[]')
      if (!Array.isArray(prior)) throw Error('invalid archive')
      sessionStorage.setItem(storageKey + ':prior', JSON.stringify([...prior, pending]))
      sessionStorage.removeItem(storageKey)
      setPending(null); setReplacementId(''); setReplacementRevision(null); setAck(false); setCanReselect(false)
      setNotice('原请求已保留，请重新选择替代版本并核对退役影响后确认。')
    } catch { setNotice('无法保留原请求，未清除待核对的退役内容。') }
  }
  const ready = !busy && !cached.invalid && !currentRetirement && detail.data?.published.revision === revision
    && impact.isSuccess && !impact.isFetching && !impact.hasNextPage && ack && !!reason.trim() && replacementReady
  return <section aria-label="口径版本退役">
    <h2>{detail.data?.published.document.name ?? policyId} · 发布版本 {revision}</h2>
    <Alert type="warning" title="退役后此版本不能用于新报告，也不会自动切换替代口径。历史报告继续使用原依据，仍可读取和下载。" />
    <AsyncState loading={detail.isPending} error={detail.error} retry={() => void detail.refetch()}>
      <AsyncState loading={impact.isPending} error={impact.error} retry={() => void impact.refetch()}>
        <h3>本次读取的版本影响</h3>
        <p>默认配置需另行明确调整；历史报告不会重算。此列表不是全量总数或永久冻结的影响清单。</p>
        {impact.data?.pages.flatMap(page => page.items).map(item => <p key={item.kind + ':' + item.referenceId}>
          {item.kind === 'default' ? '场景默认' : '历史报告'} · {item.referenceId} · 版本 {item.policyRevision}
        </p>)}
        {impact.data?.pages.every(page => !page.items.length) && <p>本次未查到引用此版本的默认配置或历史报告。</p>}
        {impact.hasNextPage && <Button onClick={() => void impact.fetchNextPage()} loading={impact.isFetchingNextPage}>加载更多影响</Button>}
      </AsyncState>
    </AsyncState>
    {currentRetirement && <Alert type="info" title="此版本已有退役记录" description={<>
      <p>{currentRetirement.reason}</p>
      {currentRetirement.replacement && <p>登记的替代版本：{currentRetirement.replacement.policyId} · 版本 {currentRetirement.replacement.revision}；须明确选择后使用。</p>}
    </>} />}
    {notice && <Alert type="info" title={notice} />}
    <Checkbox aria-label="登记替代版本" checked={chooseReplacement} disabled={busy || !!pending || !!currentRetirement || cached.invalid}
      onChange={event => { setChooseReplacement(event.target.checked); setReplacementId(''); setReplacementRevision(null); setAck(false) }}>
      登记替代版本建议（可选，不自动调整默认）
    </Checkbox>
    {chooseReplacement && <div>
      <p>明确选择口径及发布版本。登记仅说明推荐目标，不证明业务规则等价；新报告仍需明确选择或调整默认。</p>
      {!pending && !currentRetirement && <AsyncState loading={candidates.isPending} error={candidates.error} retry={() => void candidates.refetch()}>
        <Space wrap>{candidates.data?.pages.flatMap(page => page.items).filter(item => item.publishedRevision).map(item =>
          <Button key={item.policyId} disabled={busy} onClick={() => { setReplacementId(item.policyId); setReplacementRevision(null); setAck(false) }}>
            选择{item.name}
          </Button>)}</Space>
        {candidates.hasNextPage && <Button onClick={() => void candidates.fetchNextPage()} loading={candidates.isFetchingNextPage}>加载更多替代口径</Button>}
      </AsyncState>}
      {replacementId && <>
        <p>替代口径：{replacementId}</p>
        <Select aria-label="替代发布版本" placeholder="明确选择发布版本" value={replacementRevision ?? undefined}
          disabled={busy || !!pending || !!currentRetirement} onChange={value => { setReplacementRevision(value); setAck(false) }}
          options={Array.from({ length: candidates.data?.pages.flatMap(page => page.items).find(item => item.policyId === replacementId)?.publishedRevision
            ?? replacementRevision ?? 0 }, (_, index) => ({ value: index + 1, label: '版本 ' + (index + 1) }))} />
      </>}
      {replacement && <AsyncState loading={replacementDetail.isPending} error={replacementDetail.error} retry={() => void replacementDetail.refetch()}>
        <p>替代版本：{replacementDetail.data?.published.document.name} · 版本 {replacementRevision}</p>
        {replacementIsSelf && <Alert type="warning" title="替代版本不能指向自身。" />}
        {replacementDetail.data?.retirement && <Alert type="warning" title="替代版本已退役，请另选有效版本。" />}
      </AsyncState>}
    </div>}
    <label htmlFor="policy-retirement-reason">退役原因</label>
    <Input.TextArea id="policy-retirement-reason" aria-label="退役原因" value={reason} maxLength={4000} rows={3}
      disabled={!!pending || !!currentRetirement || cached.invalid} onChange={event => setReason(event.target.value)} />
    <Checkbox aria-label="确认退役影响" checked={ack} disabled={busy || !!currentRetirement || cached.invalid}
      onChange={event => setAck(event.target.checked)}>已核对当前版本及全部影响，确认停止将此版本用于新报告并保留历史报告。</Checkbox>
    <Space wrap>
      <Button danger disabled={!ready || !!pending} loading={busy && !pending} onClick={() => {
        if (detail.data) void submit({ policyId, revision, contentHash: detail.data.published.contentHash, reason: reason.trim(), replacement })
      }}>确认退役此版本</Button>
      {pending && <Button ref={recovery} disabled={busy} onClick={() => void read()}>读取原退役结果</Button>}
      {pending && retryReady && <Button danger disabled={!ready} onClick={() => void submit(pending)}>确认重提原退役请求</Button>}
      {pending && canReselect && <Button disabled={busy} onClick={reselect}>保留原请求并重新选择替代版本</Button>}
    </Space>
  </section>
}
