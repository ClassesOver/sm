import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Radio, Space, Tag } from 'antd'
import { useInfiniteQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { ApiError, identity, request, scopeQuery } from '../../api/http'
import { AsyncState } from '../../components/common'
import { correctedVersionSchema } from './fix-versions'
import { CurrentRegressions } from './current-regressions'
import { IssueResolution, type ResolutionPreparation } from './resolutions'

const identitySchema = z.string().min(1).max(128).regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/)
const assertionSchema = z.object({ factId: identitySchema, expectedStatus: z.enum(['computed', 'unavailable']),
  expectedValue: z.string().regex(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/).nullable().default(null), unit: z.string().min(1).max(32),
  decimalPlaces: z.number().int().min(0).max(12).nullable().default(null), expectedIssueCodes: z.array(identitySchema).max(50).default([]),
}).refine(item => item.expectedStatus === 'computed' ? item.expectedValue !== null
  : item.expectedValue === null && item.decimalPlaces === null && item.expectedIssueCodes.length > 0)
const requestSchema = z.object({ requestId: identitySchema, expectedIssueVersion: z.number().int().positive(), caseId: identitySchema,
  targetRunId: z.string().min(1).max(256), targetReportRevision: z.string().min(1).max(256), calculationReceiptId: identitySchema,
  expectationReason: z.string().trim().min(1).max(10000), assertions: z.array(assertionSchema).min(1).max(200) })
const receiptSchema = z.object({ receiptId: identitySchema, issueId: identitySchema, request: requestSchema,
  correctedVersions: z.array(correctedVersionSchema), status: z.enum(['passed', 'failed']),
  verificationLevel: z.literal('snapshot_recomputed'), businessApproval: z.literal('not_performed'), createdAt: z.string(),
  comparisons: z.array(z.object({ assertion: assertionSchema, matches: z.boolean(), actual: z.object({ factId: identitySchema,
    value: z.string().nullable(), status: z.enum(['computed', 'unavailable']), unit: z.string(), issueCodes: z.array(z.string()) }) })) })
const historySchema = z.object({ items: z.array(receiptSchema), nextCursor: z.string().nullable() })
const targetSchema = z.object({ targetRunId: z.string(), targetReportRevision: z.string(), calculationReceiptId: identitySchema,
  basisId: identitySchema, available: z.boolean(), reason: z.string(), goal: z.string().optional(), metricName: z.string().optional(),
  metricVersion: z.object({ metricId: z.string(), revision: z.number().int().positive() }).optional(),
  period: z.object({ start: z.string(), end: z.string() }).optional(),
  facts: z.array(z.object({ factId: identitySchema, unit: z.string(), dimensions: z.array(z.object({ dimensionId: z.string(),
    value: z.union([z.string(), z.number(), z.boolean(), z.null()]) })) })).max(200) })
const targetsSchema = z.object({ issueVersion: z.number().int().positive(), items: z.array(targetSchema), nextCursor: z.string().nullable() })
const pendingSchema = z.object({ issueId: identitySchema, request: requestSchema, correctedVersions: z.array(correctedVersionSchema) })
type Pending = z.infer<typeof pendingSchema>
type Receipt = z.infer<typeof receiptSchema>
type Target = z.infer<typeof targetSchema>
type Scope = { database: string; companyId: string }
type Issue = { version: number; resolutionRequestId?: string | null; review: { issueId: string; status: string; correctedVersions: z.infer<typeof correctedVersionSchema>[] } }
type Fields = { caseId: string; expectationReason: string; assertions: { expectedStatus?: 'computed' | 'unavailable';
  expectedValue?: string; decimalPlaces?: number | null; issueCodes?: string }[] }
const same = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)

