import type { ReportEditorClient, TraceValidation } from './api'
import { findEvidenceChartImage } from './evidence-location'
import { isExplanatoryUnverified } from './unverified-text'

// 与服务端 trace_sources.NOT_EVALUATED_REASONS 同一清单：静态图未做数组比对、未登记规格只是
// “未评估”，不说明来源被改动，不计入待复核；其余 unknown 与缺少核对结果仍计入。
const NOT_EVALUATED_REASONS = new Set([
  'static_image_not_evaluated', 'interactive_spec_unregistered', 'chart_unregistered', 'table_unregistered',
  'chart_semantics_unregistered', 'chart_fact_binding_unregistered', 'chart_arrays_unverified',
])

// 质量包里只是“系统无法自动判断”的诊断：范围未确认、派生运算未评估、排名上下文缺失、
// 表格/图表规格未登记。它们不是发现的问题，单独计为“未自动核对”，不计入语义待确认，
// 也不让状态栏变为待处理；原始诊断仍全部保留。
const UNEVALUATED_QUALITY_REASONS = new Set([
  ...NOT_EVALUATED_REASONS,
  'scope_unknown', 'scope_value_unknown', 'operation_semantics_not_evaluated',
  'ranking_context_unknown', 'table_registration_unavailable',
])

export function qualityIssueNotEvaluated(issue: { reasons?: string[] }): boolean {
  const reasons = issue.reasons ?? []
  return reasons.length > 0 && reasons.every(reason => UNEVALUATED_QUALITY_REASONS.has(reason))
}

type QualityIssue = NonNullable<TraceValidation['quality']>['issues'][number]

/** 已由来源核对计入待复核的诊断（数值、表格、图表本身已提示），不再重复计数。 */
function countedBySourceReview(result: TraceValidation): (issue: QualityIssue) => boolean {
  const subjects = new Map(result.subjects.map(subject => [subject.subjectId, subject]))
  const tables = new Map(result.tables?.map(table => [table.tableId, table]) ?? [])
  const charts = new Map(result.charts?.map(chart => [chart.chartId, chart]) ?? [])
  return issue => {
    const subject = issue.subjectId ? subjects.get(issue.subjectId) : undefined
    const table = issue.subjectId ? tables.get(issue.subjectId) : undefined
    const chart = issue.subjectId ? charts.get(issue.subjectId) : undefined
    return Boolean(
      (issue.code === 'assertion_support_unknown' && subject &&
        (subject.status !== 'valid' || (subject.warnings?.length ?? 0) > 0)) ||
      (issue.code === 'table_support_unknown' && table &&
        (table.dataCheck?.status === 'unknown' || table.cells.stale + table.cells.unbound > 0)) ||
      (['chart_support_unknown', 'chart_semantic_alignment_unknown'].includes(issue.code) && chart &&
        (chart.status !== 'valid' || chart.dataCheck?.status !== 'verified' || chart.semanticCheck?.status !== 'verified')),
    )
  }
}

/** 未自动核对的质量诊断条数：只作说明，不代表存在问题；已计入待复核的不重复计数。 */
export function notEvaluatedQualityCount(result: TraceValidation): number {
  const quality = result.quality
  if (!quality || quality.status !== 'evaluated') return 0
  const counted = countedBySourceReview(result)
  return quality.issues.filter(issue => qualityIssueNotEvaluated(issue) && !counted(issue)).length
}

export function checkNeedsReview(check: { status: string; reason?: string; reasons?: string[] } | undefined): boolean {
  if (!check) return true
  if (check.status === 'verified') return false
  const reasons = check.reasons ?? (check.reason ? [check.reason] : [])
  return check.status === 'conflicting' || reasons.length === 0 || !reasons.every(reason => NOT_EVALUATED_REASONS.has(reason))
}

