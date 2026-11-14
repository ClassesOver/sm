import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import type { RenderSlide } from '@genoffice/pptx-render'
import { SlideThumb } from './vendor/genoffice/renderer/SlideThumb'
import { useVisibleThumbs } from './vendor/genoffice/renderer/use-visible-thumbs'
import { clickSelection, rangeSelection } from './vendor/genoffice-slides/slide-selection'
import './slides-view-modes.css'

export interface SorterSlide { id: number; title: string; hidden: boolean; slide?: RenderSlide }
export interface SlidesSorterState { slides: SorterSlide[]; current: number; locked: boolean }
type Options = {
  onSelect(id: number): boolean
  onMove(ids: number[], insertAt: number): boolean
  onDelete(ids: number[]): void
  onNormal(): void
}

/** 固定源 SlideThumb 与主画布共用 StaticNode；图片只读取现有渲染树中的内嵌数据。 */
export function SlideViewThumbnail({ slide, width = 208 }: { slide?: RenderSlide; width?: number }) {
  const [images, setImages] = useState(new Map<string, HTMLImageElement>())
  useEffect(() => {
    let disposed = false
    const urls = new Set<string>()
    const collect = (value: unknown) => {
      if (typeof value === 'string' && value.startsWith('data:image/')) urls.add(value)
      else if (value && typeof value === 'object') Object.values(value).forEach(collect)
    }
    collect(slide)
    for (const url of urls) {
      const image = new Image()
      image.onload = () => { if (!disposed) setImages(previous => new Map(previous).set(url, image)) }
      image.src = url
    }
    return () => { disposed = true }
  }, [slide])
  return slide ? <SlideThumb slide={slide} images={images} width={width} /> : <div className="slides-sorter-unavailable" role="status">缩略图暂不可用</div>
}

/** 沿用源可见区域懒绘制，避免长文稿同时保留数百个 Konva 画布。 */
function SorterViewport({ host, state, children }: { host: HTMLElement; state: SlidesSorterState; children: (visible: ReadonlySet<number>) => React.ReactNode }) {
  const ref = useRef(host)
  const visible = useVisibleThumbs(ref, '.slides-sorter-item', [state.slides.map(item => item.id).join(',')])
  useLayoutEffect(() => {
    if (document.activeElement === host) host.querySelector<HTMLElement>(`[data-slide-index="${state.current}"]`)?.scrollIntoView?.({ block: 'nearest' })
  }, [host, state.current])
  return children(visible)
}

