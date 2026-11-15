import type { NativeOperation } from './native-draft'
import type { RedactPattern } from './genoffice-pdf-redact-patterns'
import { findPatternsInIndex, redactionRect, type SearchIndex } from './genoffice-pdf-search'
import { PDF_REDACTION_MAX, pdfRedactionOperation, pdfPageState, type PdfPageIdentity, type PdfRect } from './pdf-operations'

export const PDF_REDACT_PATTERN_LABELS: Record<RedactPattern, string> = {
  phone: '电话号码',
  email: '电子邮箱',
  'credit-card': '信用卡号码',
  ssn: '美国社会安全号码',
  date: '日期',
  iban: 'IBAN 账号',
}

export function stagePdfPatternRedactions(index: SearchIndex, pages: PdfPageIdentity[], operations: NativeOperation[], patterns: readonly RedactPattern[]) {
  const source = new Map(pages.map(page => [page.index, page]))
  const deleted = new Set(operations.filter(op => op.kind === 'deletePage').map(op => op.pageId))
  const available = (pageIndex: number) => {
    const page = source.get(pageIndex)
    return page && !page.blank && !deleted.has(page.pageId) ? page : undefined
  }
  const key = (operation: NativeOperation) => JSON.stringify([operation.pageId, operation.rect])
  const existing = new Set(operations.filter(op => op.kind === 'redact').map(key))
  const staged: NativeOperation[] = []
  const room = Math.min(PDF_REDACTION_MAX - operations.filter(op => op.kind === 'redact').length, 500 - operations.length)
  let hits = 0, skipped = 0, capped = false
  for (const hit of findPatternsInIndex(index, patterns, i => !available(i))) {
    const page = available(hit.pageIndex)!
    const { x, y, width, height } = page.cropBox
    if (hit.rotated || hit.geometryIncomplete || hit.rects.some(([x1, y1, x2, y2]) => x1 < x || y1 < y || x2 > x + width || y2 > y + height)) {
      skipped++
      continue
    }
    const marks = new Map<string, NativeOperation>()
    try {
      for (const rect of hit.rects) {
        const [x1, y1, x2, y2] = redactionRect(rect)
        const clipped: PdfRect = [Math.max(x, x1), Math.max(y, y1), Math.min(x + width, x2), Math.min(y + height, y2)]
        const operation = pdfRedactionOperation(page.pageId, clipped, page.cropBox)
        if (!existing.has(key(operation))) marks.set(key(operation), operation)
      }
    } catch {
      skipped++
      continue
    }
    if (staged.length + marks.size > room) {
      capped = true
      break
    }
    if (marks.size) hits++
    for (const [identity, mark] of marks) {
      existing.add(identity)
      staged.push(mark)
    }
  }
  const next = [...operations, ...staged]
  if (staged.length) pdfPageState(pages, next)
  return { operations: next, hits, skipped, capped, added: staged.length }
}