export function sourceValidationIssueCount(result: TraceValidation): number {
  const warningSubjects = result.subjects.filter(
    (subject) => subject.status === 'valid' && (subject.warnings?.length ?? 0) > 0,
  ).length
  const table = result.tableSummary
  const tableChecks = result.tables?.filter(table => table.dataCheck !== undefined && checkNeedsReview(table.dataCheck) && table.cells.stale + table.cells.unbound === 0).length ?? 0
  const chartIssues = result.charts?.filter((chart) => chart.status !== 'valid' || checkNeedsReview(chart.dataCheck) || checkNeedsReview(chart.semanticCheck)).length ?? 0
  return result.summary.stale + result.summary.unbound + warningSubjects +
    (table ? table.stale + table.unbound + table.insertedRows + (table.copiedCells ?? 0) : 0) + chartIssues + tableChecks
}

/** Additional semantic work, keeping source availability and business support separate. */
export function semanticReviewGroupCount(result: TraceValidation): number {
  const quality = result.quality
  if (!quality || quality.status !== 'evaluated') return 0
  const pending = new Set<number>()
  const counted = countedBySourceReview(result)
  quality.issues.forEach((issue, index) => {
    // Already counted in the source review indicator, or only “not evaluated”; retain every raw issue.
    if (qualityIssueNotEvaluated(issue) || counted(issue)) return
    pending.add(index)
  })
  let count = 0
  const ledger = quality.warningLedger
  if (ledger && quality.inputSha256 && ledger.qualityInputSha256 === quality.inputSha256 &&
    ledger.originalIssueCount === quality.issues.length) {
    for (const group of ledger.groups) {
      const members = group.issueIndices.filter(index => pending.has(index))
      if (members.length) count++
      members.forEach(index => pending.delete(index))
    }
  }
  // Older/malformed worklists cannot hide diagnoses they do not cover.
  return count + pending.size
}

function numericalPlaceholderCount(visibleText: string): number {
  let count = 0
  for (const match of visibleText.matchAll(/待核实/g)) {
    if (!isExplanatoryUnverified(visibleText, match.index)) count++
  }
  return count
}

/** 状态栏溯源覆盖摘要：可溯源 x/y · 待复核 n · 待核实 n。只统计，不改变校验结论。 */
export function sourceCoverageSummary(result: TraceValidation, visibleText: string): { text: string; state: 'valid' | 'stale' | 'unknown' } {
  const warningSubjects = result.subjects.filter(subject => subject.status === 'valid' && (subject.warnings?.length ?? 0) > 0).length
  const table = result.tableSummary
  const charts = result.charts ?? []
  const total = result.summary.valid + result.summary.stale + result.summary.unbound +
    (table ? table.valid + table.stale + table.unbound : 0) + charts.length
  const uncheckedTableCells = result.tables?.filter(table => table.dataCheck?.status === 'unknown').reduce((sum, table) => sum + table.cells.valid, 0) ?? 0
  const traceable = result.summary.valid - warningSubjects + Math.max(0, (table?.valid ?? 0) - uncheckedTableCells) + charts.filter(chart => chart.status === 'valid' && chart.dataCheck?.status === 'verified' && chart.semanticCheck?.status === 'verified').length
  const issues = sourceValidationIssueCount(result)
  const unverified = result.reviewNotices !== undefined
    ? result.reviewNotices.filter(notice => notice.kind === 'numeric_unverified').reduce((sum, notice) => sum + notice.occurrences, 0)
    : numericalPlaceholderCount(visibleText)
  const reviewTexts = result.reviewNotices?.filter(notice => notice.kind === 'source_review').reduce((sum, notice) => sum + notice.occurrences, 0) ?? 0
  const contentWarnings = result.warnings?.length ?? 0
  const sourceFailures = result.sourceIssues?.length ?? 0
  const qualityFailed = result.quality?.status === 'failed'
  const semanticGroups = semanticReviewGroupCount(result)
  const notEvaluated = notEvaluatedQualityCount(result)
  const coverage = result.quality?.questionCoverage
  const hasQuestions = coverage?.required != null && coverage.required > 0
  const answerPending = Boolean(hasQuestions && coverage?.effectiveAnswerRate == null)
  const answerIncomplete = Boolean(hasQuestions && coverage && coverage.answered < coverage.required!)
  const text = [
    total ? `可溯源 ${traceable}/${total}` : '当前内容无精确来源绑定',
    issues ? `待复核 ${issues}` : '',
    unverified ? `待核实数值 ${unverified}` : '',
    reviewTexts ? `文字待确认 ${reviewTexts}` : '',
    contentWarnings ? `内容提示 ${contentWarnings}` : '',
    sourceFailures ? `来源异常 ${sourceFailures}` : '',
    qualityFailed ? '语义检查暂不可用' : '',
    semanticGroups ? `语义待确认 ${semanticGroups}组` : '',
    notEvaluated ? `未自动核对 ${notEvaluated}` : '',
    hasQuestions && coverage ? answerPending ? '回答覆盖待核验' : `已核验回答 ${coverage.answered}/${coverage.required}` : '',
  ].filter(Boolean).join(' · ')
  return { text, state: issues || unverified || reviewTexts || contentWarnings || sourceFailures || qualityFailed || semanticGroups || answerPending || answerIncomplete ? 'stale' : total ? 'valid' : 'unknown' }
}

