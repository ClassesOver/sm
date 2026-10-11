import type { ReportEditorClient, TraceValidation } from './api'

export function sourceValidationIssueCount(result: TraceValidation): number {
  const warningSubjects = result.subjects.filter(
    (subject) => subject.status === 'valid' && (subject.warnings?.length ?? 0) > 0,
  ).length
  const table = result.tableSummary
  const chartIssues = result.charts?.filter((chart) => chart.status !== 'valid').length ?? 0
  return (result.warnings?.length ?? 0) + result.summary.stale + result.summary.unbound + warningSubjects +
    (table ? table.stale + table.unbound + table.insertedRows + (table.copiedCells ?? 0) : 0) + chartIssues
}

const UNVERIFIED_PLACEHOLDER = '待核实'

/** 状态栏溯源覆盖摘要：可溯源 x/y · 待复核 n · 待核实 n。只统计，不改变校验结论。 */
export function sourceCoverageSummary(result: TraceValidation, markdown: string): { text: string; state: 'valid' | 'stale' | 'unknown' } {
  const warningSubjects = result.subjects.filter(subject => subject.status === 'valid' && (subject.warnings?.length ?? 0) > 0).length
  const table = result.tableSummary
  const charts = result.charts ?? []
  const total = result.summary.valid + result.summary.stale + result.summary.unbound +
    (table ? table.valid + table.stale + table.unbound : 0) + charts.length
  const traceable = result.summary.valid - warningSubjects + (table?.valid ?? 0) + charts.filter(chart => chart.status === 'valid').length
  const issues = sourceValidationIssueCount(result)
  const unverified = markdown.split(UNVERIFIED_PLACEHOLDER).length - 1
  const text = [
    total ? `可溯源 ${traceable}/${total}` : '当前内容无精确来源绑定',
    issues ? `待复核 ${issues}` : '',
    unverified ? `待核实 ${unverified}` : '',
  ].filter(Boolean).join(' · ')
  return { text, state: issues || unverified ? 'stale' : total ? 'valid' : 'unknown' }
}

/**
 * 正文中需处理的位置（改动数值、待核实、过期引用、待复核表格/图表入口）中，文档位置在 after 之后的下一处；
 * 到末尾后回到第一处。按文档位置而非元素身份接续，装饰重绘后不会回到开头。
 */
export function nextSourceIssue(root: HTMLElement, after: number | null, positionOf: (element: HTMLElement) => number,
  validation: TraceValidation | null = null): HTMLElement | null {
  const staleSubjects = new Set(validation?.subjects.filter(subject => subject.status === 'stale').map(subject => subject.subjectId))
  const valueSubjects = new Set([...root.querySelectorAll<HTMLElement>(
    '.report-value-mark--stale, .report-value-mark--unverified',
  )].map(mark => mark.dataset.valueSubject))
  // 无法提取唯一正文值时，使用协议引用兜底。读取整组引用，兼容首项为 analysis 的合并入口。
  const issues = [...root.querySelectorAll<HTMLElement>(
    '.report-value-mark--stale, .report-value-mark--unverified, .report-object-source-marker[data-marker-state="stale"], .report-protocol-marker[data-marker-references]',
  )].filter(item => {
    if (item.matches('.report-value-mark--stale, .report-value-mark--unverified, .report-object-source-marker[data-marker-state="stale"]')) return true
    if (item.classList.contains('report-object-source-marker')) return false
    const references: Array<{ kind: string; value: string }> = JSON.parse(item.dataset.markerReferences ?? '[]')
    return references.some(ref => ref.kind === 'citation' && staleSubjects.has(ref.value) && !valueSubjects.has(ref.value))
  })
  if (!issues.length) return null
  return (after === null ? undefined : issues.find(item => positionOf(item) > after)) ?? issues[0]
}

export async function markdownSha256(markdown: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(markdown))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export function createSourceValidationController(
  client: Pick<ReportEditorClient, 'validateSources'>,
  getMarkdown: () => string,
  onResult: (result: TraceValidation | null) => void,
  onChecking: () => void,
  delayMs = 450,
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
      onResult(null)
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
