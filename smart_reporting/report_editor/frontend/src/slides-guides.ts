/**
 * 固定源 View ▸ Guides（SlidesApp.tsx guides/showGuides/guidePreview/guideBubble）的原生 DOM 移植：
 * 参考线位置为页面宽/高的 0–1 比例，默认横竖各一条居中；按文档持久化到本机 localStorage。
 * 拖动参考线移动，拖出画布 24px 以外或双击删除；拖动时气泡显示距页面中心的距离（ruler-ticks formatRulerValue）。
 * 纯视图状态，不写入文件、不产生草稿。
 */
import { formatRulerValue, type RulerUnit } from './vendor/genoffice-slides/ruler-ticks'

export type Guide = { axis: 'v' | 'h'; pos: number }
const DEFAULT_GUIDES: Guide[] = [{ axis: 'v', pos: 0.5 }, { axis: 'h', pos: 0.5 }]
const clamp = (value: number) => Math.min(1, Math.max(0, value))

export function readGuides(key: string): Guide[] {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return DEFAULT_GUIDES.map(guide => ({ ...guide }))
    const parsed: unknown = JSON.parse(raw)
    if (Array.isArray(parsed) && parsed.length <= 100 && parsed.every(item => item && (item.axis === 'v' || item.axis === 'h') && typeof item.pos === 'number' && item.pos >= 0 && item.pos <= 1)) return parsed as Guide[]
  } catch { /* 存储不可用时退回默认参考线 */ }
  return DEFAULT_GUIDES.map(guide => ({ ...guide }))
}

export interface SlidesGuides {
  setVisible(visible: boolean): void
  /** 标尺拖出参考线：done=false 为预览，done=true 时落到页面内则新增并显示参考线 */
  pull(axis: 'h' | 'v', client: { x: number; y: number }, done: boolean): void
  render(): void
  dispose(): void
  cancelPull(): void
  guides(): Guide[]
}

