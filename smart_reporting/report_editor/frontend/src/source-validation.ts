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
