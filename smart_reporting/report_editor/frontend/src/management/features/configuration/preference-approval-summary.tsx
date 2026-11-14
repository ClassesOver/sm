import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Space } from 'antd'
import { z } from 'zod'
import { request } from '../../api/http'
import { versionSchema } from './contracts'
import { formatLabels } from './format-labels'

const digest = z.string().regex(/^[0-9a-f]{64}$/)
export const verificationReceiptSchema = z.object({ id: z.string().uuid(), contentHash: digest, contractHash: digest,
  executorManifestHash: digest, expiresAt: z.string().datetime({ offset: true }) })
export type VerificationReceipt = z.infer<typeof verificationReceiptSchema>
const gapSchema = z.object({ requirementId: z.string(), reason: z.string(), message: z.string().optional(),
  format: z.string().optional(), scenario: z.string().optional(), path: z.string().optional(), missingDimensions: z.array(z.string()).default([]) })
const summarySchema = z.object({ id: z.string().uuid(), contentHash: digest, draft: z.object({ version: z.number().int().positive(), contentHash: digest }),
  contractVersion: z.number().int().positive(), contractHash: digest, executorManifestHash: digest,
  expiresAt: z.string().datetime({ offset: true }), status: z.string(), canApply: z.boolean(), missingRequirements: z.array(gapSchema) })
const requirementLabels: Record<string, string> = {
  'signature-content-and-layout': '落款内容与排版', 'template-binding-and-precedence': '模板落点与样式优先级',
  'markdown-semantic-transform': '文本报告语义转换', 'native-editable-role-style': '原生对象与文字样式',
  'paged-header-footer-and-numbering': '文档页眉页脚与页码', 'workbook-display-invariants': '电子表格数据与显示',
  'workbook-print-layout': '电子表格打印布局', 'slides-native-content-and-style': '演示文稿原生内容与样式',
  'pdf-accessible-quality': 'PDF质量与可访问性', 'freeze-history-and-download': '冻结历史与下载',
  'authorization-and-integrity': '授权与文件身份', 'nonblocking-artifact-delivery': '验收失败时保留产物',
  'maintenance-and-version-workflow': '维护与版本流程', 'system-configuration-boundary': '系统配置边界',
}
const reasonLabels: Record<string, string> = { implementation_missing: '要求的实现尚未完成', coverage_missing: '缺少完整场景证据',
  missing_evidence: '缺少验收证据', check_failed: '存在实际失败检查', binding_mismatch: '证据绑定不一致',
  unauthorized_evidence: '证据授权未通过', missing_binding: '缺少精确绑定', contract_hash_mismatch: '合同身份不一致' }
const dimensionLabels: Record<string, string> = { native: '原生对象回读', visual: '视觉验收', lifecycle: '版本与授权流程' }
type ApplyInput = { expectedVersion: number; expectedHash: string; expectedEffectiveRevision: number; approvalId: string; expectedApprovalHash: string }