/**
 * 正文中需处理的位置（改动数值、待核实、过期引用、待复核表格/图表入口）中，文档位置在 after 之后的下一处；
 * 到末尾后回到第一处。按文档位置而非元素身份接续，装饰重绘后不会回到开头。
 */
export function nextSourceIssue(root: HTMLElement, after: number | null, positionOf: (element: HTMLElement) => number,
  validation: TraceValidation | null = null): HTMLElement | null {
  const reviewSubjects = new Set(validation?.subjects.filter(subject =>
    subject.status !== 'valid' || (subject.warnings?.length ?? 0) > 0,
  ).map(subject => subject.subjectId))
  const valueSubjects = new Set([...root.querySelectorAll<HTMLElement>(
    '.report-value-mark--review, .report-value-mark--stale, .report-value-mark--unverified',
  )].map(mark => mark.dataset.valueSubject))
  // 无法提取唯一正文值时，使用协议引用兜底。读取整组引用，兼容首项为 analysis 的合并入口。
  const issues = [...root.querySelectorAll<HTMLElement>(
    '.report-value-mark--review, .report-value-mark--stale, .report-value-mark--unverified, .report-object-source-marker[data-marker-state="stale"], .report-protocol-marker[data-marker-references]',
  )].filter(item => {
    // 原始值与待核实占位属于同一处，跳转只定位正文占位。
    if (item.classList.contains('report-original-value')) return false
    if (item.matches('.report-value-mark--review, .report-value-mark--stale, .report-value-mark--unverified, .report-object-source-marker[data-marker-state="stale"]')) return true
    if (item.classList.contains('report-object-source-marker')) return false
    const references: Array<{ kind: string; value: string }> = JSON.parse(item.dataset.markerReferences ?? '[]')
    return references.some(ref => ref.kind === 'citation' && reviewSubjects.has(ref.value) && !valueSubjects.has(ref.value))
  })
  // 未绑定但仍在正文的图可以定位；不为它创建指向不存在的来源记录的按钮。
  for (const chart of validation?.charts ?? []) {
    if (chart.status !== 'unbound' || !chart.locationSource) continue
    const target = findEvidenceChartImage(root, chart.locationSource, document.baseURI)
    if (target) issues.push(target)
  }
  const ordered = [...new Set(issues)].sort((a, b) => positionOf(a) - positionOf(b))
  if (!ordered.length) return null
  return (after === null ? undefined : ordered.find(item => positionOf(item) > after)) ?? ordered[0]
}

const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]
const rotr = (value: number, bits: number) => (value >>> bits) | (value << (32 - bits))

