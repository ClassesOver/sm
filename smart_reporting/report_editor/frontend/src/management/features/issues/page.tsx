import React, { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Form, Input, Radio, Space, Table, Tag } from 'antd'
import { useInfiniteQuery, useMutation } from '@tanstack/react-query'
import { z } from 'zod'
import { useSession } from '../../app/session'
import { identity, request, scopeQuery } from '../../api/http'
import { AsyncState, PageHeader } from '../../components/common'
import { useScope } from '../scopes/context'
import { assetNames, correctedVersionSchema, FixVersions } from './fix-versions'
import { IssueRegressions } from './regressions'

const statuses = { open: '待处理', needs_evidence: '待补充证据', accepted: '已采纳，待修复', rejected: '未采纳', resolved: '已解决' }
const recordSchema = z.object({ basisId: z.string(), reportId: z.string(), revision: z.number().int().positive(),
  resolutionRequestId: z.string().nullable().optional(), version: z.number().int().positive(), review: z.object({ issueId: z.string(),
    status: z.enum(['open', 'needs_evidence', 'accepted', 'rejected', 'resolved']),
    category: z.string(), description: z.string(), objectRefs: z.array(z.string()), decisionReason: z.string(),
    correctedVersions: z.array(correctedVersionSchema).default([]),
  }), proposal: z.object({ changeSummary: z.string(), counterexample: z.string() }).nullable() })
const listSchema = z.object({ items: z.array(recordSchema), nextCursor: z.string().nullable() })
const decisionSchema = z.object({ expectedVersion: z.number().int().positive(),
  status: z.enum(['needs_evidence', 'accepted', 'rejected']), decisionReason: z.string().trim().min(1).max(10000),
  proposal: z.object({ changeSummary: z.string().trim().min(1).max(10000), counterexample: z.string().trim().min(1).max(10000) }).optional(),
  correctedVersions: z.array(correctedVersionSchema).max(50).optional(),
}).refine(value => value.status !== 'accepted' || value.proposal !== undefined)
const pendingSchema = z.object({ issueId: z.string().min(1).max(128), decision: decisionSchema,
  priorCorrectedVersions: z.array(correctedVersionSchema).default([]) })
type Issue = z.infer<typeof recordSchema>
type Pending = z.infer<typeof pendingSchema>
type Fields = { status: 'needs_evidence' | 'accepted' | 'rejected'; decisionReason: string; changeSummary?: string; counterexample?: string;
  correctedVersions?: z.infer<typeof correctedVersionSchema>[] }

