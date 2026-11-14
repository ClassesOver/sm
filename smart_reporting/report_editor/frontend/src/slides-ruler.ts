/**
 * 固定源 View ▸ Ruler（components/StageRuler.tsx）的原生 DOM 移植：标尺位于缩放画布之外，
 * 0 在页面中心、向两侧递增（中文界面用厘米）；按住主键在画布上拖动时，两条标尺上有跟随指针的细线。
 * 刻度计算直接复用逐字节引入的 ruler-ticks.ts。纯视图状态，不写入文件。
 * 按住标尺拖入画布：横向标尺拉出水平参考线、纵向标尺拉出垂直参考线（4px 死区防误触），由 onPull 交给参考线模块。
 */
import { computeRulerTicks, type RulerUnit } from './vendor/genoffice-slides/ruler-ticks'

export interface SlidesRuler { setVisible(visible: boolean): void; update(): void; dispose(): void }

/** stage：.slides-stage；content()：当前 Konva 画布内容元素；slidePx()：未缩放的幻灯片像素尺寸（96dpi，cx/9525）。 */
export type GuidePull = (axis: 'h' | 'v', client: { x: number; y: number }, done: boolean) => void
export function mountSlidesRuler(stage: HTMLElement, content: () => HTMLElement | null, slidePx: () => { width: number; height: number }, unit: RulerUnit = 'cm', onPull?: GuidePull, onCancelPull?: () => void): SlidesRuler {
  let disposed = false
  let cancelDrag: (() => void) | undefined
  let observedContent: HTMLElement | null = null
  const corner = document.createElement('div'); corner.className = 'ruler-corner'
  const strip = (vertical: boolean) => {
    const root = document.createElement('div'); root.className = `ruler ${vertical ? 'ruler-v' : 'ruler-h'}`
    const add = document.createElement('button'); add.className = 'ruler-add'; add.type = 'button'; add.textContent = '+'
    add.setAttribute('aria-label', `+ 添加${vertical ? '垂直' : '水平'}参考线`)
    add.title = '在页面中心添加参考线；方向键可微调位置'
    add.addEventListener('click', event => {
      event.stopPropagation()
      if (disposed || !visible || !onPull) return
      cancelDrag?.()
      const rect = content()?.getBoundingClientRect()
      if (rect && rect.width > 0 && rect.height > 0) onPull(vertical ? 'v' : 'h', { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }, true)
    })
    const marks = document.createElement('div'); marks.setAttribute('aria-hidden', 'true')
    const indicator = document.createElement('div'); indicator.className = 'ruler-indicator'
    // 固定源 startGuideDrag：拖动方向与标尺垂直，标尺只上报指针位置，由参考线模块换算到页面坐标。
    root.addEventListener('pointerdown', event => {
      if (event.button !== 0 || !onPull || disposed || !visible || (event.target instanceof Element && event.target.closest('.ruler-add'))) return
      cancelDrag?.()
      event.preventDefault()
      const start = { x: event.clientX, y: event.clientY }, axis = vertical ? 'v' : 'h'
      let dragging = false
      const host = content()
      const cleanup = () => {
        root.removeEventListener('pointermove', move); root.removeEventListener('pointerup', up)
        window.removeEventListener('keydown', escape); root.removeEventListener('pointercancel', cancel); root.removeEventListener('lostpointercapture', cancel)
        cancelDrag = undefined
        if (root.hasPointerCapture?.(event.pointerId)) root.releasePointerCapture(event.pointerId)
      }
      const cancel = (next?: PointerEvent) => {
        if (next && next.pointerId !== event.pointerId) return
        cleanup(); if (dragging) onCancelPull?.()
      }
      const escape = (next: KeyboardEvent) => { if (next.isComposing || next.keyCode === 229 || next.defaultPrevented) return; if (next.key === 'Escape') { next.preventDefault(); next.stopPropagation(); cancel() } }
      cancelDrag = cancel
      root.setPointerCapture?.(event.pointerId)
      const move = (next: PointerEvent) => {
        if (next.pointerId !== event.pointerId) return
        if (content() !== host) { cancel(); return }
        if (!dragging) { dragging = Math.abs(next.clientX - start.x) > 4 || Math.abs(next.clientY - start.y) > 4; if (!dragging) return }
        onPull(axis, { x: next.clientX, y: next.clientY }, false)
      }
      const up = (next: PointerEvent) => {
        if (next.pointerId !== event.pointerId) return
        if (content() !== host) { cancel(); return }
        cleanup()
        if (dragging) onPull(axis, { x: next.clientX, y: next.clientY }, true)
      }
      root.addEventListener('pointermove', move); root.addEventListener('pointerup', up)
      window.addEventListener('keydown', escape); root.addEventListener('pointercancel', cancel); root.addEventListener('lostpointercapture', cancel)
    })
    root.append(marks, indicator, ...(onPull ? [add] : []))
    return { root, indicator, vertical, add, marks }
  }
  const horizontal = strip(false), vertical = strip(true)
  let visible = false, frame = 0
  const render = () => {
    frame = 0
    const element = content()
    if (disposed || !visible || !element) return
    const box = element.getBoundingClientRect(), size = slidePx()
    for (const ruler of [horizontal, vertical]) {
      const rect = ruler.root.getBoundingClientRect()
      const zoom = (ruler.vertical ? box.height / size.height : box.width / size.width) || 0
      const ticks = computeRulerTicks({ rulerLen: ruler.vertical ? rect.height : rect.width, origin: ruler.vertical ? box.top - rect.top : box.left - rect.left,
        slideLen: ruler.vertical ? size.height : size.width, zoom, unit })
      ruler.marks.replaceChildren(...ticks.map(tick => {
        const mark = document.createElement('span'); mark.setAttribute('aria-hidden', 'true'); mark.className = tick.label != null ? 'ruler-num' : 'ruler-tick'
        if (tick.label != null) mark.textContent = tick.label
        mark.style[ruler.vertical ? 'top' : 'left'] = `${tick.pos}px`
        return mark
      }))
      ruler.root.dataset.rulerZoom = zoom.toFixed(4)
    }
  }
  const update = () => { if (!disposed && visible && !frame) frame = requestAnimationFrame(render) }
  const observer = new ResizeObserver(update)
  observer.observe(stage)
  // 固定源：主键按住在画布上拖动（移动、缩放、框选）时，指针位置细线随之移动。
  const hide = () => { for (const ruler of [horizontal, vertical]) ruler.indicator.style.display = 'none' }
  const move = (event: PointerEvent) => {
    if (!visible) return
    if (!(event.buttons & 1)) { hide(); return }
    for (const ruler of [horizontal, vertical]) {
      const rect = ruler.root.getBoundingClientRect()
      ruler.indicator.style.display = 'block'
      ruler.indicator.style.transform = ruler.vertical ? `translateY(${event.clientY - rect.top}px)` : `translateX(${event.clientX - rect.left}px)`
    }
  }
  stage.addEventListener('pointermove', move)
  stage.addEventListener('pointerleave', hide)
  window.addEventListener('pointerup', hide)
  const observeContent = () => {
    const element = visible ? content() : null
    if (element === observedContent) return
    cancelDrag?.()
    if (observedContent) observer.unobserve(observedContent)
    observedContent = element
    if (element) observer.observe(element)
  }
  return {
    setVisible(next) {
      if (disposed) return
      if (!next) { cancelDrag?.(); hide(); if (frame) cancelAnimationFrame(frame); frame = 0 }
      visible = next
      observeContent()
      stage.dataset.ruler = String(next)
      if (next) { stage.prepend(corner, horizontal.root, vertical.root); update() }
      else { corner.remove(); horizontal.root.remove(); vertical.root.remove() }
    },
    update() { if (disposed) return; cancelDrag?.(); observeContent(); update() },
    dispose() { if (disposed) return; cancelDrag?.(); disposed = true; visible = false; hide(); corner.remove(); horizontal.root.remove(); vertical.root.remove(); stage.dataset.ruler = 'false'; observer.disconnect(); stage.removeEventListener('pointermove', move); stage.removeEventListener('pointerleave', hide); window.removeEventListener('pointerup', hide); if (frame) cancelAnimationFrame(frame) },
  }
}
