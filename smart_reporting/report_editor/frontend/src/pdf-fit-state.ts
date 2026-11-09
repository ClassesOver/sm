/** Pinned App rowSize/recomputeFit intent adapted to native fixed DOM chrome.
 * Provenance and adaptations: genoffice-pdf-fit-source.json.
 */
import { spreadRows } from './genoffice-pdf-spread'
import { clampPdfZoom } from './pdf-view-state'
export const PDF_ROW_GAP = 16 // pinned view-config.ts PAGE_GAP
export interface PdfFitPage { width: number; height: number; chromeWidth: number; chromeHeight: number }
export function fitPdfRows(pages: PdfFitPage[], spread: 1 | 2, mode: 'width' | 'page', availableWidth: number, availableHeight: number): number | null {
  if (!pages.length || availableWidth <= 0 || availableHeight <= 0) return null
  if (![availableWidth, availableHeight].every(Number.isFinite) || pages.some(p => ![p.width,p.height,p.chromeWidth,p.chromeHeight].every(Number.isFinite) || p.width <= 0 || p.height <= 0 || p.chromeWidth < 0 || p.chromeHeight < 0)) throw new Error('页面适配尺寸无效')
  const rows = spreadRows(pages.map((_, index) => index), spread)
  const widthScales = rows.map(row => (availableWidth - PDF_ROW_GAP * (row.length - 1) - row.reduce((n,i) => n + pages[i].chromeWidth,0)) / row.reduce((n,i) => n + pages[i].width,0))
  let next = widthScales.reduce((minimum, value) => Math.min(minimum, value), Number.POSITIVE_INFINITY)
  if (mode === 'page') for (const page of pages) next = Math.min(next, (availableHeight - page.chromeHeight) / page.height)
  return clampPdfZoom(next)
}
