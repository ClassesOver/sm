import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Form, Input, Modal, Select, Space } from 'antd'
import { z } from 'zod'
import { request } from '../../api/http'
import { formatLabels, formatOptions } from './format-labels'
import { PreferenceApprovalSummary, verificationReceiptSchema, type VerificationReceipt } from './preference-approval-summary'

const digest = z.string().regex(/^[0-9a-f]{64}$/)
const issue = z.object({ code: z.string(), message: z.string() })
const artifact = z.object({ filename: z.string(), mediaType: z.string(), size: z.number().int().nonnegative(), sha256: digest, base64: z.string() })
const formatResult = z.object({ status: z.string(), availability: z.string().optional(), artifact: artifact.nullable().optional(),
  pdf: artifact.nullable().optional(), readback: z.object({ status: z.string() }).optional(), provenance: z.unknown().optional(), issues: z.array(issue).default([]) })
const templateProvenanceSchema = z.object({ layoutSource: z.literal('uploaded_template'),
  contentSource: z.literal('frozen_report_markdown'), signatureSource: z.literal('current_draft'),
  generatedDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  template: z.object({ filename: z.string().min(1), size: z.number().int().nonnegative(), sha256: digest }),
  placement: z.enum(['declared_template_slot', 'semantic_template_slot', 'body_end']).optional().catch(undefined),
  signatureLayoutSource: z.enum(['template', 'generated_fallback']).optional().catch(undefined),
  templateSampleStatus: z.enum(['replaced', 'cleared', 'preserved_for_review', 'no_declared_slot']).optional().catch(undefined),
  signatureReadback: z.enum(['passed', 'failed', 'unverified']).optional().catch(undefined),
  bodyRepresentation: z.enum(['frozen_markdown_text', 'native_docx_blocks', 'pdf_text_sample']),
  richDocumentProjection: z.enum(['unverified', 'structure_verified', 'sample_only']) }).refine(value =>
    ({ frozen_markdown_text: 'unverified', native_docx_blocks: 'structure_verified', pdf_text_sample: 'sample_only' })[value.bodyRepresentation] === value.richDocumentProjection)
const report = z.object({ reportId: z.string().min(1), revision: z.number().int().positive() })
const resultSchema = z.object({ draftVersion: z.number().int().positive(), contentHash: digest, status: z.string(), canApply: z.literal(false),
  formats: z.object({ md: formatResult, xlsx: formatResult, pptx: formatResult, pdf: formatResult, word: formatResult }),
  issues: z.array(issue).default([]), report, bindingHash: digest, bindingValid: z.boolean(), verificationReceipt: z.unknown().optional() })
const challenge = z.object({ handoffToken: z.string().regex(/^[A-Za-z0-9_-]{32,128}$/), expiresAt: z.string().min(1) })
const bootstrap = z.object({ csrfToken: z.string().min(1) })
const endpoint = '/configuration/preferences/report-verification'
const verificationRecordSchema = verificationReceiptSchema.extend({
  createdAt: z.string().datetime({ offset: true }),
  draft: z.object({ version: z.number().int().positive(), contentHash: digest }),
  report: z.object({ reportId: z.string().min(1), revision: z.number().int().positive() }),
  assessment: z.object({ status: z.string(), canApply: z.boolean(), missingRequirementCount: z.number().int().nonnegative() }),
})
const verificationRecordsSchema = z.array(verificationRecordSchema).max(20)
const templateSampleLabels = { replaced: '声明样例已替换', cleared: '声明样例已清除',
  preserved_for_review: '声明样例保留待核对', no_declared_slot: '未声明落款槽' }
const semanticTemplateSampleLabels = { ...templateSampleLabels, replaced: '语义识别样例已替换', cleared: '语义识别样例已清除',
  preserved_for_review: '语义识别样例保留待核对', no_declared_slot: '无可确认语义样例' }
type Artifact = z.infer<typeof artifact>
type VerificationRecord = z.infer<typeof verificationRecordSchema>