export function mountSlidesGuides(content: () => HTMLElement | null, slidePx: () => { width: number; height: number }, storageKey: string, onVisibleChange: (visible: boolean) => void, unit: RulerUnit = 'cm'): SlidesGuides {
  let guides = readGuides(storageKey), visible = false, preview: Guide | null = null
  let disposed = false, renderedHost: HTMLElement | null = content()
  let cancelDrag: (() => void) | undefined
  const elements: HTMLElement[] = []
  const clearLines = () => { for (const element of elements) element.remove(); elements.length = 0 }
  const bubble = document.createElement('div'); bubble.className = 'ruler-bubble'; bubble.hidden = true; document.body.append(bubble)
  const save = () => { try { localStorage.setItem(storageKey, JSON.stringify(guides)) } catch { /* 仅本机便利，失败不影响编辑 */ } }
  const showBubble = (client: { x: number; y: number }, guide: Guide) => {
    const size = slidePx()
    bubble.hidden = false
    bubble.textContent = formatRulerValue(guide.pos, guide.axis === 'v' ? size.width : size.height, unit)
    const rect = bubble.getBoundingClientRect()
    bubble.style.left = `${Math.max(4, Math.min(client.x + 14, innerWidth - rect.width - 4))}px`
    bubble.style.top = `${Math.max(4, Math.min(client.y + 16, innerHeight - rect.height - 4))}px`
  }
  const fraction = (axis: 'v' | 'h', client: { x: number; y: number }) => {
    const rect = content()?.getBoundingClientRect()
    if (!rect || rect.width <= 0 || rect.height <= 0) return null
    return axis === 'v' ? (client.x - rect.left) / rect.width : (client.y - rect.top) / rect.height
  }
  const line = (guide: Guide, draggable: boolean) => {
    const element = document.createElement('div')
    element.className = `guide-line guide-${guide.axis}${draggable ? ' guide-draggable' : ''}`
    element.style[guide.axis === 'v' ? 'left' : 'top'] = `${guide.pos * 100}%`
    elements.push(element)
    return element
  }
  const focusPage = (host: HTMLElement) => { if (!host.hasAttribute('tabindex')) host.tabIndex = -1; host.focus({ preventScroll: true }) }
  const render = (focusIndex?: number) => {
    if (disposed) return
    const focused = elements.find(element => element === document.activeElement)
    const restoreIndex = focusIndex ?? (focused?.dataset.guideIndex ? Number(focused.dataset.guideIndex) : undefined)
    // 切页可能复用同一画布节点；重建叠层前也要撤销尚未提交的拖动。
    cancelDrag?.()
    const host = content()
    if (host !== renderedHost) { preview = null; bubble.hidden = true }
    renderedHost = host
    clearLines()
    if (!host) return
    if (visible) guides.forEach((guide, index) => {
      const element = line(guide, true)
      element.title = '拖动或方向键移动参考线；Shift 加速；Delete 删除'
      element.tabIndex = 0; element.setAttribute('role', 'slider')
      element.setAttribute('aria-label', `${guide.axis === 'v' ? '垂直' : '水平'}参考线 ${index + 1}`)
      element.setAttribute('aria-orientation', guide.axis === 'v' ? 'horizontal' : 'vertical')
      element.setAttribute('aria-valuemin', '0'); element.setAttribute('aria-valuemax', '100')
      element.setAttribute('aria-description', '方向键微调，Shift 加速，Home 或 End 移到边缘，Delete 删除，拖动时 Escape 取消')
      const syncPosition = () => {
        element.style[guide.axis === 'v' ? 'left' : 'top'] = `${guide.pos * 100}%`
        element.setAttribute('aria-valuenow', String(Number((guide.pos * 100).toFixed(3))))
        const size = slidePx()
        element.setAttribute('aria-valuetext', `距${guide.axis === 'v' ? '左' : '上'}边 ${Number((guide.pos * 100).toFixed(1))}%，距中心 ${formatRulerValue(guide.pos, guide.axis === 'v' ? size.width : size.height, unit)}`)
      }
      syncPosition()
      element.addEventListener('keydown', event => {
        if (disposed || event.altKey || event.ctrlKey || event.metaKey || event.isComposing || event.keyCode === 229 || event.defaultPrevented || content() !== host) return
        const negative = guide.axis === 'v' ? 'ArrowLeft' : 'ArrowUp', positive = guide.axis === 'v' ? 'ArrowRight' : 'ArrowDown'
        if (![negative, positive, 'Home', 'End', 'Delete', 'Backspace'].includes(event.key)) return
        event.preventDefault(); event.stopPropagation(); cancelDrag?.()
        if (event.key === 'Delete' || event.key === 'Backspace') { guides = guides.filter(item => item !== guide); save(); render(index); return }
        const size = slidePx(), length = guide.axis === 'v' ? size.width : size.height
        if (!(length > 0)) return
        guide.pos = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : clamp(guide.pos + (event.key === positive ? 1 : -1) * (event.shiftKey ? 10 : 1) / length)
        syncPosition(); save()
      })
      element.dataset.guideIndex = String(index)
      element.addEventListener('pointerdown', event => {
        if (event.button !== 0 || disposed) return
        cancelDrag?.()
        event.preventDefault(); event.stopPropagation()
        element.focus({ preventScroll: true })
        const original = guide.pos
        const cleanup = () => {
          window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up)
          window.removeEventListener('keydown', escape); window.removeEventListener('pointercancel', cancel); element.removeEventListener('lostpointercapture', cancel)
          cancelDrag = undefined; bubble.hidden = true
          if (element.hasPointerCapture?.(event.pointerId)) element.releasePointerCapture(event.pointerId)
        }
        const cancel = (next?: PointerEvent) => {
          if (next && next.pointerId !== event.pointerId) return
          guide.pos = original; syncPosition(); cleanup()
        }
        const escape = (next: KeyboardEvent) => { if (next.isComposing || next.keyCode === 229 || next.defaultPrevented) return; if (next.key === 'Escape') { next.preventDefault(); next.stopPropagation(); cancel() } }
        cancelDrag = cancel
        element.setPointerCapture?.(event.pointerId)
        const rect = host.getBoundingClientRect()
        let moved = false
        const move = (next: PointerEvent) => {
          if (next.pointerId !== event.pointerId) return
          if (content() !== host) { cancel(); render(); return }
          moved = true
          guide.pos = clamp(guide.axis === 'v' ? (next.clientX - rect.left) / rect.width : (next.clientY - rect.top) / rect.height)
          syncPosition()
          showBubble({ x: next.clientX, y: next.clientY }, guide)
        }
        const up = (next: PointerEvent) => {
          if (next.pointerId !== event.pointerId) return
          if (content() !== host) { cancel(); render(); return }
          cleanup()
          // 单击不重绘：保留同一元素，双击删除才能命中
          if (!moved) return
          const outside = next.clientX < rect.left - 24 || next.clientX > rect.right + 24 || next.clientY < rect.top - 24 || next.clientY > rect.bottom + 24
          if (outside) guides = guides.filter(item => item !== guide)
          save(); render()
        }
        window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
        window.addEventListener('keydown', escape); window.addEventListener('pointercancel', cancel); element.addEventListener('lostpointercapture', cancel)
      })
      element.addEventListener('dblclick', () => { guides = guides.filter(item => item !== guide); save(); render() })
      host.append(element)
    })
    if (preview) host.append(line(preview, false))
    if (restoreIndex !== undefined) {
      const target = elements.filter(element => element.classList.contains('guide-draggable'))[Math.min(restoreIndex, guides.length - 1)]
      if (target) target.focus({ preventScroll: true }); else focusPage(host)
    }
  }
  return {
    setVisible(next) { if (disposed) return; cancelDrag?.(); preview = null; bubble.hidden = true; visible = next; render() },
    pull(axis, client, done) {
      if (disposed) return
      const raw = fraction(axis, client)
      if (raw === null) { preview = null; bubble.hidden = true; render(); return }
      if (!done) { preview = { axis, pos: clamp(raw) }; showBubble(client, preview); render(); return }
      preview = null; bubble.hidden = true
      // 放回标尺区（页面外）= 取消
      if (raw >= -0.02 && raw <= 1.02) { guides = [...guides, { axis, pos: clamp(raw) }]; save(); if (!visible) { visible = true; onVisibleChange(true) } }
      render()
    },
    render,
    cancelPull() { preview = null; bubble.hidden = true; render() },
    dispose() { if (disposed) return; cancelDrag?.(); disposed = true; preview = null; clearLines(); bubble.remove() },
    guides: () => guides.map(guide => ({ ...guide })),
  }
}