/** 视图只持有选择状态；页面身份、顺序、草稿和历史仍由现有编辑器管理。 */
export function createSlidesSorter(host: HTMLElement, options: Options) {
  const root = createRoot(host)
  let state: SlidesSorterState = { slides: [], current: -1, locked: true }
  let selected: number[] = []
  let dragged: number | null = null
  let dropPos: number | null = null
  let disposed = false
  host.classList.add('slides-sorter-view')
  host.setAttribute('role', 'listbox')
  host.setAttribute('aria-label', '幻灯片浏览视图')
  host.setAttribute('aria-multiselectable', 'true')
  host.tabIndex = 0
  const select = (index: number, mods: { shift?: boolean; toggle?: boolean } = {}) => {
    if (disposed || state.locked || !state.slides[index]) return false
    const before = selected
    const next = clickSelection({ selected: selected.map(id => state.slides.findIndex(item => item.id === id)), current: state.slides.findIndex(item => item.id === state.current) }, index, mods)
    selected = next.selected.map(position => state.slides[position]!.id)
    if (!options.onSelect(state.slides[next.current]!.id)) { selected = before; return false }
    host.focus({ preventScroll: true }); render(); return true
  }
  const beforeTarget = (event: React.DragEvent<HTMLDivElement>, index: number) => index + (event.clientX >= event.currentTarget.getBoundingClientRect().left + event.currentTarget.getBoundingClientRect().width / 2 ? 1 : 0)
  const render = () => {
    if (disposed) return
    host.setAttribute('aria-activedescendant', `slides-sorter-slide-${state.current}`)
    root.render(<SorterViewport host={host} state={state}>{visible => <>{state.slides.map((item, index) => <div key={item.id} data-index={index} id={`slides-sorter-slide-${item.id}`} data-slide-index={item.id} data-position={index}
      role="option" aria-selected={selected.includes(item.id)} aria-label={`${index + 1}. ${item.title}${item.hidden ? '（已隐藏）' : ''}`}
      className={`slides-sorter-item${item.id === state.current ? ' active' : selected.includes(item.id) ? ' selected' : ''}${item.hidden ? ' thumb-hidden' : ''}${dragged !== null && selected.includes(item.id) ? ' dragging' : ''}${dropPos === index ? ' drop-before' : ''}${dropPos === state.slides.length && index === state.slides.length - 1 ? ' drop-after' : ''}`}
      draggable={!state.locked}
      onClick={event => select(index, { shift: event.shiftKey, toggle: event.ctrlKey || event.metaKey })}
      onDoubleClick={() => { if (select(index)) options.onNormal() }}
      onDragStart={event => {
        if (state.locked || (!selected.includes(item.id) && !select(index))) { event.preventDefault(); return }
        dragged = item.id; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(item.id)); render()
      }}
      onDragOver={event => { if (dragged === null || state.locked) return; event.preventDefault(); event.dataTransfer.dropEffect = 'move'; dropPos = beforeTarget(event, index); render() }}
      onDrop={event => {
        if (dragged === null || state.locked) return
        event.preventDefault()
        // 与固定源一致，以最终落点重新计算插入缝隙，不信任上次 dragover。
        const at = beforeTarget(event, index), ids = state.slides.filter(slide => selected.includes(slide.id)).map(slide => slide.id)
        dragged = null; dropPos = null; options.onMove(ids, at); render()
      }}
      onDragEnd={() => { dragged = null; dropPos = null; render() }}>
      <div className="slides-sorter-paper" style={{ height: item.slide ? item.slide.heightPx * 208 / item.slide.widthPx : 117 }}>{visible.has(index) && <SlideViewThumbnail slide={item.slide} />}</div><span className="slides-sorter-num">{index + 1}</span>
      {item.hidden && <span className="slides-sorter-hidden">已隐藏</span>}
      <span className="slides-sorter-title">{item.title}</span>
    </div>)}</>}</SorterViewport>)
  }
  const keydown = (event: KeyboardEvent) => {
    if (disposed || state.locked || event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.target !== host || event.altKey) return
    const mod = event.ctrlKey || event.metaKey, current = state.slides.findIndex(item => item.id === state.current)
    if (!state.slides.length) return
    if (mod && event.key.toLowerCase() === 'a') { event.preventDefault(); selected = state.slides.map(item => item.id); render(); return }
    if (mod) return
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      const edge = event.key === 'Home' ? 0 : state.slides.length - 1
      if ((event.key === 'Home' || event.key === 'End') && event.shiftKey) {
        const before = selected
        selected = rangeSelection(current, edge).map(index => state.slides[index]!.id)
        if (!options.onSelect(state.current)) selected = before
        render()
      } else select(event.key === 'Home' || event.key === 'End' ? edge : Math.max(0, Math.min(state.slides.length - 1, current + (event.key === 'ArrowUp' || event.key === 'PageUp' ? -1 : 1))))
    } else if ((event.key === 'Delete' || event.key === 'Backspace') && (window.getSelection()?.isCollapsed ?? true)) {
      event.preventDefault(); options.onDelete([...selected])
    }
  }
  host.addEventListener('keydown', keydown)
  return {
    update(next: SlidesSorterState) {
      if (disposed) return
      state = next
      selected = selected.filter(id => state.slides.some(item => item.id === id))
      if (!selected.includes(state.current)) selected = [state.current]
      render()
    },
    focus() { host.focus({ preventScroll: true }) },
    dispose() { disposed = true; host.removeEventListener('keydown', keydown); root.unmount() },
  }
}
