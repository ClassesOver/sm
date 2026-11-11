import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox } from 'antd'
import { z } from 'zod'
import { ApiError, identity, request } from '../../api/http'
import { BusinessApprovals, type ApprovalCandidate, type ApprovalChoice } from './business-approvals'
import { correctedVersionSchema } from './fix-versions'
import type { ResolutionPreparation } from './resolutions'

const issueSchema = z.object({ code: z.string(), message: z.string() })
const resultSchema = z.object({ issueId: z.string(), issueVersion: z.number().int().positive(), checkedAt: z.string(),
  regressionEvidenceReady: z.boolean(), businessApproval: z.enum(['not_performed', 'explicitly_approved']), issueClosed: z.literal(false),
  businessApprovalReady: z.boolean().optional(), businessApprovalCheck: z.object({ requestId: z.string().nullable(),
    status: z.enum(['not_selected', 'verified', 'unavailable']), issues: z.array(issueSchema), approvedByUsername: z.string().optional() }).optional(),
  issues: z.array(issueSchema), checks: z.array(z.object({ receiptId: z.string(), status: z.enum(['passed', 'failed']), issues: z.array(issueSchema) })),
  originalEvidenceReady: z.boolean().optional(), deliveryReady: z.boolean().optional(), factPresentationReady: z.boolean().optional(),
  originalChecks: z.array(z.object({ documentId: z.string(), title: z.string().optional(), revision: z.number().int().positive(), status: z.enum(['readable', 'unavailable']), issues: z.array(issueSchema) })).optional(),
  reportRelationships: z.array(z.object({ receiptId: z.string(), targetRunId: z.string(), targetBasisId: z.string(), parentBasisId: z.string(),
    status: z.enum(['verified', 'unverified']), deliveryVerified: z.boolean(), issues: z.array(issueSchema),
    factPresentationVerified: z.boolean().optional(), coveredFactIds: z.array(z.string()).optional(), missingFactIds: z.array(z.string()).optional(),
    contentIssues: z.array(issueSchema).optional(), deliveryIssues: z.array(issueSchema).optional(), outputRevision: z.number().int().positive().optional(),
    validationPassed: z.boolean().optional(), validationIssueCodes: z.array(z.string()).optional(),
    deliveryArtifacts: z.array(z.object({ format: z.enum(['pdf', 'docx', 'pptx', 'xlsx']), path: z.string(), size: z.number().int().positive(), sha256: z.string() })).optional() })).optional() })
