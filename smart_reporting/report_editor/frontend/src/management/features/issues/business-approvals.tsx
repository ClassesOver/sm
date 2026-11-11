import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Input, Space } from 'antd'
import { useInfiniteQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { ApiError, identity, request, scopeQuery } from '../../api/http'
import { correctedVersionSchema } from './fix-versions'

const id = z.string().min(1).max(128).regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/)
const locatorSchema = z.object({ kind: z.enum(['text_lines', 'pdf_page', 'docx_paragraph', 'docx_table_cell']),
  page: z.number().int().positive().nullable(), lineStart: z.number().int().positive().nullable(), lineEnd: z.number().int().positive().nullable(),
  paragraph: z.number().int().positive().nullable(), table: z.number().int().positive().nullable(), row: z.number().int().positive().nullable(), column: z.number().int().positive().nullable() })
const sourceSchema = z.object({ regressionReceiptId: id, documentId: id, revision: z.number().int().positive(), locator: locatorSchema,
  quote: z.string().trim().min(1).max(10000) })
const approvalRequestSchema = z.object({ requestId: id, expectedIssueVersion: z.number().int().positive(), decision: z.literal('approve_expected_values'),
  regressionReceiptIds: z.array(id).min(1).max(50), sources: z.array(sourceSchema).min(1).max(100), approvalReason: z.string().trim().min(1).max(10000) })
const pendingSchema = z.object({ issueId: id, request: approvalRequestSchema, correctedVersions: z.array(correctedVersionSchema) })
const receiptSchema = z.object({ issueId: id, receiptId: id, requestHash: z.string().regex(/^[a-f0-9]{64}$/),
  request: z.object({ requestId: id, expectedIssueVersion: z.number().int().positive(), regressionReceiptIds: z.array(id).min(1).max(50) }),
  correctedVersions: z.array(correctedVersionSchema), approvedByUsername: z.string(), approvedByAccountId: z.number().int().positive(), createdAt: z.string(),
  businessApproval: z.literal('explicitly_approved'), approvalScope: z.literal('regression_expected_values'), currentEvidenceStatus: z.literal('not_checked') })
const optionsSchema = z.object({ items: z.array(z.object({ documentId: id, revision: z.number().int().positive(), name: z.string(), available: z.boolean(), reason: z.string() })), nextCursor: z.string().nullable() })
const fragmentSchema = z.object({ locator: locatorSchema, text: z.string() })
const documentSchema = z.object({ documentId: id, revisions: z.array(z.object({ revision: z.number().int().positive(), reviewStatus: z.string(), ingestionStatus: z.string(),
  parseReceipt: z.object({ fragments: z.array(fragmentSchema) }).nullable() })) })
type Source = z.infer<typeof sourceSchema> & { title?: string }
type Pending = z.infer<typeof pendingSchema>
type Receipt = z.infer<typeof receiptSchema>
export type ApprovalCandidate = { receiptId: string; status: 'passed' | 'failed'; request: { caseId: string; expectedIssueVersion: number;
  expectationReason?: string; assertions?: { factId: string; expectedStatus: string; expectedValue?: string | null; unit: string }[] } }
export type ApprovalChoice = { requestId: string; regressionReceiptIds: string[] }
type Scope = { database: string; companyId: string }
const same = (left: unknown, right: unknown): boolean => JSON.stringify(left) === JSON.stringify(right)

export async function approvalRequestHash(value: unknown): Promise<string> {
  // 与管理服务_digest的sort_keys/ensure_ascii一致；这里只处理严格请求模型中的整数和文本。
  const sorted = (item: unknown): unknown => Array.isArray(item) ? item.map(sorted)
    : item !== null && typeof item === 'object' ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b, 'en')).map(([key, value]) => [key, sorted(value)])) : item
  const text = JSON.stringify(sorted(value)).replace(/[\u0080-\uffff]/g, char => '\\u' + char.charCodeAt(0).toString(16).padStart(4, '0'))
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

