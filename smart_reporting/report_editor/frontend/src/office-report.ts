import { expireOfficeSession, officeCsrf, officeRequest, OfficeRequestError } from './office-client'
import type { OfficeSpace } from './office-client'

type ReportFormat = 'docx' | 'xlsx' | 'pptx' | 'pdf'

type ReportIssue = { message?: string; details?: { validationIssues?: ReportIssue[] } }
type ReportPause = { runId: string; retryCount: number }

const pauseIds = new Map<string, string>()

function rememberPause(key: string, runId?: string) {
  if (runId) pauseIds.set(key, runId)
  else pauseIds.delete(key)
  try {
    if (runId) sessionStorage.setItem(key, runId)
    else sessionStorage.removeItem(key)
  } catch { /* The current tab can still reopen the dialog. */ }
}

class ReportClarification extends Error {
  constructor(question: string, readonly pause: ReportPause) { super(question) }
}

type ReportReceipt = {
  reportId: string
  workflowFailure?: string
  word?: { downloadUrl: string }
  pdf?: { downloadUrl: string }
  xlsx?: { downloadUrl: string }
  pptx?: { downloadUrl: string }
  editor?: { openUrl: string }
  validation?: { ok?: boolean; issues?: ReportIssue[] }
  validationIssues?: ReportIssue[]
  sourceWarnings?: ReportIssue[]
  publicationGate?: { formalReleaseAllowed?: boolean; issues?: ReportIssue[]; warnings?: ReportIssue[] }
}

function reportLink(value: unknown): URL | undefined {
  if (typeof value !== 'string' || !value) return
  try {
    const url = new URL(value, window.location.origin)
    if (url.origin === window.location.origin && !url.username && !url.password && url.pathname.startsWith('/reports/v1/')) return url
  } catch { /* Ignore malformed links independently. */ }
}

function findWorkflowOutput<T>(value: unknown, read: (output: Record<string, unknown>) => T | undefined): T | undefined {
  if (!value || typeof value !== 'object') return
  const output = value as Record<string, unknown>
  const direct = read(output) ?? findWorkflowOutput(output.content, read) ?? findWorkflowOutput(output.step_output, read)
  if (direct !== undefined) return direct
  for (const steps of [output.step_results, output.step_requirements]) {
    if (!Array.isArray(steps)) continue
    for (const step of steps.slice().reverse()) {
      const result = findWorkflowOutput(step, read)
      if (result !== undefined) return result
    }
  }
}

export async function submitOfficeReport(space: string, message: string, format?: ReportFormat, sourceIds: string[] = []) {
  const csrf = officeCsrf()
  const response = await fetch('/workflows/enterprise-reporting-workflow-v1/runs', {
    method: 'POST',
    credentials: 'same-origin',
    redirect: 'error',
    headers: {
      'X-CSRF-Token': csrf,
      'X-Office-Workspace': space,
    },
    body: new URLSearchParams({ message: format || sourceIds.length ? JSON.stringify({prompt: message, deliveryFormat: format,
      sourceIds: sourceIds.length ? sourceIds : undefined}) : message, stream: 'false' }),
  })
  if (response.status === 401 && csrf === officeCsrf()) expireOfficeSession()
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result?.message === 'string' ? result.message : '无法提交报告。')
  return readReportResult(result)
}

function readReportResult(result: Record<string, unknown>) {
  const state = String(result?.status).toLowerCase()
  const readReceipt = (output: Record<string, unknown>) => typeof output.reportId === 'string' ? output as ReportReceipt : undefined
  if (state === 'error' || state === 'failed') {
    const published = findWorkflowOutput(result, output => {
      const report = readReceipt(output)
      if (report && [report.word, report.pdf, report.xlsx, report.pptx].some(artifact => {
        const url = reportLink(artifact?.downloadUrl)
        return url && /^\/reports\/v1\/(?:native\/)?download\/[^/]+\/[^/]+$/.test(url.pathname)
      })) return report
    })
    if (published) return {
      ...published, workflowFailure: typeof result.content === 'string' && result.content.trim()
        ? result.content.trim() : '报告流程未完成。',
    }
  }
  const report = findWorkflowOutput(result, readReceipt)
  if (state !== 'completed' || !report) {
    if (state === 'paused' && typeof result.run_id === 'string'
        && Array.isArray(result.step_requirements)) {
      const requirement = result.step_requirements.find(item => item?.step_id === 'normalize-report-request')
      const question = requirement?.step_output?.content?.clarificationQuestion
      if (typeof question === 'string' && question.trim() && Number.isInteger(requirement.retry_count)) {
        throw new ReportClarification(question, { runId: result.run_id, retryCount: requirement.retry_count })
      }
    }
    const question = findWorkflowOutput(result, output => typeof output.clarificationQuestion === 'string'
      ? output.clarificationQuestion.trim() || undefined : undefined)
    throw new Error(question ?? (typeof result?.content === 'string' ? result.content : '报告未完成，请核对报告要求和工作区的数据源授权。'))
  }
  return report
}

