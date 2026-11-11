import { createModal } from './modal'
import { buttonClasses } from './button'

// Fixed GenOffice f8c17004 docs/wheel-zoom.ts: 10–500%, ten points per button.
export const DOCX_ZOOM_MIN = 10
export const DOCX_ZOOM_MAX = 500
export type DocxZoomFit = 'width' | 'page'
export interface DocxViewCommands {
  run(label: string): void
  reason(label: string): string | null
  active?(label: string): boolean
}

export function docxFitZoom(mode: DocxZoomFit, viewport: { width: number; height: number }, page: { width: number; height: number }): number | undefined {
  if (![viewport.width, viewport.height, page.width, page.height].every(value => Number.isFinite(value) && value > 0)) return undefined
  const width = Math.max(1, viewport.width - 48) / page.width * 100
  const height = Math.max(1, viewport.height - 48) / page.height * 100
  const value = Math.floor(mode === 'width' ? width : Math.min(width, height))
  return Math.max(DOCX_ZOOM_MIN, Math.min(DOCX_ZOOM_MAX, value))
}

/** Display-only zoom. Never writes PM attributes, NativeDraft or source bytes. */
export function createDocxViewCommands(options: {
  root: HTMLElement
  scroller: HTMLElement
  page: HTMLElement
  pageSize(): { width: number; height: number }
  onPaginationPreview(): void
  onZoomChange?(): void
  navigation?: {toggle(): void; readonly visible: boolean}
  gridlines?: {toggle(): void; readonly visible: boolean}
  ruler?: {toggle(): void; readonly visible: boolean}
  outline?: {run(label: string): void; reason(label: string): string | null; readonly mode: string}
}) {
  let zoom = 100
  let fit: DocxZoomFit | undefined
  let disposed = false
  const previousZoom = options.page.style.getPropertyValue('zoom')
  const previousData = options.root.getAttribute('data-docx-zoom')
  const status = document.createElement('output')
  status.className = 'docx-view-status'
  status.setAttribute('aria-label', 'Word 显示比例')
  options.root.append(status)
  const update = () => {
    const changed = options.root.dataset.docxZoom !== String(zoom)
    options.page.style.setProperty('zoom', String(zoom / 100))
    options.root.dataset.docxZoom = String(zoom)
    status.value = `${zoom}%`
    status.textContent = `${zoom}%`
    if (changed) options.onZoomChange?.()
  }
  const set = (value: number) => {
    if (!Number.isFinite(value) || value < DOCX_ZOOM_MIN || value > DOCX_ZOOM_MAX || !Number.isInteger(value)) throw new Error('显示比例须为 10–500 的整数百分比')
    fit = undefined
    zoom = value
    update()
  }
  const refit = () => {
    if (!fit || disposed) return
    const next = docxFitZoom(fit, { width: options.scroller.clientWidth, height: options.scroller.clientHeight }, options.pageSize())
    if (next !== undefined) { zoom = next; update() }
  }
  const applyFit = (mode: DocxZoomFit) => {
    const next = docxFitZoom(mode, { width: options.scroller.clientWidth, height: options.scroller.clientHeight }, options.pageSize())
    if (next === undefined) return
    fit = mode
    zoom = next
    update()
  }
  const modal = createModal({ root: options.root, label: 'Word 显示比例', cardClass: 'docx-zoom-dialog', closeLabel: '关闭显示比例', content: `
    <h2>显示比例</h2><form class="docx-zoom-form">
      <label>百分比<input type="number" min="10" max="500" step="1" aria-label="显示比例（%）" aria-describedby="docx-zoom-error"></label>
      <p>仅调整屏幕显示，不改变文档尺寸、内容或导出结果。</p>
      <p id="docx-zoom-error" role="alert"></p>
      <div class="docx-zoom-actions"><button type="button" class="${buttonClasses('secondary')}" data-action="cancel">取消</button><button type="submit" class="${buttonClasses('primary')}">应用</button></div>
    </form>` })
  const input = modal.card.querySelector<HTMLInputElement>('input')!
  const error = modal.card.querySelector<HTMLElement>('[role=alert]')!
  modal.card.querySelector('[data-action=cancel]')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (!input.value.trim()) throw new Error('请输入显示比例')
      set(Number(input.value))
      modal.close()
    } catch (cause) { error.textContent = (cause as Error).message; input.setAttribute('aria-invalid', 'true') }
  })
  const handled = new Set(['缩小', '放大', '页宽', '整页', '缩放', '100%', '分页预览'])
  const commands: DocxViewCommands = {
    reason(label) {
      if (!disposed && label === '标尺' && options.ruler) return null
      if (!disposed && label === '网格线' && options.gridlines) return null
      if (!disposed && label === '导航窗格' && options.navigation) return null
      if (!disposed && ['大纲', '页面视图'].includes(label) && options.outline) return options.outline.reason(label)
      return !disposed && handled.has(label) ? null : '此视图命令尚未与原生 Word 画布对齐'
    },
    active(label) { return !disposed && (label === '标尺' ? !!options.ruler?.visible : label === '网格线' ? !!options.gridlines?.visible : label === '导航窗格' ? !!options.navigation?.visible : label === '大纲' ? options.outline?.mode === 'outline' : label === '页面视图' ? options.outline?.mode === 'page' : false) },
    run(label) {
      if (commands.reason(label) !== null) return
      if (label === '标尺') { options.ruler!.toggle(); return }
      if (label === '网格线') { options.gridlines!.toggle(); return }
      if (label === '导航窗格') { options.navigation!.toggle(); return }
      if (label === '大纲' || label === '页面视图') { options.outline!.run(label); return }
      if (label === '缩小') set(Math.max(DOCX_ZOOM_MIN, zoom - 10))
      else if (label === '放大') set(Math.min(DOCX_ZOOM_MAX, zoom + 10))
      else if (label === '100%') set(100)
      else if (label === '页宽') applyFit('width')
      else if (label === '整页') applyFit('page')
      else if (label === '分页预览') options.onPaginationPreview()
      else { input.value = String(zoom); error.textContent = ''; input.removeAttribute('aria-invalid'); modal.open(input) }
    },
  }
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(refit) : undefined
  observer?.observe(options.scroller)
  window.addEventListener('resize', refit)
  update()
  return { ...commands, refresh: refit, get zoom() { return zoom }, dispose() {
    disposed = true; observer?.disconnect(); window.removeEventListener('resize', refit); modal.remove(); status.remove()
    if (previousZoom) options.page.style.setProperty('zoom', previousZoom); else options.page.style.removeProperty('zoom')
    if (previousData === null) options.root.removeAttribute('data-docx-zoom'); else options.root.setAttribute('data-docx-zoom', previousData)
  } }
}