function SourcePicker({ scope, issueId, onChoose, onCancel }: { scope: Scope; issueId: string; onChoose: (value: Omit<Source, 'regressionReceiptId'>) => void; onCancel: () => void }) {
  const [search, setSearch] = useState('')
  const [detail, setDetail] = useState<{ documentId: string; revision: number; title: string; fragments: z.infer<typeof fragmentSchema>[] } | null>(null)
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(false)
  const sequence = useRef(0)
  const options = useInfiniteQuery({ queryKey: ['issue-approval-sources', scope, issueId, search], initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request('/report-issue-reviews/' + encodeURIComponent(issueId) + '/approval-source-options?' + scopeQuery(scope)
      + '&q=' + encodeURIComponent(search) + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), optionsSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined })
  const read = async (documentId: string, revision: number, title: string) => {
    const token = ++sequence.current
    setLoading(true); setDetail(null); setNotice('')
    try {
      const document = await request('/business-documents/' + encodeURIComponent(documentId) + '?' + scopeQuery(scope), documentSchema)
      if (token !== sequence.current) return
      const target = document.revisions.find(item => item.revision === revision)
      if (document.documentId !== documentId || !target?.parseReceipt || target.reviewStatus !== 'approved' || target.ingestionStatus !== 'ready') {
        setNotice('原件修订已变化或尚不可用，请重新选择。'); return
      }
      setDetail({ documentId, revision, title, fragments: target.parseReceipt.fragments })
    } catch (error) { if (token === sequence.current) setNotice(error instanceof ApiError ? error.message : '原件读取失败，请显式重试。') }
    finally { if (token === sequence.current) setLoading(false) }
  }
  return <Card size="small" title="选择独立原件与位置">
    <Input.Search aria-label="搜索预期来源原件" placeholder="按原件名称搜索" enterButton="搜索原件" maxLength={128} onSearch={value => { ++sequence.current; setDetail(null); setLoading(false); setSearch(value) }} />
    {options.isPending && <p role="status">正在读取原件候选…</p>}
    {options.error && <Button onClick={() => void options.refetch()}>重试读取原件候选</Button>}
    {options.data?.pages.flatMap(page => page.items).map(item => <div key={item.documentId + ':' + item.revision}>
      <p>{item.name} · 修订 {item.revision}</p>
      {item.reason && <p>{item.reason}</p>}
      <Button disabled={!item.available} onClick={() => void read(item.documentId, item.revision, item.name)}>读取{item.name}</Button>
    </div>)}
    {options.data?.pages.every(page => !page.items.length) && <p>暂无匹配的已发布原件，请先完成原件审核与发布。</p>}
    {options.hasNextPage && <Button loading={options.isFetchingNextPage} onClick={() => void options.fetchNextPage()}>加载更多来源原件</Button>}
    {loading && <p role="status">正在读取原文位置…</p>}
    {notice && <Alert type="warning" title={notice} />}
    {detail?.fragments.map((fragment, index) => <div key={index}>
      <h4>原文位置 {index + 1}</h4>
      <p>{locationLabel(fragment.locator)}</p>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{fragment.text.slice(0, 10000)}</pre>
      {fragment.text.length > 10000 && <p>此片段较长，先显示前10000字；可在选取后缩短摘录。</p>}
      <Button onClick={() => onChoose({ documentId: detail.documentId, revision: detail.revision, title: detail.title, locator: fragment.locator, quote: fragment.text.slice(0, 10000) })}>采用此原文位置</Button>
    </div>)}
    <Button onClick={onCancel}>结束选择原件</Button>
  </Card>
}

function locationLabel(locator: z.infer<typeof locatorSchema>): string {
  if (locator.kind === 'text_lines') return `第${locator.lineStart}–${locator.lineEnd}行`
  if (locator.kind === 'pdf_page') return `第${locator.page}页`
  if (locator.kind === 'docx_paragraph') return `第${locator.paragraph}段`
  return `表${locator.table}，第${locator.row}行、第${locator.column}列`
}

