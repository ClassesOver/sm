/**
 * 固定源 View ▸ Ruler（components/StageRuler.tsx）的原生 DOM 移植：标尺位于缩放画布之外，
 * 0 在页面中心、向两侧递增（中文界面用厘米）；按住主键在画布上拖动时，两条标尺上有跟随指针的细线。
 * 刻度计算直接复用逐字节引入的 ruler-ticks.ts。纯视图状态，不写入文件。
 * 与固定源差异：暂不支持从标尺拖出参考线。
 */
import { computeRulerTicks, type RulerUnit } from './vendor/genoffice-slides/ruler-ticks'

export interface SlidesRuler { setVisible(visible: boolean): void; update(): void; dispose(): void }

/** stage：.slides-stage；content()：当前 Konva 画布内容元素；slidePx()：未缩放的幻灯片像素尺寸（96dpi，cx/9525）。 */
export function mountSlidesRuler(stage: HTMLElement, content: () => HTMLElement | null, slidePx: () => { width: number; height: number }, unit: RulerUnit = 'cm'): SlidesRuler {
  const corner = document.createElement('div'); corner.className = 'ruler-corner'
  const strip = (vertical: boolean) => {
    const root = document.createElement('div'); root.className = `ruler ${vertical ? 'ruler-v' : 'ruler-h'}`; root.setAttribute('aria-hidden', 'true')
    const indicator = document.createElement('div'); indicator.className = 'ruler-indicator'
    return { root, indicator, vertical }
  }
  const horizontal = strip(false), vertical = strip(true)
  let visible = false, frame = 0
  const render = () => {
    frame = 0
    const element = content()
    if (!visible || !element) return
    const box = element.getBoundingClientRect(), size = slidePx()
    for (const ruler of [horizontal, vertical]) {
      const rect = ruler.root.getBoundingClientRect()
      const zoom = (ruler.vertical ? box.height / size.height : box.width / size.width) || 0
      const ticks = computeRulerTicks({ rulerLen: ruler.vertical ? rect.height : rect.width, origin: ruler.vertical ? box.top - rect.top : box.left - rect.left,
        slideLen: ruler.vertical ? size.height : size.width, zoom, unit })
      ruler.root.replaceChildren(...ticks.map(tick => {
        const mark = document.createElement('span'); mark.className = tick.label != null ? 'ruler-num' : 'ruler-tick'
        if (tick.label != null) mark.textContent = tick.label
        mark.style[ruler.vertical ? 'top' : 'left'] = `${tick.pos}px`
        return mark
      }), ruler.indicator)
      ruler.root.dataset.rulerZoom = zoom.toFixed(4)
    }
  }
  const update = () => { if (visible && !frame) frame = requestAnimationFrame(render) }
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
  return {
    setVisible(next) {
      visible = next
      stage.dataset.ruler = String(next)
      if (next) { stage.prepend(corner, horizontal.root, vertical.root); const element = content(); if (element) observer.observe(element); update() }
      else { corner.remove(); horizontal.root.remove(); vertical.root.remove() }
    },
    update() { const element = content(); if (visible && element) observer.observe(element); update() },
    dispose() { observer.disconnect(); stage.removeEventListener('pointermove', move); stage.removeEventListener('pointerleave', hide); window.removeEventListener('pointerup', hide); if (frame) cancelAnimationFrame(frame) },
  }
}
