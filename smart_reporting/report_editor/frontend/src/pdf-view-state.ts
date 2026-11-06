/** Native host adapter for pinned PDF view-config.ts/App zoom semantics. */
export const PDF_ZOOM_STEPS = [.1, .25, .5, .67, .8, .9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5, 6, 8] as const
export function clampPdfZoom(value: number) {
  if (!Number.isFinite(value)) throw new Error('缩放比例无效')
  return Math.max(PDF_ZOOM_STEPS[0], Math.min(PDF_ZOOM_STEPS[PDF_ZOOM_STEPS.length - 1], value))
}
export function stepPdfZoom(value: number, direction: -1 | 1) {
  const scale = clampPdfZoom(value)
  return direction === 1 ? PDF_ZOOM_STEPS.find(step => step > scale + .001) ?? 8 : [...PDF_ZOOM_STEPS].reverse().find(step => step < scale - .001) ?? .1
}
export interface PdfZoomAnchor { pageId: string; x: number; y: number; vx: number; vy: number }
/** DOM adapter retains a content point while native fixed headings/gaps stay unscaled. */
export function capturePdfZoomAnchor(viewport: HTMLElement, scale: number, vx = 0, vy = 0): PdfZoomAnchor | null {
  const bounds = viewport.getBoundingClientRect(), px = bounds.left + vx, py = bounds.top + vy
  const pages = [...viewport.querySelectorAll<HTMLElement>('.pdf-page-content')]
  const page = pages.find(node => { const box = node.getBoundingClientRect(); return px >= box.left && px <= box.right && py >= box.top && py <= box.bottom })
    ?? pages.find(node => { const box = node.getBoundingClientRect(); return box.bottom >= py && box.top <= bounds.bottom })
  if (!page || !(scale > 0)) return null
  const box = page.getBoundingClientRect(), x = Math.min(box.right, Math.max(box.left, px)), y = Math.min(box.bottom, Math.max(box.top, py))
  const pageId = page.closest<HTMLElement>('.pdf-page')?.dataset.pageId
  return pageId ? { pageId, x: (x - box.left) / scale, y: (y - box.top) / scale, vx: x - bounds.left, vy: y - bounds.top } : null
}
export function restorePdfZoomAnchor(viewport: HTMLElement, anchor: PdfZoomAnchor, scale: number) {
  const page = [...viewport.querySelectorAll<HTMLElement>('.pdf-page')].find(node => node.dataset.pageId === anchor.pageId)?.querySelector<HTMLElement>('.pdf-page-content')
  if (!page) return
  const bounds = viewport.getBoundingClientRect(), box = page.getBoundingClientRect()
  viewport.scrollTop += box.top + anchor.y * scale - bounds.top - anchor.vy
  viewport.scrollLeft += box.left + anchor.x * scale - bounds.left - anchor.vx
}