function RegressionResult({ receipt }: { receipt: Receipt }) {
  return <Card size="small" title={<Space wrap><span>{receipt.request.caseId}</span>
    <Tag color={receipt.status === 'passed' ? 'blue' : undefined} className={receipt.status === 'failed' ? 'issue-regression-failed' : undefined}>{receipt.status === 'passed' ? '快照核验符合预期' : '快照核验不符合预期'}</Tag></Space>}>
    <p>预期依据：{receipt.request.expectationReason}</p>
    <p>本回归记录仅为机械核验，不包含后续业务签认或关闭裁定。</p>
    {receipt.comparisons.map(item => <div key={item.actual.factId} className="issue-regression-comparison">
      <p>{item.matches ? '符合' : '不符合'} · 单位 {item.assertion.unit}</p>
      <p>预期：{item.assertion.expectedStatus === 'computed' ? item.assertion.expectedValue : '不可计算'}
        {item.assertion.decimalPlaces === null ? '' : `（四舍五入到${item.assertion.decimalPlaces}位）`}
        {item.assertion.expectedIssueCodes.length ? ` · ${item.assertion.expectedIssueCodes.join('、')}` : ''}</p>
      <p>实际：{item.actual.status === 'computed' ? item.actual.value : '不可计算'} · {item.actual.unit}
        {item.actual.issueCodes.length ? ` · ${item.actual.issueCodes.join('、')}` : ''}</p>
      <details><summary>事实登记标识</summary>{item.actual.factId}</details>
    </div>)}
    <details><summary>核验登记与目标运行</summary><p>{receipt.receiptId}</p>
      <p>{receipt.request.targetRunId} · {receipt.request.targetReportRevision} · {receipt.request.calculationReceiptId}</p>
      <p>{receipt.createdAt}</p></details>
  </Card>
}