export function reportVerificationTarget(value: string) {
  const input = value.trim(), invalid = () => new Error('请输入同源报告修订地址，例如 /reports/v1/editor/报告标识/2；不能使用打开链接、原生编辑器或带查询参数的地址。')
  if (/[\\\u0000-\u0020\u007f]/.test(input)) throw invalid()
  const match = /^(?:https?:\/\/[^/?#]+)?(\/reports\/v1\/editor\/([^/?#]+)\/([1-9]\d*))$/.exec(input)
  if (!match) throw invalid()
  let url: URL, reportId: string
  try { url = new URL(input, location.origin); reportId = decodeURIComponent(match[2]) } catch { throw invalid() }
  const revision = Number(match[3])
  if (url.origin !== location.origin || url.username || url.password || url.search || url.hash || url.pathname !== match[1]
    || !Number.isSafeInteger(revision) || reportId.length > 256 || /[\\/?#%\u0000-\u0020\u007f]/.test(reportId)
    || ['open', 'assets', 'native', '.', '..'].includes(reportId.toLowerCase())) throw invalid()
  return { reportId, revision, api: match[1] + '/api/preference-verification' }
}

async function reportRequest<T>(path: string, schema: z.ZodType<T>, signal: AbortSignal, csrf?: string, body?: unknown): Promise<T> {
  // 报告Cookie只随实际路径发送；浏览器为同源POST提供Origin，不借管理请求的登出处理。
  const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
    cache: 'no-store', redirect: 'error', signal, headers: body === undefined ? {} : { 'content-type': 'application/json', 'x-csrf-token': csrf! },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
  let payload: unknown
  try { payload = await response.json() } catch { throw new Error('报告接口响应无法读取，请重新打开报告后重试。') }
  if (!response.ok) {
    const parsed = z.object({ detail: z.union([z.string(), z.object({ message: z.string().optional(), code: z.string().optional() })]).optional(),
      message: z.string().optional() }).safeParse(payload)
    const detail = parsed.success ? parsed.data.detail : undefined
    throw new Error((typeof detail === 'string' ? detail : detail?.message) || (parsed.success && parsed.data.message)
      || (response.status === 401 ? '报告会话已失效，请先在当前浏览器重新打开此修订。' : '无法使用此报告，请核对当前修订的完整编辑权限。'))
  }
  const parsed = schema.safeParse(payload)
  if (!parsed.success) throw new Error('报告接口响应身份不完整，请重新打开报告后重试。')
  return parsed.data
}

export async function verifiedReportArtifactBytes(value: Artifact) {
  const bytes = Uint8Array.from(atob(value.base64), char => char.charCodeAt(0))
  if (bytes.length !== value.size) throw new Error('产物身份核验失败：文件大小与回执不一致。')
  const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(byte => byte.toString(16).padStart(2, '0')).join('')
  if (hash !== value.sha256) throw new Error('产物身份核验失败：SHA256 与回执不一致。')
  return bytes
}

export function PreferenceReportVerification({ format, version, contentHash, csrf, disabled, effectiveRevision = 0, onApplied }: {
  format: string; version: number; contentHash: string; csrf: string; disabled: boolean; effectiveRevision?: number; onApplied?: () => Promise<void> | void
}) {
  const [open, setOpen] = useState(false), [address, setAddress] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [result, setResult] = useState<z.infer<typeof resultSchema> | null>(null)
  const [receipts, setReceipts] = useState<VerificationReceipt[]>([])
  const [availableRecords, setAvailableRecords] = useState<VerificationRecord[]>([])
  const [loadingRecords, setLoadingRecords] = useState(false)
  const [recordsLoaded, setRecordsLoaded] = useState(false)
  const [resultFormat, setResultFormat] = useState(format === 'common' ? 'md' : format)
  const generation = useRef(0), abort = useRef<AbortController | null>(null)
  const identity = `${version}:${contentHash}:${format}:${disabled}`, latest = useRef(identity)
  latest.current = identity
  useEffect(() => {
    generation.current++; abort.current?.abort(); setResult(null); setError(''); setBusy(false)
    setAvailableRecords([]); setLoadingRecords(false); setRecordsLoaded(false)
    setResultFormat(format === 'common' ? 'md' : format)
    return () => { generation.current++; abort.current?.abort() }
  }, [format, version, contentHash, disabled])
  useEffect(() => { setReceipts([]) }, [format, version, contentHash, disabled])
  function clear() { generation.current++; abort.current?.abort(); setResult(null); setError(''); setBusy(false); setLoadingRecords(false) }
  async function openDialog() {
    setOpen(true); clear(); setReceipts([]); setAvailableRecords([]); setRecordsLoaded(false)
    if (disabled) return
    const current = generation.current, selected = identity, controller = new AbortController()
    abort.current = controller; setLoadingRecords(true)
    try {
      const query = new URLSearchParams({ expectedVersion: String(version), expectedHash: contentHash })
      const records = await request(`${endpoint}/results?${query}`, verificationRecordsSchema, { signal: controller.signal })
      if (current === generation.current && selected === latest.current && !controller.signal.aborted) {
        setAvailableRecords(records); setRecordsLoaded(true)
      }
    } catch (reason) {
      if (current === generation.current && selected === latest.current && !controller.signal.aborted)
        setError((reason as Error).message)
    } finally {
      if (current === generation.current && selected === latest.current) setLoadingRecords(false)
    }
  }
  function selectRecord(record: VerificationRecord, checked: boolean) {
    const receipt = { id: record.id, contentHash: record.contentHash, contractHash: record.contractHash,
      executorManifestHash: record.executorManifestHash, expiresAt: record.expiresAt }
    setReceipts(current => checked
      ? current.some(item => item.id === receipt.id) || current.length >= 20 ? current : [...current, receipt]
      : current.filter(item => item.id !== receipt.id))
  }
  async function run() {
    if (disabled || busy) return
    clear()
    let target: ReturnType<typeof reportVerificationTarget>
    try { target = reportVerificationTarget(address) } catch (reason) { setError((reason as Error).message); return }
    const current = ++generation.current, selected = identity, controller = new AbortController()
    abort.current = controller
    const active = () => current === generation.current && selected === latest.current && !controller.signal.aborted
    setBusy(true)
    try {
      const created = await request(endpoint, challenge, { method: 'POST', csrf, signal: controller.signal, body: { expectedVersion: version, expectedHash: contentHash } })
      if (!active()) return
      const editor = await reportRequest(target.api, bootstrap, controller.signal)
      if (!active()) return
      const confirmed = await reportRequest(target.api, report, controller.signal, editor.csrfToken, { handoffToken: created.handoffToken })
      if (!active()) return
      if (confirmed.reportId !== target.reportId || confirmed.revision !== target.revision) throw new Error('报告关联响应与所选修订不一致，请重新打开报告。')
      const next = await request(endpoint + '/run', resultSchema, { method: 'POST', csrf, signal: controller.signal,
        body: { expectedVersion: version, expectedHash: contentHash, handoffToken: created.handoffToken } })
      if (!active()) return
      if (next.draftVersion !== version || next.contentHash !== contentHash || next.report.reportId !== target.reportId || next.report.revision !== target.revision)
        throw new Error('验收响应与所选草稿或报告修订不一致，请重新关联。')
      setResult(next)
      if (next.verificationReceipt !== undefined) {
        const parsed = verificationReceiptSchema.safeParse(next.verificationReceipt)
        if (!parsed.success) setError('服务器验收记录身份不完整；已生成产物保留，本次记录不能用于汇总。')
        else {
          const existing = receipts.find(item => item.id === parsed.data.id)
          if (existing && existing.contentHash !== parsed.data.contentHash) setError('服务器验收记录身份发生变化；已生成产物保留，请重新关联。')
          else if (!existing && receipts.length >= 20) setError('本次已关联20条验收记录；已生成产物保留，请关闭后重新选择所需报告。')
          else if (!existing) setReceipts([...receipts, parsed.data])
        }
      }
    } catch (reason) { if (active()) setError((reason as Error).message) }
    finally { if (active()) setBusy(false) }
  }
  async function download(value: Artifact) {
    const current = generation.current, selected = identity
    try {
      const bytes = await verifiedReportArtifactBytes(value)
      if (disabled || current !== generation.current || selected !== latest.current) return
      const url = URL.createObjectURL(new Blob([bytes], { type: value.mediaType })), link = document.createElement('a')
      link.href = url; link.download = value.filename.split(/[\\/]/).at(-1) || 'report'; link.click()
      const revoke = URL.revokeObjectURL; setTimeout(() => revoke(url), 1000)
    } catch (reason) { if (current === generation.current && selected === latest.current) setError((reason as Error).message) }
  }
  const displayFormat = format === 'common' ? resultFormat : format
  const selected = result?.formats[displayFormat as keyof z.infer<typeof resultSchema>['formats']]
  const templateSource = templateProvenanceSchema.safeParse(selected?.provenance)
  return <>
    <Button aria-label="实际报告验收" disabled={disabled} onClick={() => void openDialog()}>实际报告验收</Button>
    <Modal title="实际报告验收" open={open} footer={null} width={640} className="management-overlay" destroyOnHidden
      onCancel={() => { clear(); setReceipts([]); setAvailableRecords([]); setLoadingRecords(false); setOpen(false) }}>
      <p>先在当前浏览器打开具有完整编辑权限的报告，再复制该报告修订的编辑地址。</p>
      <p>验收使用已保存草稿和此报告的正式材料，不等于应用批准；全局应用需汇总批准后单独确认。</p>
      <section aria-label="已保存验收记录" style={{ borderTop: '1px solid #d8e3ed', margin: '12px 0', paddingTop: 10 }}>
        <strong>当前草稿的已保存验收记录</strong>
        {loadingRecords && <p role="status">正在读取已保存记录…</p>}
        {recordsLoaded && !loadingRecords && !error && availableRecords.length === 0 && <p>没有可恢复的验收记录。</p>}
        {availableRecords.map(record => <label key={record.id} style={{ display: 'flex', gap: 8, padding: '8px 0', borderBottom: '1px solid #e6edf2' }}>
          <input type="checkbox" aria-label={`选择 ${record.report.reportId} 修订 ${record.report.revision} 的验收记录`}
            checked={receipts.some(item => item.id === record.id)} onChange={event => selectRecord(record, event.target.checked)} />
          <span>{record.report.reportId} · 修订 {record.report.revision} · {new Date(record.createdAt).toLocaleString()} ·
            {record.assessment.canApply ? '完整通过' : `未完成 · ${record.assessment.missingRequirementCount} 项缺口`}</span>
        </label>)}
      </section>
      <Form layout="vertical" onFinish={() => void run()}>
        <Form.Item label="已打开的报告修订地址"><Input aria-label="已打开的报告修订地址" autoComplete="off" disabled={disabled || busy}
          value={address} placeholder="/reports/v1/editor/报告标识/2" onChange={event => { clear(); setAddress(event.target.value) }} /></Form.Item>
        <Button aria-label="关联并验收报告" htmlType="submit" type="primary" disabled={disabled || busy} loading={busy}>关联并验收报告</Button>
      </Form>
      {disabled && <p>草稿有未保存修改或正在保存，请先保存并回读最新草稿。</p>}
      {busy && <p role="status">正在核对报告授权并执行真实材料验收，请稍候…</p>}
      {error && <Alert type="error" showIcon title={error} />}
      {result && <section aria-label="实际报告验收结果" style={{ marginTop: 16, overflowWrap: 'anywhere' }}>
        <Alert showIcon type={result.status === 'passed' && result.bindingValid ? 'success' : 'warning'}
          title={result.status === 'passed' && result.bindingValid ? '报告材料验收通过，仍未获应用批准。' : '报告材料验收未通过或尚未完成。'} />
        <p>报告 {result.report.reportId} · 修订 {result.report.revision} · 草稿 v{result.draftVersion}</p>
        {!result.bindingValid && <p>绑定复核未通过；仅保留服务器本次返回的已授权产物。</p>}
        {format === 'common' && <Form.Item label="验收结果格式"><Select aria-label="验收结果格式" value={resultFormat}
          options={formatOptions.map(item => ({ value: item.key, label: item.label }))}
          onChange={next => { generation.current++; abort.current?.abort(); setResultFormat(next); setError('') }} /></Form.Item>}
        <p>当前格式：{formatLabels[displayFormat] || displayFormat} · {selected?.status === 'passed' && result.bindingValid ? '当前格式验收通过' : selected?.status === 'failed' ? '验收未通过' : '验收未完成'}</p>
        {selected?.readback && <p>独立回读：{selected.provenance !== undefined && selected.readback.status === 'passed'
          ? templateSource.success ? '模板局部回读通过，完整验收尚未完成' : '模板来源待复核'
          : ({ passed: '通过', failed: '未通过', unavailable: '不可用' } as Record<string, string>)[selected.readback.status] || '尚未完成'}</p>}
        {selected?.provenance !== undefined && (templateSource.success ? <details aria-label="模板排版来源">
          <summary>模板排版来源与核验范围</summary>
          <p>布局：上传模板 {templateSource.data.template.filename.split(/[\\/]/).at(-1)}</p>
          <p>正文与标题：当前修订冻结成稿；{templateSource.data.richDocumentProjection === 'structure_verified'
            ? '原生标题、列表、表格与图片已按冻结正文独立核对。'
            : templateSource.data.richDocumentProjection === 'sample_only'
              ? 'PDF 可见文字已抽样核对，原生对象结构尚未验证。'
              : '富文档转换尚未验证，请核对实际文件。'}</p>
          <p>落款：本次已保存草稿；冻结日期：{templateSource.data.generatedDate}</p>
          <p>落款生成位置（生成回执）：{templateSource.data.placement === 'declared_template_slot' ? '模板声明的落款槽'
            : templateSource.data.placement === 'semantic_template_slot' ? '语义识别位置（模型判断）'
            : templateSource.data.placement === 'body_end' ? '正文末尾回退' : '待复核'}</p>
          <p>落款排版（生成回执）：{templateSource.data.signatureLayoutSource === 'template' ? '模板原有排版'
            : templateSource.data.signatureLayoutSource === 'generated_fallback' ? '新增回退排版' : '待复核'}</p>
          <p>{templateSource.data.placement === 'semantic_template_slot' ? '语义识别样例处理' : '声明样例处理'}（生成回执）：{templateSource.data.templateSampleStatus
            ? (templateSource.data.placement === 'semantic_template_slot' ? semanticTemplateSampleLabels : templateSampleLabels)[templateSource.data.templateSampleStatus] : '待复核'}</p>
          <p>落款内容独立回读：{templateSource.data.signatureReadback === 'passed' ? '通过（不含完整布局）'
            : templateSource.data.signatureReadback === 'failed' ? '未通过' : '尚未核验'}</p>
          <p>完整布局尚未核验；未声明的模板样例尚未评估。</p>
        </details> : <Alert type="warning" showIcon title="模板来源回执不完整，版式与来源仍需复核" />)}
        {[...result.issues, ...(selected?.issues || [])].map((item, index) => <Alert key={index} type="warning" showIcon title={item.message} />)}
        <Space wrap style={{ marginTop: 12 }}>
          {selected?.artifact && <Button aria-label="读取当前格式验收产物" onClick={() => void download(selected.artifact!)}>读取当前格式验收产物</Button>}
          {selected?.pdf && <Button aria-label="读取当前格式 PDF" onClick={() => void download(selected.pdf!)}>读取当前格式 PDF</Button>}
        </Space>
      </section>}
      {!!receipts.length && <PreferenceApprovalSummary receipts={receipts} version={version} contentHash={contentHash} csrf={csrf}
        disabled={disabled || busy} effectiveRevision={effectiveRevision} onApplied={onApplied} />}
    </Modal>
  </>
}
