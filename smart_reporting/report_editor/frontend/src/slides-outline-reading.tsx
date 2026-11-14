import React from 'react'
import { createRoot } from 'react-dom/client'
import { SlideViewThumbnail, type SlidesSorterState } from './slides-view-modes'
import { outlineOf } from './vendor/genoffice-slides/outline-of'
import { rangeSelection } from './vendor/genoffice-slides/slide-selection'
import './slides-outline-reading.css'

type Options = { onSelect(id: number): boolean; onDelete(ids: number[]): void; onNormal(): void }

/** 源 Outline 只展示文字大纲并选页，编辑仍由现有普通画布完成。 */
export function createSlidesOutline(host: HTMLElement, options: Options) {
  let state: SlidesSorterState = { slides: [], current: -1, locked: true }, selected: number[] = [], disposed = false
  host.className = 'slides-outline-pane'; host.tabIndex = 0
  host.setAttribute('role', 'listbox'); host.setAttribute('aria-label', '幻灯片文字大纲')
  const select = (id: number) => {
    if (disposed || state.locked || !state.slides.some(item => item.id === id) || !options.onSelect(id)) return
    selected = [id]; host.focus({ preventScroll: true })
    host.querySelector<HTMLElement>(`[data-slide-index="${id}"]`)?.scrollIntoView?.({ block: 'nearest' })
  }
  const keydown = (event: KeyboardEvent) => {
    if (disposed || host.hidden || state.locked || event.target !== host || event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.altKey || !state.slides.length) return
    const current = state.slides.findIndex(item => item.id === state.current), mod = event.ctrlKey || event.metaKey
    if (mod && event.key.toLowerCase() === 'a') { event.preventDefault(); selected = state.slides.map(item => item.id); return }
    if (mod) return
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      const edge = event.key === 'Home' ? 0 : state.slides.length - 1
      if (event.shiftKey && (event.key === 'Home' || event.key === 'End')) { selected = rangeSelection(current, edge).map(index => state.slides[index]!.id); return }
      const next = event.key === 'Home' || event.key === 'End' ? edge : Math.max(0, Math.min(state.slides.length - 1, current + (event.key === 'ArrowUp' || event.key === 'PageUp' ? -1 : 1)))
      select(state.slides[next]!.id)
    } else if ((event.key === 'Delete' || event.key === 'Backspace') && (window.getSelection()?.isCollapsed ?? true)) {
      event.preventDefault(); options.onDelete([...selected])
    }
  }
  host.addEventListener('keydown', keydown)
  return {
    update(next: SlidesSorterState) {
      if (disposed) return
      state = next; selected = selected.filter(id => next.slides.some(item => item.id === id))
      if (!selected.includes(state.current)) selected = [state.current]
      host.setAttribute('aria-activedescendant', `slides-outline-slide-${state.current}`)
      host.replaceChildren(...state.slides.map((item, index) => {
        const outline = item.slide ? outlineOf(item.slide) : { title: '大纲暂不可用', lines: [] }
        const row = document.createElement('div'); row.className = `slides-outline-item${item.id === state.current ? ' active' : ''}`
        row.dataset.slideIndex = String(item.id); row.id = `slides-outline-slide-${item.id}`; row.setAttribute('role', 'option'); row.setAttribute('aria-selected', String(item.id === state.current))
        const number = document.createElement('span'); number.className = 'slides-outline-num'; number.textContent = String(index + 1)
        const body = document.createElement('div'); body.className = 'slides-outline-body'
        const title = document.createElement('div'); title.className = 'slides-outline-title'; title.textContent = outline.title || '（无文字）'; body.append(title)
        for (const text of outline.lines.slice(0, 5)) { const line = document.createElement('div'); line.className = 'slides-outline-line'; line.textContent = text; body.append(line) }
        if (outline.lines.length > 5) { const more = document.createElement('div'); more.className = 'slides-outline-line slides-outline-more'; more.textContent = '…'; body.append(more) }
        row.append(number, body); row.addEventListener('click', () => select(item.id)); return row
      }))
    },
    focus() { host.focus({ preventScroll: true }) },
    dispose() { disposed = true; host.removeEventListener('keydown', keydown); host.replaceChildren() },
  }
}

