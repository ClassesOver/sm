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
  guides(): Guide[]
}

export function mountSlidesGuides(content: () => HTMLElement | null, slidePx: () => { width: number; height: number }, storageKey: string, onVisibleChange: (visible: boolean) => void, unit: RulerUnit = 'cm'): SlidesGuides {
  let guides = readGuides(storageKey), visible = false, preview: Guide | null = null
  const bubble = document.createElement('div'); bubble.className = 'ruler-bubble'; bubble.hidden = true; document.body.append(bubble)
  const save = () => { try { localStorage.setItem(storageKey, JSON.stringify(guides)) } catch { /* 仅本机便利，失败不影响编辑 */ } }
  const showBubble = (client: { x: number; y: number }, guide: Guide) => {
    const size = slidePx()
    bubble.hidden = false; bubble.style.left = `${client.x + 14}px`; bubble.style.top = `${client.y + 16}px`
    bubble.textContent = formatRulerValue(guide.pos, guide.axis === 'v' ? size.width : size.height, unit)
  }
  const fraction = (axis: 'v' | 'h', client: { x: number; y: number }) => {
    const rect = content()?.getBoundingClientRect()
    if (!rect) return 0
    return axis === 'v' ? (client.x - rect.left) / rect.width : (client.y - rect.top) / rect.height
  }
  const line = (guide: Guide, draggable: boolean) => {
    const element = document.createElement('div')
    element.className = `guide-line guide-${guide.axis}${draggable ? ' guide-draggable' : ''}`
    element.style[guide.axis === 'v' ? 'left' : 'top'] = `${guide.pos * 100}%`
    return element
  }
  const render = () => {
    const host = content()
    for (const old of document.querySelectorAll('.slides-canvas .guide-line')) old.remove()
    if (!host) return
    if (visible) guides.forEach((guide, index) => {
      const element = line(guide, true)
      element.title = '拖动移动参考线；拖出画布或双击删除'
      element.dataset.guideIndex = String(index)
      element.addEventListener('pointerdown', event => {
        event.preventDefault(); event.stopPropagation()
        element.setPointerCapture?.(event.pointerId)
        const rect = host.getBoundingClientRect()
        let moved = false
        const move = (next: PointerEvent) => {
          moved = true
          guide.pos = clamp(guide.axis === 'v' ? (next.clientX - rect.left) / rect.width : (next.clientY - rect.top) / rect.height)
          element.style[guide.axis === 'v' ? 'left' : 'top'] = `${guide.pos * 100}%`
          showBubble({ x: next.clientX, y: next.clientY }, guide)
        }
        const up = (next: PointerEvent) => {
          window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up)
          bubble.hidden = true
          // 单击不重绘：保留同一元素，双击删除才能命中
          if (!moved) return
          const outside = next.clientX < rect.left - 24 || next.clientX > rect.right + 24 || next.clientY < rect.top - 24 || next.clientY > rect.bottom + 24
          if (outside) guides = guides.filter(item => item !== guide)
          save(); render()
        }
        window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
      })
      element.addEventListener('dblclick', () => { guides = guides.filter(item => item !== guide); save(); render() })
      host.append(element)
    })
    if (preview) host.append(line(preview, false))
  }
  return {
    setVisible(next) { visible = next; render() },
    pull(axis, client, done) {
      const raw = fraction(axis, client)
      if (!done) { preview = { axis, pos: clamp(raw) }; showBubble(client, preview); render(); return }
      preview = null; bubble.hidden = true
      // 放回标尺区（页面外）= 取消
      if (raw >= -0.02 && raw <= 1.02) { guides = [...guides, { axis, pos: clamp(raw) }]; save(); if (!visible) { visible = true; onVisibleChange(true) } }
      render()
    },
    render,
    guides: () => guides.map(guide => ({ ...guide })),
  }
}