export function CurrentRegressions({ scope, issueId, version, csrf, candidates, disabled, username, correctedVersions, onPreparation }: {
  scope: { database: string; companyId: string }; issueId: string; version: number; csrf: string; candidates: ApprovalCandidate[]; disabled: boolean;
  username: string; correctedVersions: z.infer<typeof correctedVersionSchema>[]
  onPreparation?: (value: ResolutionPreparation | null) => void
}) {
  const [selected, setSelected] = useState<string[]>([])
  const [approval, setApproval] = useState<ApprovalChoice | null>(null)
  const [result, setResult] = useState<z.infer<typeof resultSchema> | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const running = useRef(false)
  useEffect(() => {
    onPreparation?.(approval && result?.businessApprovalCheck?.requestId === approval.requestId ? {
      approvalRequestId: approval.requestId, regressionReceiptIds: selected,
      regressionReady: result.regressionEvidenceReady, originalReady: !!result.originalEvidenceReady,
      approvalReady: !!result.businessApprovalReady && result.businessApprovalCheck.status === 'verified',
      deliveryReady: !!result.deliveryReady, factsReady: !!result.factPresentationReady,
    } : null)
  }, [approval, selected, result, onPreparation])
  const check = async (includeOriginals = false) => {
    if (running.current || !selected.length || disabled) return
    running.current = true; setBusy(true); setResult(null); setNotice('')
    try {
      const response = await request('/report-issue-reviews/' + encodeURIComponent(issueId)
        + (includeOriginals ? '/resolution-evidence-check' : '/regression-evidence-check'),
        resultSchema, { method: 'POST', csrf, body: { ...identity(scope), expectedIssueVersion: version, regressionReceiptIds: selected,
          ...(includeOriginals && approval ? { businessApprovalRequestId: approval.requestId } : {}) } })
      if (response.issueId !== issueId || response.issueVersion !== version
          || response.checks.length !== selected.length || new Set(response.checks.map(item => item.receiptId)).size !== selected.length
          || response.checks.some(item => !selected.includes(item.receiptId))
          || response.regressionEvidenceReady !== (!response.issues.length && response.checks.every(item => item.status === 'passed' && !item.issues.length))
          || includeOriginals && (response.originalEvidenceReady === undefined || !response.originalChecks || !response.reportRelationships)
          || response.businessApproval === 'explicitly_approved' && (!includeOriginals || !approval || !response.businessApprovalReady
            || response.businessApprovalCheck?.status !== 'verified' || response.businessApprovalCheck.requestId !== approval.requestId
            || !!response.businessApprovalCheck.issues.length)
          || includeOriginals && approval && response.businessApprovalCheck?.requestId !== approval.requestId) {
        setNotice('检查响应与当前问题或所选回归不一致，请重新读取问题。'); return
      }
      setResult(response)
    } catch (error) {
      setNotice(error instanceof ApiError ? error.message : '检查结果未知，可显式重新检查；本操作没有写入裁定或关闭问题。')
    } finally { running.current = false; setBusy(false) }
  }
  return <section aria-label="关闭前回归证据检查" className="issue-current-regressions">
    <h3>当前回归证据</h3>
    <p>历史通过不保证快照仍可读。选择回归后重新检查当前文件身份、修复覆盖与实际复算；本检查不写入裁定，也不批准关闭。</p>
    {candidates.map(item => <div key={item.receiptId}>
      <Checkbox aria-label={`检查${item.request.caseId}的当前证据`} checked={selected.includes(item.receiptId)}
        disabled={busy || disabled || item.status !== 'passed' || item.request.expectedIssueVersion !== version
          || selected.length >= 50 && !selected.includes(item.receiptId)}
        onChange={event => { setSelected(event.target.checked ? [...selected, item.receiptId] : selected.filter(id => id !== item.receiptId)); setResult(null); setApproval(null) }}>
        {item.request.caseId}{item.status === 'failed' ? ' · 原核验未通过' : item.request.expectedIssueVersion !== version ? ' · 问题版本已变化' : ' · 历史核验通过'}
      </Checkbox>
      <details><summary>回归记录标识</summary>{item.receiptId}</details>
    </div>)}
    <p>已选 {selected.length} 条，最多50条；历史翻页可继续选择。</p>
    <BusinessApprovals key={JSON.stringify([scope, issueId, version, correctedVersions])} scope={scope} issueId={issueId} version={version}
      csrf={csrf} username={username} correctedVersions={correctedVersions} candidates={candidates} disabled={disabled || busy}
      onUse={choice => { setApproval(choice); setSelected(choice.regressionReceiptIds); setResult(null); setNotice('已明确选择该签认及其精确回归集合；点击“检查原件与新报告关系”核对当前有效性。') }} />
    {approval && <p>已选择业务预期签认；更改回归选择会取消本次签认选择。<Button disabled={busy} onClick={() => { setApproval(null); setResult(null) }}>取消本次签认选择</Button></p>}
    <Button aria-label="检查所选回归的当前证据" aria-busy={busy} disabled={disabled || !selected.length} loading={busy} onClick={() => void check()}>检查所选回归的当前证据</Button>
    <Button aria-label="检查原件与新报告关系" aria-busy={busy} disabled={disabled || !selected.length} loading={busy} onClick={() => void check(true)}>检查原件与新报告关系</Button>
    {notice && <Alert type="warning" title={notice} />}
    {result && <div role="status">
      <Alert type={result.regressionEvidenceReady ? 'info' : 'warning'} title={result.regressionEvidenceReady
        ? '本次回归证据检查通过；仍须核对新报告处理和业务裁定。' : '当前回归证据尚不齐全'} />
      <p>检查时间：{result.checkedAt}。仅反映本次读取时的状态，关闭时须再次检查。</p>
      {result.issues.map((item, index) => <p key={index}>{item.message}（{item.code}）</p>)}
      {result.checks.map(item => <div key={item.receiptId}>
        <p>{item.status === 'passed' ? '当前证据可复核' : '当前证据不可用于关闭'}</p>
        {item.issues.map((issue, index) => <p key={index}>{issue.message}（{issue.code}）</p>)}
        <details><summary>检查对应回归</summary>{item.receiptId}</details>
      </div>)}
      {result.originalChecks && <div>
        <h3>业务原件当前状态</h3>
        <p>{result.originalEvidenceReady ? '所需原件本次可读，身份已核对。' : '所需原件尚不可全部核验。'}</p>
        {result.originalChecks.map(item => <div key={item.documentId + ':' + item.revision}>
          <p>{item.title ?? '业务原件'} · 修订 {item.revision} · {item.status === 'readable' ? '可读且身份匹配' : '不可读取或身份失配'}</p>
          {item.issues.map((issue, index) => <p key={index}>{issue.message}（{issue.code}）</p>)}
          <details><summary>原件登记标识</summary>{item.documentId}</details>
        </div>)}
      </div>}
      {result.reportRelationships && <div>
        <h3>新报告与原报告关系</h3>
        {result.reportRelationships.length === 0 && <p>尚无通过当前回归核验的目标，不能核对新报告关系。</p>}
        {result.reportRelationships.map(item => <div key={item.receiptId}>
          <p>{item.status === 'verified' ? '新依据父链已核对' : '尚无可信新报告父链'}</p>
          <p>{item.deliveryVerified ? `新报告修订 ${item.outputRevision} 的请求格式文件本次可读且身份匹配。` : '报告最终交付尚未核验；依据已登记不等于新报告已完成。'}</p>
          {item.deliveryArtifacts?.map(file => <p key={file.format}>{file.format.toUpperCase()} · 文件身份已核对</p>)}
          {item.deliveryIssues?.map((issue, index) => <p key={index}>{issue.message}（{issue.code}）</p>)}
          {item.factPresentationVerified !== undefined && <div>
            <p>{item.factPresentationVerified ? '回归计算的全部根指标事实已在本次正文或冻结附表中核对。' : '新报告尚未完整核对回归事实的正文或附表呈现。'}</p>
            {item.contentIssues?.map((issue, index) => <p key={index}>{issue.message}（{issue.code}）</p>)}
            <p>此项不证明业务解释、图表或全部导出内容一致，仍需业务签认。</p>
          </div>}
          {item.validationPassed === false && <p>原交付验收未通过；文件可读不代表验收或业务签认通过。</p>}
          {item.issues.map((issue, index) => <p key={index}>{issue.message}（{issue.code}）</p>)}
          <details><summary>新旧依据登记信息</summary><p>{item.parentBasisId} → {item.targetBasisId}</p><p>{item.targetRunId}</p></details>
        </div>)}
      </div>}
      {result.businessApprovalCheck?.issues.map((issue, index) => <p key={'approval-' + index}>{issue.message}（{issue.code}）</p>)}
      <p>{result.businessApproval === 'explicitly_approved'
        ? '所选回归预期的显式签认本次有效；不等于整报告批准，问题未关闭。'
        : approval ? '业务预期尚未取得本次有效签认，问题未关闭；报告下载不受本检查影响。'
          : '业务预期尚未签认，问题未关闭；报告下载不受本检查影响。'}</p>
    </div>}
  </section>
}