/** 源 Reading 是静态 SlideThumb 逐页浏览，不调用 SlideShowView 或动画/媒体执行器。 */
export function createSlidesReading(host: HTMLElement, options: Options) {
  const root = createRoot(host)
  let state: SlidesSorterState = { slides: [], current: -1, locked: true }, disposed = false
  host.className = 'slides-reading-view'; host.tabIndex = 0; host.setAttribute('role', 'region'); host.setAttribute('aria-label', '幻灯片阅读视图')
  const navigate = (delta: number) => {
    if (disposed || host.hidden || state.locked) return
    const current = state.slides.findIndex(item => item.id === state.current), item = state.slides[Math.max(0, Math.min(state.slides.length - 1, current + delta))]
    if (item && options.onSelect(item.id)) host.focus({ preventScroll: true })
  }
  const render = () => {
    if (disposed) return
    const index = state.slides.findIndex(item => item.id === state.current), item = state.slides[index]
    const availableWidth = Math.max(1, (host.clientWidth || window.innerWidth - 120) - 40), availableHeight = Math.max(1, (host.clientHeight || window.innerHeight - 252) - 100)
    const width = item?.slide ? Math.round(Math.min(availableWidth, availableHeight * item.slide.widthPx / item.slide.heightPx)) : 208
    root.render(<><button type="button" className="slides-reading-slide" aria-label="单击翻到下一页（Esc 退出阅读视图）" disabled={state.locked} onClick={() => navigate(1)}><SlideViewThumbnail slide={item?.slide} width={width} /></button>
      <div className="slides-reading-bar" role="group" aria-label="阅读视图翻页">
        <button type="button" disabled={state.locked || index <= 0} onClick={() => navigate(-1)}>‹ 上一页</button>
        <span className="slides-reading-page" role="status" aria-label="阅读页码">{index + 1} / {state.slides.length}</span>
        <button type="button" disabled={state.locked || index >= state.slides.length - 1} onClick={() => navigate(1)}>下一页 ›</button>
        <button type="button" className="slides-reading-exit" disabled={state.locked} onClick={options.onNormal}>退出阅读视图</button>
      </div><p className="slides-reading-note">静态逐页浏览 · 不播放动画、转场和音视频</p></>)
  }
  const keydown = (event: KeyboardEvent) => {
    if (disposed || host.hidden || state.locked || !host.contains(document.activeElement) || event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.ctrlKey || event.metaKey || event.altKey) return
    if (event.target instanceof Element && event.target.closest('input,textarea,select,[contenteditable="true"]')) return
    // 浏览器按钮保留Enter/空格原生激活，避免按钮与阅读捕获层各翻一次。
    if ((event.key === 'Enter' || event.key === ' ') && event.target instanceof Element && event.target.closest('button')) return
    if (!['Escape', 'ArrowRight', 'ArrowDown', ' ', 'PageDown', 'Enter', 'ArrowLeft', 'ArrowUp', 'PageUp'].includes(event.key)) return
    event.preventDefault(); event.stopImmediatePropagation()
    if (event.key === 'Escape') options.onNormal()
    else navigate(['ArrowLeft', 'ArrowUp', 'PageUp'].includes(event.key) ? -1 : 1)
  }
  const observer = new ResizeObserver(render); observer.observe(host)
  window.addEventListener('keydown', keydown, true); window.addEventListener('resize', render)
  return {
    update(next: SlidesSorterState) { if (!disposed) { state = next; render() } },
    focus() { host.focus({ preventScroll: true }); render() },
    dispose() { disposed = true; observer.disconnect(); window.removeEventListener('keydown', keydown, true); window.removeEventListener('resize', render); root.unmount() },
  }
}
