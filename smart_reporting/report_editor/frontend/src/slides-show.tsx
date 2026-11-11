import React from 'react'
import { createRoot } from 'react-dom/client'
import { Layer, Rect, Stage } from 'react-konva'
import type { RenderSlide } from '@genoffice/pptx-render'
import { StaticNode } from './vendor/genoffice/renderer/NodeBody'
import { fillToKonva } from './vendor/genoffice/renderer/konva-adapter'
import './slides-show.css'

/** slides 已按播放顺序排好且过滤隐藏页；startIndex 是该数组的零基下标。 */
export type SlidesShowOptions = { slides: RenderSlide[]; startIndex?: number; onClose: () => void }

/** 只读静态放映，不解析 PPTX，也不执行动画、转场、演讲者视图或音视频。 */
export function openSlidesShow(host: HTMLElement, options: SlidesShowOptions): { dispose(): void } {
  const slides = options.slides.slice()
  const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : undefined
  const dialog = document.createElement('dialog')
  dialog.className = 'slides-show'
  dialog.setAttribute('aria-label', '静态幻灯片放映')
  dialog.tabIndex = -1
  const stageHost = document.createElement('div'); stageHost.className = 'slides-show-stage'
  const toolbar = document.createElement('div'); toolbar.className = 'slides-show-controls'
  const previous = document.createElement('button'); previous.type = 'button'; previous.textContent = '上一页'; previous.setAttribute('aria-label', '上一页')
  const next = document.createElement('button'); next.type = 'button'; next.textContent = '下一页'; next.setAttribute('aria-label', '下一页')
  const exit = document.createElement('button'); exit.type = 'button'; exit.textContent = '退出放映'; exit.setAttribute('aria-label', '退出放映')
  const counter = document.createElement('span'); counter.setAttribute('aria-label', '放映页码'); counter.setAttribute('aria-live', 'polite')
  const note = document.createElement('p'); note.className = 'slides-show-note'; note.textContent = '只读静态放映 · 不播放动画、转场和音视频，无演讲者视图'
  toolbar.append(previous, counter, next, exit)
  dialog.append(stageHost, toolbar, note); host.append(dialog)
  const root = createRoot(stageHost)
  let images = new Map<string, HTMLImageElement>()
  let disposed = false
  let enteredFullscreen = false
  let index = Math.min(Math.max(0, Number.isInteger(options.startIndex) ? options.startIndex! : 0), Math.max(0, slides.length - 1))
  const render = () => {
    if (disposed) return
    const slide = slides[index]
    counter.textContent = slides.length ? String(index + 1) + ' / ' + slides.length : '0 / 0'
    previous.disabled = !slides.length || index === 0; next.disabled = !slides.length || index === slides.length - 1
    if (!slide) { root.render(<p>没有可放映页面</p>); return }
    const availableWidth = stageHost.clientWidth || Math.max(1, window.innerWidth - 32)
    const availableHeight = stageHost.clientHeight || Math.max(1, window.innerHeight - 120)
    const scale = Math.min(availableWidth / slide.widthPx, availableHeight / slide.heightPx)
    root.render(<Stage width={slide.widthPx * scale} height={slide.heightPx * scale} listening={false}>
      <Layer scaleX={scale} scaleY={scale} listening={false}>
        <Rect width={slide.widthPx} height={slide.heightPx} {...fillToKonva(slide.background, slide.widthPx, slide.heightPx, images)} listening={false} />
        {slide.nodes.map(node => <StaticNode key={node.id} node={node} images={images} />)}
      </Layer>
    </Stage>)
  }
  const navigate = (target: number) => { index = Math.max(0, Math.min(slides.length - 1, target)); render() }
  const observer = new ResizeObserver(render)
  observer.observe(stageHost)
  const dispose = () => {
    if (disposed) return
    disposed = true
    window.removeEventListener('keydown', onKey, true)
    window.removeEventListener('resize', render)
    document.removeEventListener('fullscreenchange', onFullscreenChange)
    observer.disconnect()
    for (const image of images.values()) image.onload = null
    root.unmount(); dialog.remove()
    if (document.fullscreenElement === dialog) { try { void document.exitFullscreen().catch(() => {}) } catch {} }
    if (previousFocus?.isConnected) previousFocus.focus()
    options.onClose()
  }
  const onKey = (event: KeyboardEvent) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return
    // 捕获本视图的按键，避免同时触发编辑器快捷键。
    if (!['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'ArrowLeft', 'ArrowUp', 'PageUp', 'Home', 'End', 'Escape'].includes(event.key)) return
    event.preventDefault(); event.stopImmediatePropagation()
    if (event.key === 'Escape') dispose()
    else if (event.key === 'Home') navigate(0)
    else if (event.key === 'End') navigate(slides.length - 1)
    else navigate(index + (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(event.key) ? -1 : 1))
  }
  const onFullscreenChange = () => {
    if (document.fullscreenElement === dialog) enteredFullscreen = true
    else if (enteredFullscreen) dispose()
  }
  previous.addEventListener('click', () => navigate(index - 1))
  next.addEventListener('click', () => navigate(index + 1))
  exit.addEventListener('click', dispose)
  dialog.addEventListener('cancel', event => { event.preventDefault(); dispose() })
  dialog.addEventListener('close', dispose)
  window.addEventListener('keydown', onKey, true)
  window.addEventListener('resize', render)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  // 复用现有渲染树的内嵌图片；加载完成仅重绘本次只读快照。
  const urls = new Set<string>()
  const collect = (value: unknown) => {
    if (typeof value === 'string' && value.startsWith('data:image/')) urls.add(value)
    else if (value && typeof value === 'object') for (const child of Object.values(value)) collect(child)
  }
  collect(slides)
  for (const url of urls) {
    const image = new Image(); images.set(url, image)
    image.onload = () => { if (!disposed) { images = new Map(images); render() } }; image.src = url
  }
  dialog.showModal(); dialog.focus(); render()
  // 浏览器拒绝全屏或不支持时，保留可操作的普通对话框。
  try { void dialog.requestFullscreen?.().catch(() => {}) } catch {}
  return { dispose }
}
