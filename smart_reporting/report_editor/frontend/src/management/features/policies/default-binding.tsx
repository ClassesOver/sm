import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Space } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { identity, request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'
import { PolicyEvidencePicker } from './evidence-picker'

const refSchema = z.object({ policyId: z.string(), revision: z.number().int().positive() }).strict()
const bindingSchema = z.object({ version: z.number().int().nonnegative(), policyVersion: refSchema.nullable(),
  backgroundReleaseId: z.string().nullable() })
const backgroundCatalogSchema = z.object({ items: z.array(z.object({ releaseId: z.string(), kind: z.string(), availableForSelection: z.boolean() })) })
const currentSchema = bindingSchema.extend({ issues: z.array(z.object({ code: z.string(), impact: z.string(), message: z.string() })) })
const targetSchema = z.object({ published: z.object({ revision: z.number().int().positive(), contentHash: z.string(),
  document: z.object({ name: z.string(), scenario: z.string() }) }), retirement: z.object({ reason: z.string() }).nullable() })
const pendingSchema = z.object({ scenario: z.string(), previous: bindingSchema, target: refSchema,
  contentHash: z.string(), targetName: z.string(), backgroundReleaseId: z.string().nullable() }).strict()
type Pending = z.infer<typeof pendingSchema>
type Binding = z.infer<typeof bindingSchema>
const sameRef = (a: Binding['policyVersion'], b: Binding['policyVersion']) => a?.policyId === b?.policyId && a?.revision === b?.revision
const sameBinding = (a: Binding, b: Binding) => a.version === b.version && sameRef(a.policyVersion, b.policyVersion)
  && a.backgroundReleaseId === b.backgroundReleaseId

export function PolicyDefaultBinding({ scope, policyId, revision, username, csrf }: {
  scope: { database: string; companyId: string }; policyId: string; revision: number; username: string; csrf: string
}) {
  const target = useQuery({ queryKey: ['policy-default-target', scope, policyId, revision],
    queryFn: ({ signal }) => request('/statistical-policies/' + encodeURIComponent(policyId) + '?' + scopeQuery(scope)
      + '&revision=' + revision, targetSchema, { signal }) })
  return <AsyncState loading={target.isPending} error={target.error} retry={() => void target.refetch()}>
    {target.data && target.data.published.revision === revision && <DefaultForm key={target.data.published.document.scenario}
      scope={scope} policyId={policyId} revision={revision} username={username} csrf={csrf} target={target.data} />}
  </AsyncState>
}
function DefaultForm({ scope, policyId, revision, username, csrf, target }: {
  scope: { database: string; companyId: string }; policyId: string; revision: number; username: string; csrf: string;
  target: z.infer<typeof targetSchema>
}) {
  const client = useQueryClient()
  const scenario = target.published.document.scenario
  const storageKey = 'management-policy-default:' + JSON.stringify([username, scope.database, scope.companyId, scenario])
  const [cached] = useState(() => {
    try {
      const raw = sessionStorage.getItem(storageKey)
      return { value: raw === null ? null : pendingSchema.parse(JSON.parse(raw)), invalid: false }
    } catch { return { value: null, invalid: true } }
  })
  const [pending, setPending] = useState<Pending | null>(cached.value)
  const [checked, setChecked] = useState<z.infer<typeof currentSchema> | null>(null)
  const [background, setBackground] = useState<{ releaseId: string | null } | null>(null)
  const [ack, setAck] = useState(false)
  const [busy, setBusy] = useState(false)
  const [retryReady, setRetryReady] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [notice, setNotice] = useState(cached.invalid ? '默认调整请求缓存无法读取，请保留缓存核对，禁止覆盖提交。' : '')
  const recovery = useRef<HTMLButtonElement>(null)
  const path = '/report-policy-defaults/' + encodeURIComponent(scenario)
  const query = useQuery({ queryKey: ['policy-default', scope, scenario],
    queryFn: ({ signal }) => request(path + '?' + scopeQuery(scope), currentSchema, { signal }) })
  const current = checked ?? query.data
  const selectedBackground = background ? background.releaseId : current?.backgroundReleaseId ?? null
  useEffect(() => { if (pending && !busy) recovery.current?.focus() }, [pending, busy])
  const clearPending = () => {
    try { sessionStorage.removeItem(storageKey); setPending(null); return true }
    catch { setNotice('无法清理原请求缓存，请读回核对，不要再次提交。'); return false }
  }
  const expected = (original: Pending): Binding => ({ version: original.previous.version + 1,
    policyVersion: original.target, backgroundReleaseId: original.backgroundReleaseId })
  const submit = async (original: Pending) => {
    try { sessionStorage.setItem(storageKey, JSON.stringify(original)) }
    catch { setNotice('无法保存默认调整请求，请启用会话存储后再提交。'); return }
    setPending(original); setBusy(true); setRetryReady(false); setConflict(false)
    try {
      const result = await request(path, bindingSchema, { method: 'PUT', csrf, body: { ...identity(scope),
        expectedVersion: original.previous.version, policyVersion: original.target, backgroundReleaseId: original.backgroundReleaseId } })
      if (!sameBinding(result, expected(original))) { setNotice('返回的默认配置与原目标不同，请读取原默认调整结果。'); return }
      setChecked({ ...result, issues: [] }); setAck(false)
      if (clearPending()) { setBackground(null); setNotice('默认配置已更新，仅影响新报告；历史报告继续使用原依据。') }
      void client.invalidateQueries({ queryKey: ['policy-impact', scope] })
      const refreshed = await query.refetch()
      if (refreshed.isSuccess) setChecked(refreshed.data)
      else setNotice('默认配置已更新，但当前可用性读取失败，请刷新核对；仅影响新报告。')
    } catch { setNotice('默认调整结果待确认，请先读取原默认调整结果；不会自动重发。') }
    finally { setBusy(false) }
  }
  const read = async () => {
    if (!pending || pending.scenario !== scenario) { setNotice('原请求场景与当前版本不同，请保留原请求核对。'); return }
    setBusy(true); setRetryReady(false); setConflict(false); setAck(false)
    try {
      const latest = await request(path + '?' + scopeQuery(scope), currentSchema)
      setChecked(latest)
      if (sameBinding(latest, expected(pending))) {
        if (clearPending()) { setBackground(null); setNotice('当前默认与原目标一致；这是当前绑定核对，不是独立提交回执。仅影响新报告。') }
        void client.invalidateQueries({ queryKey: ['policy-impact', scope] })
      } else if (sameBinding(latest, pending.previous)) {
        const originalTarget = await request('/statistical-policies/' + encodeURIComponent(pending.target.policyId) + '?'
          + scopeQuery(scope) + '&revision=' + pending.target.revision, targetSchema)
        if (originalTarget.retirement || originalTarget.published.contentHash !== pending.contentHash
          || originalTarget.published.revision !== pending.target.revision || originalTarget.published.document.scenario !== scenario) {
          setNotice('原目标版本已不可用或身份变化，保留原请求，重新选择有效目标后核对。'); setConflict(true); return
        }
        if (pending.backgroundReleaseId !== null) {
          const backgrounds = await request('/business-evidence-releases/catalog?' + scopeQuery(scope)
            + '&kind=background&q=' + encodeURIComponent(pending.backgroundReleaseId), backgroundCatalogSchema)
          if (!backgrounds.items.some(item => item.releaseId === pending.backgroundReleaseId && item.kind === 'background' && item.availableForSelection)) {
            setConflict(true); setNotice('原背景集合已不可用，保留原请求；请重新选择背景后核对。'); return
          }
        }
        setRetryReady(true); setNotice('默认仍与提交前一致，重新确认后可显式重提原默认调整。')
      } else { setConflict(true); setNotice('默认配置已变化，原请求已保留；须按最新版本重新核对后才能提交。') }
    } catch (error) { setNotice((error as Error).message) }
    finally { setBusy(false) }
  }
  const recheck = () => {
    if (!pending || !checked) return
    try {
      const prior = JSON.parse(sessionStorage.getItem(storageKey + ':prior') ?? '[]')
      if (!Array.isArray(prior)) throw Error('invalid archive')
      sessionStorage.setItem(storageKey + ':prior', JSON.stringify([...prior, pending]))
      if (!clearPending()) return
      setConflict(false); setRetryReady(false); setAck(false); setBackground(null)
      setNotice('原请求已保留，当前默认已更新；请重新核对目标版本和背景后确认。')
    } catch { setNotice('无法保留原请求，未清除待核对内容。') }
  }
  const unchangedTarget = current && sameRef(current.policyVersion, { policyId, revision }) && selectedBackground === current.backgroundReleaseId
  const ready = !busy && !cached.invalid && !!current && query.isSuccess && !query.isFetching && ack && !target.retirement
  return <section aria-label="场景默认口径">
    <h2>场景默认口径</h2>
    <p>场景：{scenario}。仅影响新报告；已有报告和正在运行的报告保留原依据。</p>
    <AsyncState loading={query.isPending} error={query.error} retry={() => void query.refetch()}>
      {current && <>
        <p>当前默认：{current.policyVersion ? `${current.policyVersion.policyId} · 版本 ${current.policyVersion.revision}` : '尚未设置'} · 配置版本 {current.version}</p>
        <p>本次目标：{target.published.document.name} · {policyId} · 版本 {revision}</p>
        <p>当前背景：{current.backgroundReleaseId ?? '未设置'}</p>
        <p>本次背景：{selectedBackground ?? '不使用背景材料'}{!background && '（保留当前绑定）'}</p>
        <p>仅换背景不创建新口径版本；背景用于解释支持，不自动证明因果。</p>
        <PolicyEvidencePicker key={JSON.stringify([scope, pending?.backgroundReleaseId])} scope={scope} kind="background" value={selectedBackground ?? ''} disabled={busy || cached.invalid || !!pending || !!target.retirement} onChange={releaseId => { setBackground({ releaseId }); setAck(false) }} />
        <Space wrap><Button disabled={busy || cached.invalid || !!pending || !!target.retirement || selectedBackground === null} onClick={() => { setBackground({ releaseId: null }); setAck(false) }}>本次不使用背景材料</Button>
          {background && <Button disabled={busy || !!pending} onClick={() => { setBackground(null); setAck(false) }}>保留当前背景</Button>}</Space>
        {current.issues.map((issue, index) => <Alert key={issue.code + index} type="warning" title={issue.message} />)}
      </>}
    </AsyncState>
    {target.retirement && <Alert type="warning" title="当前选中版本已退役，不能设为新报告默认。" />}
    {pending && <p>待核对原目标：{pending.targetName} · {pending.target.policyId} · 版本 {pending.target.revision}；原背景目标 {pending.backgroundReleaseId ?? '不使用背景材料'}；原配置版本 {pending.previous.version}</p>}
    {notice && <Alert type="info" title={notice} />}
    <Checkbox aria-label="确认调整场景默认" checked={ack} disabled={busy || cached.invalid || !!target.retirement}
      onChange={event => setAck(event.target.checked)}>已核对场景、当前默认、目标版本及本次背景知识，仅为新报告调整默认。</Checkbox>
    <Space wrap>
      <Button type="primary" disabled={!ready || !!pending || !!unchangedTarget} onClick={() => {
        if (current) void submit({ scenario, previous: bindingSchema.parse(current), target: { policyId, revision },
          targetName: target.published.document.name, contentHash: target.published.contentHash, backgroundReleaseId: selectedBackground })
      }}>确认调整默认</Button>
      {pending && <Button ref={recovery} disabled={busy} onClick={() => void read()}>读取原默认调整结果</Button>}
      {pending && retryReady && <Button disabled={!ready} onClick={() => void submit(pending)}>确认重提原默认调整</Button>}
      {pending && conflict && <Button disabled={busy} onClick={recheck}>保留原请求并重新核对</Button>}
    </Space>
  </section>
}
