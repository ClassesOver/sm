import { AnnotationLayer, AnnotationType } from 'pdfjs-dist/legacy/build/pdf.mjs'
import type { PDFPageProxy } from 'pdfjs-dist'
import { clampPdfZoom } from './pdf-view-state'

type Viewport = ReturnType<PDFPageProxy['getViewport']>
type Destination = string | unknown[]
interface Options {
  host: HTMLElement
  page: PDFPageProxy
  viewport: Viewport
  annotations: unknown[]
  enabled(): boolean
  navigate(destination: Destination): Promise<void>
  error(error: unknown): void
}

/** 按 PDF.js scrollPageIntoView 的目标类型适配宿主页框；坐标仍由官方 viewport 转换。 */
export function pdfLinkDestination(unit: Viewport, destination: unknown[], currentScale: number, available: { width: number; height: number }, retained?: number[]) {
  const invalid = () => new Error('链接目标参数无效')
  const number = (value: unknown) => { if (typeof value !== 'number' || !Number.isFinite(value)) throw invalid(); return value }
  const optional = (value: unknown, fallback: number) => value == null ? fallback : number(value)
  const rectangle = (view: Viewport, rect: number[]) => [...view.convertToViewportPoint(rect[0], rect[1]), ...view.convertToViewportPoint(rect[2], rect[3])]
  const kind = destination[1] && typeof destination[1] === 'object' && 'name' in destination[1] ? destination[1].name : undefined
  const [left, bottom, right, top] = unit.viewBox
  let next = currentScale, rect: number[]
  const area = () => { if (!(available.width > 0 && available.height > 0) || ![available.width, available.height].every(Number.isFinite)) throw invalid() }
  switch (kind) {
    case 'XYZ': {
      if (destination.length < 4 || destination.length > 5) throw invalid()
      const x = optional(destination[2], 0), y = optional(destination[3], top - bottom)
      const zoom = optional(destination[4], 0); if (zoom < 0) throw invalid()
      if (zoom) next = zoom
      rect = [x, y, x, y]; break
    }
    // 与当前 PDF.js 一致：B/BH/BV 使用可见页框，不推测正文墨迹边界。
    case 'Fit': case 'FitB':
      area(); next = clampPdfZoom(Math.min(available.width / unit.width, available.height / unit.height))
      return { scale: next, left: 0, top: 0 }
    case 'FitH': case 'FitBH': {
      area(); next = available.width / unit.width
      const requestedY = destination[2]
      const y = requestedY === null && retained ? retained[1] : typeof requestedY === 'number' && requestedY >= 0 ? requestedY : top - bottom
      const x = requestedY === null && retained ? retained[0] : left
      rect = [x, y, x, y]; break
    }
    case 'FitV': case 'FitBV': {
      area(); next = available.height / unit.height
      const requestedX = destination[2]
      const x = requestedX == null ? 0 : number(requestedX)
      rect = [x, bottom, x, top]; break
    }
    case 'FitR': {
      area(); rect = destination.slice(2, 6).map(number)
      if (rect.length !== 4 || rect[2] <= rect[0] || rect[3] <= rect[1]) throw invalid()
      const bounds = rectangle(unit, rect)
      next = Math.min(available.width / Math.abs(bounds[2] - bounds[0]), available.height / Math.abs(bounds[3] - bounds[1])); break
    }
    default: throw invalid()
  }
  next = clampPdfZoom(next)
  const bounds = rectangle(unit.clone({ scale: next }), rect)
  return { scale: next, left: Math.max(0, Math.min(bounds[0], bounds[2])), top: Math.max(0, Math.min(bounds[1], bounds[3])) }
}

/** 只接入网址与页内目标；几何、四边形和旋转仍由 PDF.js 原生批注层处理。 */
export async function mountPdfSavedLinks({ host, page, viewport, annotations, enabled, navigate, error }: Options) {
  const links = annotations.flatMap(raw => {
    if (!raw || typeof raw !== 'object') return []
    const data = raw as Record<string, unknown>
    if (data.annotationType !== AnnotationType.LINK || data.subtype !== 'Link' || data.hidden || data.noHTML || !Array.isArray(data.rect) || data.rect.length !== 4 || !data.rect.every(Number.isFinite)) return []
    if (data.url) {
      if (typeof data.url !== 'string') return []
      try {
        const url = new URL(data.url)
        if (!['http:', 'https:', 'mailto:'].includes(url.protocol)) return []
      } catch { return [] }
    } else if (!(typeof data.dest === 'string' && data.dest || Array.isArray(data.dest) && data.dest.length)) return []
    return [{ ...data, action: undefined, attachment: undefined, setOCGState: undefined }]
  })
  if (!links.length) return undefined
  const element = document.createElement('div'); element.className = 'annotationLayer pdf-saved-links'
  const annotationViewport = viewport.clone({ dontFlip: true })
  element.style.setProperty('--total-scale-factor', String(viewport.scale * viewport.userUnit))
  element.style.setProperty('--scale-round-x', '1px'); element.style.setProperty('--scale-round-y', '1px')
  let disposed = false
  const active = () => !disposed && enabled()
  const service = {
    addLinkAttributes(anchor: HTMLAnchorElement, url: string) {
      const display = new URL(url); display.username = ''; display.password = ''
      anchor.href = url; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'
      anchor.title = display.href; anchor.setAttribute('aria-label', `打开链接：${display.href}`)
    },
    getDestinationHash() { return '#' },
    goToDestination(destination: Destination) { if (active()) void navigate(destination).catch(reason => { if (active()) error(reason) }) },
  }
  const layer = new AnnotationLayer({
    div: element, viewport: annotationViewport,
    // 原生链接几何只用page.view；采用当前CropBox，不能让草稿裁切仍按源页框偏移。
    page: { view: viewport.viewBox }, linkService: service,
    accessibilityManager: undefined, annotationCanvasMap: undefined, annotationEditorUIManager: undefined,
    structTreeLayer: undefined, commentManager: undefined, annotationStorage: undefined,
  })
  await layer.render({ div: element, viewport: annotationViewport, page, annotations: links,
    // 仅上述两类链接可以进入此层，因此只需实现它们使用的三项宿主导航适配。
    linkService: service as unknown as Parameters<AnnotationLayer['render']>[0]['linkService'], renderForms: false, enableScripting: false,
  })
  for (const [index, anchor] of [...element.querySelectorAll('a')].entries()) {
    if (!anchor.hasAttribute('aria-label')) {
      anchor.setAttribute('aria-label', `跳转到文档内链接 ${index + 1} 的目标页`)
      anchor.title = '按文档内链接的目标位置和缩放跳转'
    }
  }
  const onClick = (event: Event) => { if (!active()) { event.preventDefault(); event.stopImmediatePropagation() } }
  const onFocus = (event: FocusEvent) => {
    if (active() && event.target instanceof HTMLAnchorElement) event.target.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }
  element.addEventListener('click', onClick, true)
  element.addEventListener('focusin', onFocus)
  const sync = () => {
    const available = active(); element.inert = !available
    for (const anchor of element.querySelectorAll('a')) anchor.tabIndex = available ? 0 : -1
  }
  sync(); host.append(element)
  return { element, sync, dispose() { disposed = true; element.removeEventListener('click', onClick, true); element.removeEventListener('focusin', onFocus); layer.destroy(); element.remove() } }
}