export function BusinessApprovals({ scope, issueId, version, username, csrf, correctedVersions, candidates, disabled, onUse }: {
  scope: Scope; issueId: string; version: number; username: string; csrf: string; correctedVersions: z.infer<typeof correctedVersionSchema>[];
  candidates: ApprovalCandidate[]; disabled: boolean; onUse: (choice: ApprovalChoice) => void
}) {
  const path = '/report-issue-reviews/' + encodeURIComponent(issueId) + '/business-approvals'
  const cacheKey = 'management-issue-approval:' + JSON.stringify([username, scope.database, scope.companyId, issueId])
  const [pending, setPending] = useState<Pending | null>(() => { try { return pendingSchema.parse(JSON.parse(sessionStorage.getItem(cacheKey) ?? 'null')) } catch { return null } })
  const [editing, setEditing] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [picking, setPicking] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [knownId, setKnownId] = useState('')
  const [notice, setNotice] = useState('')
  const [outcome, setOutcome] = useState<'retry' | 'changed' | null>(null)
  const [busy, setBusy] = useState(false)
  const running = useRef(false)
  const readButton = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (pending && !busy) readButton.current?.focus() }, [pending, busy])
  const clear = () => { try { sessionStorage.removeItem(cacheKey); setPending(null); setOutcome(null); return true } catch { setNotice('无法清除签认缓存，请先核对会话存储。'); return false } }
  const matches = async (result: Receipt, value: Pending) => result.issueId === value.issueId
    && result.request.requestId === value.request.requestId && result.requestHash === await approvalRequestHash(value.request)
    && same(result.correctedVersions, value.correctedVersions)
  const post = async (value: Pending) => {
    if (running.current || disabled) return
    try { sessionStorage.setItem(cacheKey, JSON.stringify(pendingSchema.parse(value))) }
    catch { setNotice('无法保存签认请求，请启用会话存储后再提交。'); return }
    running.current = true; setBusy(true); setPending(value); setOutcome(null)
    try {
      const result = await request(path, receiptSchema, { method: 'POST', csrf, body: { ...identity(scope), ...value.request } })
      if (!await matches(result, value)) { setNotice('签认响应与原完整请求不一致，请读取原签认核对。'); return }
      setReceipt(result)
      if (clear()) { setEditing(false); setNotice('预期签认已登记；仅限所选回归预期，问题未关闭。') }
    } catch (error) { setNotice('签认结果待确认，请先读取原签认结果；不会自动重发。' + (error instanceof ApiError ? ` ${error.message}` : '')) }
    finally { running.current = false; setBusy(false) }
  }
  const read = async () => {
    const requestId = pending?.request.requestId ?? knownId.trim()
    if (running.current || !id.safeParse(requestId).success) { setNotice('请输入有效的原签认请求标识。'); return }
    running.current = true; setBusy(true); setOutcome(null)
    try {
      const result = await request(path + '/' + encodeURIComponent(requestId) + '?' + scopeQuery(scope), receiptSchema)
      if (result.issueId !== issueId || result.request.requestId !== requestId || pending && !await matches(result, pending)) {
        setOutcome('changed'); setNotice('原签认登记与本地请求不一致，保留本地内容供核对。'); return
      }
      setReceipt(result)
      if (!pending || clear()) { setEditing(false); setNotice('已确认原签认登记；历史记录不代表来源当前仍有效，问题未关闭。') }
    } catch (error) {
      if (pending && error instanceof ApiError && error.status === 404 && error.code === 'management_issue_approval_not_found') {
        try {
          const current = await request('/report-issue-reviews?' + scopeQuery(scope) + '&issueId=' + encodeURIComponent(issueId),
            z.object({ items: z.array(z.object({ version: z.number(), review: z.object({ issueId: z.string(), status: z.string(), correctedVersions: z.array(correctedVersionSchema) }) })) }))
          const item = current.items.find(item => item.review.issueId === issueId)
          const unchanged = item?.version === pending.request.expectedIssueVersion && item.review.status === 'accepted' && same(item.review.correctedVersions, pending.correctedVersions)
          setOutcome(unchanged ? 'retry' : 'changed')
          setNotice(unchanged ? '原签认未登记，问题及修复版本未变。核对完整原请求后，可明确重提。' : '问题或修复版本已变化，保留原请求并重新核对。')
        } catch { setNotice('无法确认当前问题状态，请继续读取；不会重提签认。') }
      } else setNotice('原签认结果仍未知，请显式重试读取；不会重复签认。')
    } finally { running.current = false; setBusy(false) }
  }
  const submit = () => {
    if (!acknowledged || !selected.length || selected.some(id => !sources.some(item => item.regressionReceiptId === id)) || !reason.trim()) {
      setNotice('请为每条所选回归选取独立原文、填写推导，并明确勾选签认声明。'); return
    }
    try {
      const payload = approvalRequestSchema.parse({ requestId: crypto.randomUUID(), expectedIssueVersion: version,
        decision: 'approve_expected_values', regressionReceiptIds: selected, sources, approvalReason: reason })
      void post({ issueId, request: payload, correctedVersions })
    } catch { setNotice('来源摘录、推导或选择数量无效，请核对后提交。') }
  }
  const usable = receipt?.request.expectedIssueVersion === version && same(receipt.correctedVersions, correctedVersions)
  return <section aria-label="业务预期签认">
    <h3>业务预期签认</h3>
    <p>明确核对独立原始材料与所选回归的全部预期。签认不批准整份报告，不自动关闭问题。</p>
    {notice && <Alert type="info" title={notice} />}
    {pending && <Card size="small" title="待确认的原签认请求">
      <p>{pending.request.approvalReason}</p>
      <details><summary>原完整签认请求</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(pending, null, 2)}</pre></details>
      <Space wrap><Button ref={readButton} aria-label="读取原签认结果" loading={busy} onClick={() => void read()}>读取原签认结果</Button>
        {outcome === 'retry' && <Button disabled={disabled} loading={busy} onClick={() => void post(pending)}>确认重提原签认</Button>}
        {outcome && <Button disabled={busy} onClick={() => { if (clear()) { setEditing(false); setReceipt(null) } }}>保留正式记录，重新核对签认</Button>}
      </Space>
    </Card>}
    {!pending && <>
      <Button disabled={disabled || busy || !correctedVersions.length} onClick={() => { setEditing(true); setReceipt(null); setAcknowledged(false) }}>签认回归预期</Button>
      <Input aria-label="已有签认请求标识" placeholder="输入原签认请求标识，可只读恢复" maxLength={128} value={knownId} onChange={event => setKnownId(event.target.value)} />
      <Button disabled={!knownId.trim() || busy} onClick={() => void read()}>读取已有签认</Button>
    </>}
    {editing && !pending && <fieldset disabled={busy || disabled}>
      <legend>选择回归与独立预期来源</legend>
      {candidates.map(item => <div key={item.receiptId}>
        <Checkbox aria-label={`签认${item.request.caseId}的预期`} checked={selected.includes(item.receiptId)}
          disabled={item.status !== 'passed' || item.request.expectedIssueVersion !== version || selected.length >= 50 && !selected.includes(item.receiptId)}
          onChange={event => { setSelected(event.target.checked ? [...selected, item.receiptId] : selected.filter(id => id !== item.receiptId));
            if (!event.target.checked) { setSources(sources.filter(source => source.regressionReceiptId !== item.receiptId)); setPicking(null) } setAcknowledged(false) }}>
          {item.request.caseId} · {item.status !== 'passed' ? '原回归未通过' : item.request.expectedIssueVersion !== version ? '问题版本已变化' : '历史回归通过'}
        </Checkbox>
        {selected.includes(item.receiptId) && <>
          <p>原预期依据：{item.request.expectationReason}</p>
          {item.request.assertions?.map((assertion, index) => <p key={assertion.factId}>分组{index + 1}预期：{assertion.expectedStatus === 'computed' ? `${assertion.expectedValue} ${assertion.unit}` : '不可计算'}</p>)}
          {sources.map((source, index) => source.regressionReceiptId === item.receiptId && <div key={index}>
            <p>{source.title ?? source.documentId} · 修订 {source.revision} · {locationLabel(source.locator)}</p>
            <Input.TextArea aria-label={`来源摘录${index + 1}`} rows={3} maxLength={10000} value={source.quote} onChange={event => { setSources(sources.map((value, i) => i === index ? { ...value, quote: event.target.value } : value)); setAcknowledged(false) }} />
            <Button onClick={() => { setSources(sources.filter((_, i) => i !== index)); setAcknowledged(false) }}>移除此来源</Button>
          </div>)}
          <Button disabled={sources.length >= 100} onClick={() => setPicking(item.receiptId)}>选择独立原件</Button>
        </>}
      </div>)}
      {!candidates.length && <p>暂无已加载回归，请先登记并读取回归历史。</p>}
      {picking && <SourcePicker key={picking} scope={scope} issueId={issueId} onCancel={() => setPicking(null)} onChoose={source => {
        if (sources.some(item => item.regressionReceiptId === picking && item.documentId === source.documentId && item.revision === source.revision && same(item.locator, source.locator))) {
          setNotice('此回归已选择该原文位置，请直接核对已有摘录。'); return
        }
        setSources([...sources, { ...source, regressionReceiptId: picking }]); setPicking(null); setAcknowledged(false)
      }} />}
      <label>签认理由与独立推导<Input.TextArea aria-label="签认理由与独立推导" rows={3} maxLength={10000} value={reason} onChange={event => { setReason(event.target.value); setAcknowledged(false) }} /></label>
      <Checkbox aria-label="明确签认所选回归预期" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)}>我已核对所选回归的全部预期和独立原文，明确签认这些预期；不批准整份报告。</Checkbox>
      <p>已选 {selected.length} 条回归、{sources.length} 处来源；每条回归至少一处。</p>
      <Button type="primary" disabled={!acknowledged} loading={busy} onClick={submit}>确认签认并登记</Button>
    </fieldset>}
    {receipt && <div role="status">
      <p>签认人：{receipt.approvedByUsername} · {receipt.createdAt} · 仅签认回归预期。问题未关闭。</p>
      <p>历史签认尚未检查当前来源；用于关闭准备时会重验文件、审核和回归身份。</p>
      <Button disabled={!usable || disabled || busy || !!pending} onClick={() => onUse({ requestId: receipt.request.requestId, regressionReceiptIds: receipt.request.regressionReceiptIds })}>用于本次关闭准备检查</Button>
      {!usable && <p>该签认的问题版本或修复引用已变化，不能用于本次检查。</p>}
      <details><summary>签认请求标识</summary>{receipt.request.requestId}</details>
    </div>}
  </section>
}
