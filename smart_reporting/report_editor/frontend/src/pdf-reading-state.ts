/** DOM/immutable identity adapter for pinned GenOffice view-state.ts.
 * Source and differences: genoffice-pdf-reading-source.json.
 */
import { nativeDraftKey, type NativeDraftIdentity } from './native-draft'
import { captureViewState, type PdfViewState, type PdfFitMode } from './genoffice-pdf-reading-state'

export function pdfReadingKey(identity: NativeDraftIdentity): string { return `native-pdf:v1:${nativeDraftKey(identity)}` }
export interface PdfReadingRow { pageId: string; pageIds: string[]; sourcePage: number; top: number; height: number }
export function pdfReadingRows(viewport: HTMLElement, sourceIds: string[]): PdfReadingRow[] {
  const bounds = viewport.getBoundingClientRect(), indices = new Map(sourceIds.map((id, index) => [id, index + 1]))
  const rows: PdfReadingRow[] = []
  for (const page of viewport.querySelectorAll<HTMLElement>('.pdf-page')) {
    const sourcePage = indices.get(page.dataset.pageId ?? ''), box = page.getBoundingClientRect()
    if (!sourcePage || box.height <= 0) continue
    const top = box.top - bounds.top - viewport.clientTop + viewport.scrollTop
    const previous = rows.at(-1)
    if (previous && Math.abs(previous.top - top) < 1) { previous.height = Math.max(previous.height, box.height); previous.pageIds.push(page.dataset.pageId!) }
    else rows.push({ pageId: page.dataset.pageId!, pageIds: [page.dataset.pageId!], sourcePage, top, height: box.height })
  }
  return rows
}
export function capturePdfReading(viewport: HTMLElement, sourceIds: string[], scale: number, fitMode: PdfFitMode): PdfViewState | null {
  const rows = pdfReadingRows(viewport, sourceIds)
  const row = rows.findLast(row => row.top <= viewport.scrollTop) ?? rows[0]
  if (!row) return null
  // Use the source fraction/scale semantics with real DOM row geometry. Native
  // headings, notes and responsive gutters do not share the desktop row formula.
  return captureViewState({ scrollTop: viewport.scrollTop - row.top, rowHeights: [row.height], rowPages: [row.sourcePage], gap: 0, scale, fitMode })
}
export function restorePdfReading(viewport: HTMLElement, sourceIds: string[], saved: PdfViewState): string | null {
  const rows = pdfReadingRows(viewport, sourceIds)
  const original = sourceIds[Math.min(sourceIds.length - 1, Math.max(0, saved.page - 1))]
  const row = rows.find(row => row.pageIds.includes(original)) ?? rows[0]
  if (!row) return null
  const fraction = row.pageIds.includes(original) ? saved.frac : 0
  viewport.scrollTop = row === rows[0] && fraction === 0 ? 0 : row.top + fraction * row.height
  return row.pageId
}