export default function ReportIssues() {
  const scope = useScope()
  return scope ? <ScopedIssues key={JSON.stringify(scope)} scope={scope} /> : <>
    <PageHeader title="报告问题" description="选择组织后查看报告反馈与裁定。" />
    <Alert type="info" title="请先在顶栏选择组织。" />
  </>
}
function ScopedIssues({ scope }: { scope: { database: string; companyId: string } }) {
  const { state } = useSession()
  const key = 'management-report-decision:' + JSON.stringify([state.session?.username, scope.database, scope.companyId])
  const [pending, setPending] = useState<Pending | null>(() => {
    try { return pendingSchema.parse(JSON.parse(sessionStorage.getItem(key) ?? 'null')) } catch { return null }
  })
  const [selected, setSelected] = useState<Issue | null>(null)
  const [notice, setNotice] = useState('')
  const [checked, setChecked] = useState<Issue | null>(null)
  const [reading, setReading] = useState(false)
  const recoveryButton = useRef<HTMLButtonElement>(null)
  const [form] = Form.useForm<Fields>()
  const status = Form.useWatch('status', form)
  const query = useInfiniteQuery({ queryKey: ['report-issue-reviews', scope], initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => request('/report-issue-reviews?' + scopeQuery(scope)
      + (pageParam ? '&after=' + encodeURIComponent(pageParam) : ''), listSchema, { signal }),
    getNextPageParam: page => page.nextCursor ?? undefined,
  })
  const save = useMutation({ mutationFn: (value: Pending) => request('/report-issue-reviews/' + encodeURIComponent(value.issueId) + '/decision',
    recordSchema, { method: 'POST', csrf: state.session!.csrfToken, body: { ...identity(scope), ...value.decision } }), retry: false,
  })
  useEffect(() => {
    if (pending && !save.isPending) recoveryButton.current?.focus()
  }, [pending, save.isPending])
  const clearPending = () => {
    try { sessionStorage.removeItem(key) }
    catch { setNotice('无法更新裁定缓存，请检查会话存储。'); return false }
    setPending(null); setChecked(null); return true
  }
  const show = (item: Issue) => {
    setSelected(item)
    form.setFieldsValue({ status: 'needs_evidence', decisionReason: '', changeSummary: '', counterexample: '',
      correctedVersions: item.review.correctedVersions })
    setNotice('请核对原问题后裁定。采纳只登记候选改动，不发布规则或标记修复完成。')
  }
  const submit = async (value: Pending) => {
    try {
      sessionStorage.setItem(key, JSON.stringify(pendingSchema.parse(value)))
    } catch { setNotice('无法保存裁定身份，请启用会话存储后再提交。'); return }
    setPending(value); setChecked(null)
    try {
      const result = await save.mutateAsync(value)
      if (result.review.issueId !== value.issueId) { setNotice('返回问题身份不一致，请读取原裁定结果。'); return }
      setSelected(result)
      if (clearPending()) setNotice('裁定已登记。采纳不等于修复，正式规则仍须显式发布。')
      void query.refetch()
    } catch {
      setNotice('裁定结果待确认，请读取原问题核对版本及裁定内容；不会自动重发。')
    }
  }
  const readOriginal = async () => {
    if (!pending) return
    setReading(true); setChecked(null)
    try {
      const result = await request('/report-issue-reviews?' + scopeQuery(scope) + '&issueId=' + encodeURIComponent(pending.issueId), listSchema)
      const current = result.items.find(item => item.review.issueId === pending.issueId)
      if (!current) { setNotice('本组织未找到原问题，请保留裁定内容供核对；不重新创建问题。'); return }
      setChecked(current); setSelected(current)
      const same = current.version === pending.decision.expectedVersion + 1
        && current.review.status === pending.decision.status && current.review.decisionReason === pending.decision.decisionReason
        && JSON.stringify(current.review.correctedVersions) === JSON.stringify(pending.decision.correctedVersions ?? pending.priorCorrectedVersions)
        && (pending.decision.status !== 'accepted' || current.proposal?.changeSummary === pending.decision.proposal?.changeSummary
          && current.proposal?.counterexample === pending.decision.proposal?.counterexample)
      setNotice(same ? '已确认原裁定生效；采纳仍为待修复。'
        : current.version === pending.decision.expectedVersion ? '原问题版本未变化。核对原裁定后可明确重新提交同一内容。'
          : '问题已有其他裁定或更新，请对照原内容与当前版本重新核对，不自动覆盖。')
      if (same) clearPending()
    } catch { setNotice('原裁定结果仍未知，请显式重试读取；不会自动提交。') }
    finally { setReading(false) }
  }
  return <section className="management-report-issues">
    <PageHeader title="报告问题" description="核对报告反馈，保留裁定理由、候选改动与反例。采纳不等于修复。" />
    {notice && <Alert type="info" title={notice} />}
    {pending && <Card title="待确认的原裁定">
      <p>原记录版本 {pending.decision.expectedVersion} · {statuses[pending.decision.status]}</p>
      <p>裁定理由：{pending.decision.decisionReason}</p>
      {pending.decision.proposal && <><p>候选改动：{pending.decision.proposal.changeSummary}</p><p>核对反例：{pending.decision.proposal.counterexample}</p></>}
      {pending.decision.correctedVersions && <details><summary>原提交的修复版本（{pending.decision.correctedVersions.length}）</summary>
        {pending.decision.correctedVersions.map(ref => <p key={JSON.stringify(ref)}>{assetNames[ref.assetType]} · {ref.assetId} · {ref.revision ?? '不可变集合'}</p>)}
      </details>}
      <Space wrap>
        <Button ref={recoveryButton} onClick={() => void readOriginal()} loading={reading} disabled={save.isPending}>读取原裁定结果</Button>
        {checked?.version === pending.decision.expectedVersion && <Button onClick={() => void submit(pending)} loading={save.isPending} disabled={reading}>确认重新提交原裁定</Button>}
        {checked && checked.version !== pending.decision.expectedVersion && <Button disabled={save.isPending || reading} onClick={() => {
          if (clearPending()) show(checked)
        }}>按当前版本重新核对</Button>}
      </Space>
      <details><summary>问题登记信息</summary><p>{pending.issueId}</p></details>
    </Card>}
    <Card title="本组织报告反馈" extra={<Button onClick={() => void query.refetch()} loading={query.isFetching}>刷新列表</Button>}>
      <AsyncState loading={query.isPending} error={query.error} retry={() => void query.refetch()}>
        <Table<Issue> rowKey={item => item.review.issueId} pagination={false} scroll={{ x: 660, y: 420 }}
          dataSource={query.data?.pages.flatMap(page => page.items)} columns={[
            { title: '问题', render: (_, item) => item.review.description, width: 300 },
            { title: '报告修订', render: (_, item) => `修订 ${item.revision}`, width: 100 },
            { title: '状态', render: (_, item) => <Tag>{statuses[item.review.status]}</Tag>, width: 150 },
            { title: '操作', render: (_, item) => <Button disabled={!!pending || save.isPending} onClick={() => show(item)}>查看并裁定</Button>, width: 130 },
          ]} />
        {query.hasNextPage && <Button onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage}>加载更多问题</Button>}
      </AsyncState>
    </Card>
    {selected && <Card title="问题核对与裁定">
      <p>{selected.review.description}</p>
      <p>状态：{statuses[selected.review.status]} · 记录版本 {selected.version}</p>
      {selected.review.decisionReason && <p>当前裁定：{selected.review.decisionReason}</p>}
      {selected.proposal && <><p>候选改动：{selected.proposal.changeSummary}</p><p>核对反例：{selected.proposal.counterexample}</p></>}
      {!!selected.review.correctedVersions.length && <details>
        <summary>已关联正式修复版本，仍待回归与重算核验</summary>
        {selected.review.correctedVersions.map(ref => <p key={JSON.stringify(ref)}>
          {assetNames[ref.assetType]} · {ref.assetId}{ref.revision === null ? '' : ` · 修订 ${ref.revision}`}
        </p>)}
      </details>}
      <details><summary>报告与对象登记信息</summary><p>{selected.reportId} · 修订 {selected.revision} · {selected.review.issueId}</p><p>{selected.review.objectRefs.join('、')}</p></details>
      {!pending && !['resolved', 'rejected'].includes(selected.review.status) && <Form id="issue-decision" name="issue-decision" form={form} layout="vertical" onFinish={values => void submit({ issueId: selected.review.issueId,
        priorCorrectedVersions: selected.review.correctedVersions,
        decision: { expectedVersion: selected.version, status: values.status, decisionReason: values.decisionReason.trim(),
          ...(values.status === 'accepted' ? { proposal: { changeSummary: values.changeSummary!.trim(), counterexample: values.counterexample!.trim() },
            correctedVersions: values.correctedVersions ?? [] } : {}) } })}>
        <Form.Item name="status" label="裁定结果" rules={[{ required: true }]}><Radio.Group options={[
          { value: 'needs_evidence', label: '待补充证据' }, { value: 'accepted', label: '采纳，登记候选改动' }, { value: 'rejected', label: '不采纳' },
        ]} /></Form.Item>
        <Form.Item name="decisionReason" label="裁定理由" rules={[{ required: true, whitespace: true, max: 10000 }]}><Input.TextArea rows={3} maxLength={10000} /></Form.Item>
        {status === 'accepted' && <>
          <Form.Item name="changeSummary" label="候选改动" rules={[{ required: true, whitespace: true, max: 10000 }]}><Input.TextArea rows={3} maxLength={10000} /></Form.Item>
          <Form.Item name="counterexample" label="原始反例与预期结果" rules={[{ required: true, whitespace: true, max: 10000 }]}><Input.TextArea rows={3} maxLength={10000} /></Form.Item>
          <Form.Item name="correctedVersions" label="关联正式修复版本（可选）">
            <FixVersions key={selected.review.issueId} scope={scope} issueId={selected.review.issueId} />
          </Form.Item>
        </>}
        <Button type="primary" htmlType="submit" loading={save.isPending}>确认登记裁定</Button>
      </Form>}
      <p>修复版本、实际回归和重算处理尚未核验前，不能关闭为“已解决”。</p>
      <IssueRegressions key={selected.review.issueId} scope={scope} issue={selected} username={state.session!.username}
        csrf={state.session!.csrfToken} disabled={!!pending || save.isPending} onResolved={() => {
          const issueId = selected.review.issueId
          void request('/report-issue-reviews?' + scopeQuery(scope) + '&issueId=' + encodeURIComponent(issueId), listSchema)
            .then(result => {
              const current = result.items.find(item => item.review.issueId === issueId)
              if (current?.review.status === 'resolved') { setSelected(previous => previous?.review.issueId === issueId ? current : previous); setNotice('关闭已登记，当前问题状态已读回。'); void query.refetch() }
              else setNotice('已取得关闭回执，当前问题列表尚未确认，请刷新读取；不会重提关闭。')
            }).catch(() => setNotice('已取得关闭回执，问题状态读取失败，请显式刷新；不会重提关闭。'))
        }} />
    </Card>}
  </section>
}