function sha256Fallback(input: Uint8Array): Uint8Array {
  const bitLength = input.length * 8
  const paddedLength = Math.ceil((input.length + 9) / 64) * 64
  const data = new Uint8Array(paddedLength)
  data.set(input); data[input.length] = 0x80
  const view = new DataView(data.buffer)
  view.setUint32(paddedLength - 4, bitLength, false)
  let [a, b, c, d, e, f, g, h] = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]
  for (let offset = 0; offset < data.length; offset += 64) {
    const w = new Uint32Array(64)
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(offset + i * 4, false)
    for (let i = 16; i < 64; i++) {
      const x = w[i - 15], y = w[i - 2]
      const s0 = rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3)
      const s1 = rotr(y, 17) ^ rotr(y, 19) ^ (y >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0
    }
    let [aa, bb, cc, dd, ee, ff, gg, hh] = [a, b, c, d, e, f, g, h]
    for (let i = 0; i < 64; i++) {
      const s1 = rotr(ee, 6) ^ rotr(ee, 11) ^ rotr(ee, 25)
      const ch = (ee & ff) ^ (~ee & gg)
      const t1 = (hh + s1 + ch + SHA256_K[i] + w[i]) >>> 0
      const s0 = rotr(aa, 2) ^ rotr(aa, 13) ^ rotr(aa, 22)
      const maj = (aa & bb) ^ (aa & cc) ^ (bb & cc)
      const t2 = (s0 + maj) >>> 0
      ;[hh, gg, ff, ee, dd, cc, bb, aa] = [gg, ff, ee, (dd + t1) >>> 0, cc, bb, aa, (t1 + t2) >>> 0]
    }
    a = (a + aa) >>> 0; b = (b + bb) >>> 0; c = (c + cc) >>> 0; d = (d + dd) >>> 0
    e = (e + ee) >>> 0; f = (f + ff) >>> 0; g = (g + gg) >>> 0; h = (h + hh) >>> 0
  }
  const result = new Uint8Array(32), words = [a, b, c, d, e, f, g, h]
  words.forEach((word, i) => { result.set([(word >>> 24) & 255, (word >>> 16) & 255, (word >>> 8) & 255, word & 255], i * 4) })
  return result
}

export async function markdownSha256(markdown: string): Promise<string> {
  const input = new TextEncoder().encode(markdown)
  const digest = crypto.subtle
    ? new Uint8Array(await crypto.subtle.digest('SHA-256', input))
    : sha256Fallback(input)
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export function createSourceValidationController(
  client: Pick<ReportEditorClient, 'validateSources'>,
  getMarkdown: () => string,
  onResult: (result: TraceValidation | null) => void,
  onChecking: () => void,
  delayMs = 450,
  onError: (error: unknown) => void = () => {},
) {
  let timer: ReturnType<typeof setTimeout> | undefined
  let sequence = 0
  let controller: AbortController | undefined

  const cancel = () => {
    sequence += 1
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
    controller?.abort()
    controller = undefined
  }

  const check = async (markdown: string, requestSequence: number) => {
    try {
      const digest = await markdownSha256(markdown)
      if (requestSequence !== sequence || getMarkdown() !== markdown) return
      controller = new AbortController()
      const result = await client.validateSources(markdown, digest, controller.signal)
      if (requestSequence !== sequence || result.draftSha256 !== digest || getMarkdown() !== markdown) return
      onResult(result)
    } catch (error) {
      if (requestSequence !== sequence || getMarkdown() !== markdown || (error instanceof DOMException && error.name === 'AbortError')) return
      // 先清除旧结果，避免通用空状态覆盖具体错误原因。
      onResult(null)
      onError(error)
    }
  }

  return {
    schedule() {
      cancel()
      onChecking()
      const markdown = getMarkdown()
      const current = sequence
      timer = setTimeout(() => void check(markdown, current), delayMs)
    },
    cancel,
  }
}