export function showOfficeReport(
  host: HTMLElement, space: OfficeSpace,
  onComplete: () => Promise<void>,
  user = '',
) {
  const key = `genoffice:report-pause:${JSON.stringify([user, space.id])}`
  const clarificationPath = (runId: string) => `/workspaces/${encodeURIComponent(space.id)}/reports/${encodeURIComponent(runId)}/clarification`
  const panel = document.createElement('dialog')
  panel.className = 'office-administration'
  panel.addEventListener('click', event => event.stopPropagation())
  const title = document.createElement('h2')
  title.textContent = '生成报告'
  const locationLabel = document.createElement('p')
  locationLabel.textContent = space.name
  const form = document.createElement('form')
  const prompt = document.createElement('textarea')
  prompt.required = true
  prompt.maxLength = 8000
  prompt.setAttribute('aria-label', '报告要求')
  prompt.placeholder = '描述报告主题、时间范围和分析要求'
  const format = document.createElement('select')
  format.setAttribute('aria-label', '交付格式')
  for (const [label, value] of [
    ['根据报告要求判断',''], ['Word（DOCX）','docx'], ['Excel（XLSX）','xlsx'],
    ['PowerPoint（PPTX）','pptx'], ['PDF','pdf'],
  ]) format.add(new Option(label, value))
  const start = document.createElement('button')
  start.type = 'submit'
  start.textContent = '生成'
  const newReport = document.createElement('button')
  newReport.type = 'button'
  newReport.textContent = '开始新报告'
  newReport.hidden = true
  newReport.onclick = () => {
    setPause()
    format.disabled = sources.disabled = false
    status.textContent = ''
    prompt.focus()
  }
  const close = document.createElement('button')
  close.type = 'button'
  close.textContent = '关闭'
  close.onclick = () => panel.close()
  const status = document.createElement('p')
  status.setAttribute('role', 'status')
  const links = document.createElement('div')
  const sources = document.createElement('fieldset')
  const legend = document.createElement('legend')
  legend.textContent = '数据源（未勾选时使用全部已授权来源）'
  sources.append(legend)
  sources.hidden = true
  const sourceNotice = document.createElement('p')
  sourceNotice.setAttribute('aria-live', 'polite')
  sourceNotice.textContent = '正在读取工作区数据源…'
  let hasAvailableSources = false
  let restoring = true
  let submitting = false
  let paused: ReportPause | undefined
  form.append(prompt, format, sources, sourceNotice, start, newReport)
  panel.append(title, locationLabel, form, status, links, close)
  panel.onclose = () => panel.remove()
  host.append(panel)
  panel.showModal()
  function updateSubmit() {
    start.disabled = restoring || submitting || (!paused && !hasAvailableSources)
    sourceNotice.hidden = Boolean(paused) || !sourceNotice.textContent
  }
  function setPause(value?: ReportPause, question?: string) {
    paused = value
    rememberPause(key, value?.runId)
    prompt.value = ''
    prompt.maxLength = value ? 2000 : 8000
    prompt.setAttribute('aria-label', value ? '补充说明' : '报告要求')
    prompt.placeholder = value ? '回答上方的澄清问题' : '描述报告主题、时间范围和分析要求'
    start.textContent = value ? '补充并继续' : '生成'
    newReport.hidden = !value
    format.hidden = Boolean(value)
    sources.hidden = Boolean(value) || sources.childElementCount === 1
    updateSubmit()
    if (question) status.textContent = question
  }
  async function restore(runId?: string) {
    start.disabled = prompt.disabled = format.disabled = sources.disabled = true
    status.textContent = '正在恢复报告…'
    try {
      type PendingReport = { pending: (ReportPause & {question: string}) | null }
      let current: PendingReport | undefined
      if (runId) {
        try { current = await officeRequest<PendingReport>(clarificationPath(runId)) }
        catch (error) {
          if (!(error instanceof OfficeRequestError) || error.status !== 404) throw error
        }
      }
      if (!current?.pending) current = await officeRequest<PendingReport>(`/workspaces/${encodeURIComponent(space.id)}/reports/pending`)
      const { pending } = current
      if (panel.open) {
        setPause(pending ?? undefined, pending?.question)
        if (!pending) status.textContent = ''
      }
    } catch (error) {
      if (panel.open) {
        if (error instanceof OfficeRequestError && error.status === 404) setPause()
        status.textContent = error instanceof Error ? error.message : '无法恢复报告。'
      }
    } finally {
      restoring = false
      prompt.disabled = false
      format.disabled = sources.disabled = Boolean(paused)
      updateSubmit()
      if (paused && panel.open) prompt.focus()
    }
  }
  let saved = pauseIds.get(key)
  try { saved ??= sessionStorage.getItem(key) ?? undefined } catch { /* Use in-memory state. */ }
  void restore(saved)
  void officeRequest<{items: {id: string; name?: string; available: boolean; reason?: string}[]}>(
    `/workspaces/${encodeURIComponent(space.id)}/data-sources`,
  ).then(result => {
    if (!panel.open) return
    const availableSources = result.items.filter(item => item.available)
    for (const source of availableSources) {
      const checkbox = document.createElement('input')
      checkbox.type = 'checkbox'
      checkbox.value = source.id
      const label = document.createElement('label')
      label.append(checkbox, document.createTextNode(source.name ?? source.id))
      sources.append(label)
    }
    sources.hidden = Boolean(paused) || sources.childElementCount === 1
    hasAvailableSources = availableSources.length > 0
    const unavailable = result.items.filter(item => !item.available)
      .map(item => `${item.name ?? item.id}：${item.reason ?? '暂不可用。'}`)
    sourceNotice.textContent = [
      ...(hasAvailableSources ? [] : ['当前工作区没有可用于报告的数据源。请联系管理员检查授权或连接配置。']),
      ...unavailable,
    ].join(' ')
  }).catch(error => {
    const reason = error instanceof Error ? error.message : '无法读取工作区数据源。'
    sourceNotice.textContent = `${reason} 请重新打开报告窗口重试。`
  }).finally(updateSubmit)
  form.onsubmit = async event => {
    event.preventDefault()
    const message = prompt.value.trim()
    if (!message || start.disabled) return
    const sourceIds = [...sources.querySelectorAll<HTMLInputElement>('input:checked')].map(input => input.value)
    if (sourceIds.length > 20) { status.textContent = '最多选择 20 个数据源。'; return }
    submitting = true
    updateSubmit()
    prompt.disabled = format.disabled = sources.disabled = newReport.disabled = true
    links.replaceChildren()
    status.textContent = paused ? '正在继续生成报告…' : '正在生成报告…'
    try {
      const report = paused ? readReportResult(await officeRequest<Record<string, unknown>>(
        clarificationPath(paused.runId),
        'POST', { feedback: message, retry_count: paused.retryCount },
      )) : await submitOfficeReport(space.id, message, (format.value || undefined) as ReportFormat | undefined, sourceIds)
      if (paused) setPause()
      if (panel.open) {
        const gate = report.publicationGate
        const issues = [
          ...(report.validation?.issues ?? []), ...(report.validationIssues ?? []),
          ...(gate?.issues ?? []), ...(gate?.warnings ?? []), ...(report.sourceWarnings ?? []),
        ]
        const reasons = new Set(issues.flatMap(issue => [issue.message,
          ...(issue.details?.validationIssues ?? []).map(detail => detail.message),
        ]).filter(message => typeof message === 'string' && message.trim()))
        const failed = report.validation?.ok === false || gate?.formalReleaseAllowed === false
        const summary = report.workflowFailure
          ? [report.workflowFailure, '已生成的文件仍可下载。', ...(failed ? ['验收未通过。'] : [])]
          : [failed ? '报告已生成，验收未通过。' : '报告已生成。']
        status.textContent = [...summary, ...reasons].join(' ')
        for (const [label, value] of [
          ['下载 Word', report.word?.downloadUrl], ['下载 PDF', report.pdf?.downloadUrl],
          ['下载 Excel', report.xlsx?.downloadUrl], ['下载 PowerPoint', report.pptx?.downloadUrl],
          ['打开报告', report.editor?.openUrl],
        ] as const) {
          const url = reportLink(value)
          if (!url) continue
          const link = document.createElement('a')
          link.href = url.href
          link.textContent = label
          link.target = '_blank'
          link.rel = 'noopener noreferrer'
          links.append(link, document.createTextNode(' '))
        }
      }
      try { await onComplete() }
      catch { if (panel.open) status.append(' 文件列表刷新失败，请返回工作区重试。') }
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : '报告生成失败。'
      if (error instanceof ReportClarification) {
        setPause(error.pause, error.message)
      }
    } finally {
      submitting = false
      prompt.disabled = newReport.disabled = false
      format.disabled = sources.disabled = Boolean(paused)
      updateSubmit()
      if (paused && panel.open) prompt.focus()
    }
  }
}