export function PreferenceApprovalSummary({ receipts, version, contentHash, csrf, disabled, effectiveRevision, onApplied }: {
  receipts: VerificationReceipt[]; version: number; contentHash: string; csrf: string; disabled: boolean;
  effectiveRevision: number; onApplied?: () => Promise<void> | void
}) {
  const [summary, setSummary] = useState<z.infer<typeof summarySchema> | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [action, setAction] = useState<ApplyInput | null>(null)
  const [applied, setApplied] = useState<number | null>(null), [, tick] = useState(0)
  const generation = useRef(0), abort = useRef<AbortController | null>(null)
  const identity = `${version}:${contentHash}:${disabled}:${receipts.map(item => item.id + ':' + item.contentHash).join(',')}`
  const latest = useRef(identity); latest.current = identity
  useEffect(() => {
    generation.current++; abort.current?.abort(); setSummary(null); setBusy(false); setError(''); setAction(null); setApplied(null)
    return () => { generation.current++; abort.current?.abort() }
  }, [identity])
  useEffect(() => {
    if (!summary) return
    const timer = setTimeout(() => tick(value => value + 1), Math.max(0, Math.min(2147483647, Date.parse(summary.expiresAt) - Date.now() + 1)))
    return () => clearTimeout(timer)
  }, [summary])
  const expired = summary !== null && Date.parse(summary.expiresAt) <= Date.now()
  const ready = summary?.status === 'ready' && summary.canApply && summary.missingRequirements.length === 0 && !expired
  function begin() {
    abort.current?.abort(); const controller = new AbortController(), current = ++generation.current, selected = identity
    abort.current = controller; setBusy(true); setError('')
    return { controller, active: () => current === generation.current && selected === latest.current && !controller.signal.aborted }
  }
  async function prepare() {
    if (disabled || busy || !receipts.length) return
    const { controller, active } = begin(); setSummary(null); setAction(null); setApplied(null)
    try {
      const next = await request('/configuration/preferences/report-verification/prepare', summarySchema, {
        method: 'POST', csrf, signal: controller.signal, body: { expectedVersion: version, expectedHash: contentHash, evidenceIds: receipts.map(item => item.id) } })
      if (!active()) return
      if (next.draft.version !== version || next.draft.contentHash !== contentHash
        || receipts.some(item => item.contractHash !== next.contractHash || item.executorManifestHash !== next.executorManifestHash))
        throw new Error('汇总响应与当前草稿、合同或执行器不一致，请重新验收。')
      setSummary(next)
    } catch (reason) { if (active()) setError((reason as Error).message) }
    finally { if (active()) setBusy(false) }
  }
  async function apply() {
    if (!action || !ready || disabled || busy) return
    const { controller, active } = begin()
    try {
      const next = await request('/configuration/preferences/apply', versionSchema, { method: 'POST', csrf, signal: controller.signal, body: action })
      if (!active()) return
      if (next.revision !== action.expectedEffectiveRevision + 1 || next.draftVersion !== action.expectedVersion
        || next.contentHash !== action.expectedHash || next.approvalId !== action.approvalId)
        throw new Error('应用回执与确认内容不一致，尚未确认应用结果；可使用同一请求重试。')
      setApplied(next.revision); setAction(null)
      await onApplied?.()
    } catch (reason) { if (active()) setError((reason as Error).message) }
    finally { if (active()) setBusy(false) }
  }
  return <section aria-label="全局偏好验收汇总" style={{ borderTop: '1px solid #d8e3ed', marginTop: 16, paddingTop: 12 }}>
    <Space wrap><span>已关联 {receipts.length} 条验收记录</span><Button aria-label="汇总当前草稿验收" disabled={disabled || busy || !receipts.length} loading={busy && !action}
      onClick={() => void prepare()}>汇总当前草稿验收</Button></Space>
    <p>当前格式通过不等于全局批准；汇总按同一草稿检查全部格式和要求。</p>
    {error && <Alert type="error" showIcon title={error} />}
    {summary && <>
      <p>验收规则版本 {summary.contractVersion} · 草稿 v{summary.draft.version} · {ready ? '具备应用批准' : expired ? '批准记录已过期，请重新汇总' : '尚未具备全局应用批准'}</p>
      {!!summary.missingRequirements.length && <details><summary>查看 {new Set(summary.missingRequirements.map(item => item.requirementId)).size} 类要求的 {summary.missingRequirements.length} 项待验证项</summary>
        <ul style={{ maxHeight: 240, overflowY: 'auto', overflowWrap: 'anywhere', paddingInlineStart: 22 }}>
          {summary.missingRequirements.map((gap, index) => <li key={index} style={{ marginBottom: 10 }}>
            <strong>{requirementLabels[gap.requirementId] || gap.requirementId}</strong>{gap.format && ' · ' + (formatLabels[gap.format] || gap.format)}
            {(gap.path || gap.scenario) && <div>{gap.path || gap.scenario}</div>}
            <div>{gap.message || reasonLabels[gap.reason] || gap.reason}{gap.missingDimensions.length ? ' 缺少：' + gap.missingDimensions.map(item => dimensionLabels[item] || item).join('、') : ''}</div>
          </li>)}
        </ul>
      </details>}
      {ready && !applied && !action && <Button aria-label="应用已批准偏好" disabled={disabled || busy} onClick={() => setAction({
        expectedVersion: version, expectedHash: contentHash, expectedEffectiveRevision: effectiveRevision,
        approvalId: summary.id, expectedApprovalHash: summary.contentHash })}>应用已批准偏好</Button>}
      {action && !applied && <div role="group" aria-label="确认全局偏好应用"><p>确认将草稿 v{version} 应用为全局默认？仅影响后续新任务，已有报告与历史版本保持原样。</p>
        <Space wrap><Button aria-label="确认应用偏好" type="primary" disabled={disabled || busy || !ready} loading={busy} onClick={() => void apply()}>确认应用偏好</Button>
          <Button disabled={busy} onClick={() => setAction(null)}>继续检查</Button></Space></div>}
    </>}
    {applied !== null && <Alert type="success" showIcon title={'已应用为偏好版本 ' + applied + '，已核对服务器回执。'} />}
  </section>
}