export function IssueRegressions({ scope, issue, username, csrf, disabled = false, onResolved }: {
  scope: Scope; issue: Issue; username: string; csrf: string; disabled?: boolean; onResolved?: () => void
}) {
  const path = '/report-issue-reviews/' + encodeURIComponent(issue.review.issueId)
  const cacheKey = 'management-issue-regression:' + JSON.stringify([username, scope.database, scope.companyId, issue.review.issueId])
  const [pending, setPending] = useState<Pending | null>(() => {
    try { return pendingSchema.parse(JSON.parse(sessionStorage.getItem(cacheKey) ?? 'null')) } catch { return null }
  })
  const [editing, setEditing] = useState(false)
  const [preparation, setPreparation] = useState<ResolutionPreparation | null>(null)
  const [target, setTarget] = useState<Target | null>(null)
  const [search, setSearch] = useState('')
  const [notice, setNotice] = useState('')
  const [outcome, setOutcome] = useState<'retry' | 'changed' | null>(null)
  const [result, setResult] = useState<Receipt | null>(null)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const readButton = useRef<HTMLButtonElement>(null)
  const [form] = Form.useForm<Fields>()
  const assertions = Form.useWatch('assertions', form) as Fields['assertions'] | undefined
  const allowed = !disabled && issue.review.status === 'accepted' && !!issue.review.correctedVersions.length
  const targets = useInfiniteQuery({ queryKey: ['issue-regression-targets', scope, issue.review.issueId, issue.version, search],
    enabled: editing && allowed && !pending, initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request(path + '/regression-targets?' + scopeQuery(scope) + '&q=' + encodeURIComponent(search)
      + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), targetsSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined })
  const history = useInfiniteQuery({ queryKey: ['issue-regressions', scope, issue.review.issueId],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request(path + '/regressions?' + scopeQuery(scope)
      + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), historySchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined })
  useEffect(() => { if (pending && !busy) readButton.current?.focus() }, [pending, busy])
  const clear = () => {
    try { sessionStorage.removeItem(cacheKey) } catch { setNotice('无法清除核验缓存，请保留原请求并检查会话存储。'); return false }
    setPending(null); setOutcome(null); return true
  }
  const matches = (receipt: Receipt, saved: Pending) => receipt.issueId === saved.issueId
    && same(receipt.request, saved.request) && same(receipt.correctedVersions, saved.correctedVersions)
  const post = async (saved: Pending) => {
    if (busyRef.current) return
    try { sessionStorage.setItem(cacheKey, JSON.stringify(pendingSchema.parse(saved))) }
    catch { setNotice('无法保存核验请求，请启用会话存储后再提交。'); return }
    busyRef.current = true; setBusy(true); setPending(saved); setOutcome(null)
    try {
      const receipt = await request(path + '/regressions', receiptSchema, { method: 'POST', csrf,
        body: { ...identity(scope), ...saved.request } })
      setResult(receipt)
      if (!matches(receipt, saved)) { setNotice('核验登记内容与本地请求不一致，请读取原结果核对。'); return }
      if (clear()) { setEditing(false); setTarget(null); setNotice('核验已登记，结果保留；问题仍待修复核验与业务签认。') }
      void history.refetch()
    } catch (error) {
      setNotice('核验登记结果待确认，请先读取原请求；不会自动重发。' + (error instanceof ApiError ? ` ${error.message}` : ''))
    } finally { busyRef.current = false; setBusy(false) }
  }
  const read = async () => {
    if (!pending || busyRef.current) return
    busyRef.current = true; setBusy(true); setOutcome(null)
    try {
      const response = await request(path + '/regressions?' + scopeQuery(scope) + '&requestId=' + encodeURIComponent(pending.request.requestId), historySchema)
      const receipt = response.items[0]
      if (receipt) {
        setResult(receipt)
        if (matches(receipt, pending)) {
          if (clear()) { setEditing(false); setTarget(null); setNotice('已确认原回归核验登记；业务预期尚未签认，问题未关闭。') }
          void history.refetch()
        } else { setOutcome('changed'); setNotice('原请求已有不同登记内容，请对照本地预期与正式记录核对；不能覆盖原结果。') }
        return
      }
      const current = await request('/report-issue-reviews?' + scopeQuery(scope) + '&issueId=' + encodeURIComponent(pending.issueId),
        z.object({ items: z.array(z.object({ version: z.number(), review: z.object({ issueId: z.string(), status: z.string(),
          correctedVersions: z.array(correctedVersionSchema) }) })) }))
      const original = current.items.find(item => item.review.issueId === pending.issueId)
      const unchanged = original?.version === pending.request.expectedIssueVersion && original.review.status === 'accepted'
        && same(original.review.correctedVersions, pending.correctedVersions)
      setOutcome(unchanged ? 'retry' : 'changed')
      setNotice(unchanged ? '原核验尚未登记，问题和修复版本未变。核对完整预期后，可显式提交同一原请求。'
        : '问题或修复版本已变化。保留本地预期供核对，请刷新问题并重新选择目标。')
    } catch { setNotice('原核验结果仍未知，请显式重试读取；不会提交新核验。') }
    finally { busyRef.current = false; setBusy(false) }
  }
  const finish = (values: Fields) => {
    if (!target || !allowed || targets.data?.pages.some(page => page.issueVersion !== issue.version)) return
    try {
      const payload = requestSchema.parse({ requestId: crypto.randomUUID(), expectedIssueVersion: issue.version,
        caseId: values.caseId, expectationReason: values.expectationReason, targetRunId: target.targetRunId,
        targetReportRevision: target.targetReportRevision, calculationReceiptId: target.calculationReceiptId,
        assertions: target.facts.map((fact, index) => {
          const item = values.assertions[index]
          if (item.expectedStatus === 'computed' && item.decimalPlaces != null
            && (item.expectedValue?.split('.')[1] ?? '').replace(/0+$/, '').length > item.decimalPlaces) {
            throw Error('预期值超过比较精度')
          }
          return { factId: fact.factId, unit: fact.unit, expectedStatus: item.expectedStatus,
            expectedValue: item.expectedStatus === 'computed' ? item.expectedValue?.trim() : null,
            decimalPlaces: item.expectedStatus === 'computed' ? item.decimalPlaces ?? null : null,
            expectedIssueCodes: item.expectedStatus === 'unavailable' ? (item.issueCodes ?? '').split(/[,，]/).map(code => code.trim()).filter(Boolean) : [] }
        }) })
      void post({ issueId: issue.review.issueId, request: payload, correctedVersions: issue.review.correctedVersions })
    } catch { setNotice('请为全部分组填写明确预期；数值使用普通十进制，不可计算时须填写原因标识。') }
  }
  return <Card title="回归核验与历史" className="issue-regressions" size="small">
    <p>只读已登记快照并复算，不重新查询业务库、不生成新报告。预期须来自独立原始材料；通过不等于业务签认或问题解决。</p>
    {notice && <Alert type="info" title={notice} />}
    {pending && <Card size="small" title="待确认的原回归请求">
      <p>{pending.request.caseId} · {pending.request.expectationReason}</p>
      <details><summary>原完整请求与修复版本</summary><pre>{JSON.stringify(pending, null, 2)}</pre></details>
      <Space wrap><Button ref={readButton} onClick={() => void read()} loading={busy}>读取原回归结果</Button>
        {outcome === 'retry' && <Button onClick={() => void post(pending)} disabled={disabled} loading={busy}>确认重新提交原核验</Button>}
        {outcome && <Button disabled={busy} onClick={() => { if (clear()) { setEditing(false); setTarget(null); setNotice('已保留正式记录，请刷新问题后重新核对；新核验使用新请求身份。') } }}>保留正式记录，重新核对</Button>}
      </Space>
    </Card>}
    {!pending && <Button onClick={() => { setEditing(true); setTarget(null); setResult(null) }} disabled={!allowed || busy}>新建回归核验</Button>}
    {!allowed && <p>先采纳问题并关联正式修复版本，裁定结果待确认时先读回核对。</p>}
    {editing && !pending && allowed && <>
      <Input.Search aria-label="搜索回归目标" placeholder="按报告目标或运行标识搜索" maxLength={128} enterButton="搜索计算" allowClear onSearch={setSearch} />
      <AsyncState loading={targets.isPending} error={targets.error} retry={() => void targets.refetch()}>
        {targets.data?.pages.some(page => page.issueVersion !== issue.version) && <Alert type="warning" title="问题版本已变化，请刷新问题并重新打开。" />}
        {targets.data?.pages.flatMap(page => page.items).map(item => <Card size="small" key={item.basisId + ':' + item.calculationReceiptId}>
          <p>{item.metricName ?? '已登记计算'}{item.metricVersion ? ` · 修订 ${item.metricVersion.revision}` : ''} · {item.goal}</p>
          {item.period && <p>{item.period.start} 至 {item.period.end}（结束日期不含） · {item.facts.length} 个分组事实</p>}
          {item.reason && <p>{item.reason}</p>}
          <details><summary>运行与计算登记</summary>{item.targetRunId} · {item.targetReportRevision} · {item.calculationReceiptId}</details>
          <Button disabled={!item.available || targets.data?.pages.some(page => page.issueVersion !== issue.version)} onClick={() => {
            setTarget(item); form.resetFields(); setNotice('请依据原始材料独立填写全部预期，实际值将在核验登记后展示。')
          }}>选择此计算</Button>
        </Card>)}
        {targets.data?.pages.every(page => !page.items.length) && <p>暂无匹配计算。先按正式修复版本生成新报告，再选择其已登记计算。</p>}
        {targets.hasNextPage && <Button loading={targets.isFetchingNextPage} onClick={() => void targets.fetchNextPage()}>加载更多计算</Button>}
      </AsyncState>
      {target && <Form id="issue-regression" name="issue-regression" form={form} layout="vertical" onFinish={finish}>
        <p>当前目标：{target.metricName} · {target.facts.length} 个分组。更换目标会清空本地预期。</p>
        <Form.Item name="caseId" label="反例标识" rules={[{ required: true, pattern: /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/, message: '使用字母、数字及_.:-，最多128字符。' }]}><Input placeholder="例如 budget-total" maxLength={128} /></Form.Item>
        <Form.Item name="expectationReason" label="独立预期依据" rules={[{ required: true, whitespace: true, max: 10000 }]}><Input.TextArea rows={3} placeholder="说明原始材料与独立计算过程，不直接复制实际结果。" maxLength={10000} /></Form.Item>
        {target.facts.map((fact, index) => <fieldset key={fact.factId}>
          <legend>分组 {index + 1}：{fact.dimensions.length ? fact.dimensions.map(item => `${item.dimensionId}=${item.value ?? '空'}`).join('、') : '总体'}</legend>
          <p>单位：{fact.unit}</p>
          <Form.Item name={['assertions', index, 'expectedStatus']} label="预期状态" rules={[{ required: true }]}>
            <Radio.Group options={[{ value: 'computed', label: '可计算' }, { value: 'unavailable', label: '不可计算' }]} />
          </Form.Item>
          {assertions?.[index]?.expectedStatus === 'computed' && <>
            <Form.Item name={['assertions', index, 'expectedValue']} label="独立预期值" rules={[{ required: true, pattern: /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/, message: '填写普通十进制数值，例如63.33。' }]}><Input inputMode="decimal" /></Form.Item>
            <Form.Item name={['assertions', index, 'decimalPlaces']} label="比较小数位（留空为精确比较）"><InputNumber min={0} max={12} precision={0} /></Form.Item>
          </>}
          {assertions?.[index]?.expectedStatus === 'unavailable' && <Form.Item name={['assertions', index, 'issueCodes']} label="预期不可计算原因标识（逗号分隔）" rules={[{ required: true, whitespace: true }]}><Input placeholder="例如 zero_denominator；不能用0代替不可计算。" /></Form.Item>}
          <details><summary>事实登记标识</summary>{fact.factId}</details>
        </fieldset>)}
        <Button type="primary" htmlType="submit" loading={busy}>确认快照核验并登记</Button>
      </Form>}
    </>}
    {result && !history.data?.pages.some(page => page.items.some(item => item.receiptId === result.receiptId)) && <RegressionResult receipt={result} />}
    <h3>本问题核验历史</h3>
    <Button onClick={() => void history.refetch()} loading={history.isFetching}>刷新核验历史</Button>
    <AsyncState loading={history.isPending} error={history.error} retry={() => void history.refetch()}>
      {history.data?.pages.flatMap(page => page.items).map(receipt => <RegressionResult key={receipt.receiptId} receipt={receipt} />)}
      {history.data?.pages.every(page => !page.items.length) && <p>尚无已登记核验。未通过的核验也会保留。</p>}
      {history.hasNextPage && <Button onClick={() => void history.fetchNextPage()} loading={history.isFetchingNextPage}>加载更多核验</Button>}
    </AsyncState>
    <CurrentRegressions key={issue.version + ':' + JSON.stringify(issue.review.correctedVersions)} scope={scope}
      issueId={issue.review.issueId} version={issue.version} csrf={csrf}
      username={username} correctedVersions={issue.review.correctedVersions}
      onPreparation={setPreparation}
      candidates={history.data?.pages.flatMap(page => page.items) ?? []} disabled={!allowed || !!pending || busy} />
    <IssueResolution scope={scope} issueId={issue.review.issueId} version={issue.version} username={username} csrf={csrf}
      correctedVersions={issue.review.correctedVersions} preparation={preparation} resolutionRequestId={issue.resolutionRequestId} disabled={!allowed || !!pending || busy} onResolved={onResolved} />
  </Card>
}
