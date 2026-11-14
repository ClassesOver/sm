import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import type { RenderSlide } from '@genoffice/pptx-render'
import type { AnimationItem } from './vendor/genoffice/animation-types'
import { AnimPreviewOverlay } from './vendor/genoffice/renderer/AnimatedSlide'
import { installFocusTrap } from './focus-trap'
import './slides-animation-preview.css'

/** 固定源 AnimPreviewOverlay 的浏览器画布宿主：源播放器负责rAF/步进，关闭即卸载。 */
export function openSlidesAnimationPreview(host: HTMLElement, options: { slide: RenderSlide; items: AnimationItem[]; warnings?: string[]; onClose(): void }) {
  const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : undefined
  const overlay = document.createElement('section'); overlay.className = 'slides-animation-preview'; overlay.tabIndex = 0
  overlay.setAttribute('role', 'region'); overlay.setAttribute('aria-label', '动画预览')
  const stage = document.createElement('div'); stage.className = 'slides-animation-preview-stage'
  const footer = document.createElement('div'); footer.className = 'slides-animation-preview-controls'
  const note = document.createElement('span'); note.textContent = options.warnings?.length ? options.warnings.join('；') : '动画预览 · 单击画面或按 Esc 结束'
  note.setAttribute('role', 'status')
  const exit = document.createElement('button'); exit.type = 'button'; exit.textContent = '结束预览'
  footer.append(note, exit); overlay.append(stage, footer); host.append(overlay)
  const root = createRoot(stage), images = new Map<string, HTMLImageElement>()
  const releaseFocus = installFocusTrap(overlay)
  let disposed = false
  const dispose = () => {
    if (disposed) return
    disposed = true; observer.disconnect(); releaseFocus(); window.removeEventListener('keydown', keydown, true)
    for (const image of images.values()) image.onload = null
    root.unmount(); overlay.remove()
    if (previousFocus?.isConnected) previousFocus.focus()
    options.onClose()
  }
  const render = () => {
    if (disposed) return
    const width = Math.max(1, Math.min(stage.clientWidth || host.clientWidth || options.slide.widthPx,
      (stage.clientHeight || host.clientHeight || options.slide.heightPx) * options.slide.widthPx / options.slide.heightPx))
    root.render(createElement(AnimPreviewOverlay, { slide: options.slide, items: options.items, images, width, onDone: dispose }))
  }
  const observer = new ResizeObserver(render); observer.observe(stage)
  const keydown = (event: KeyboardEvent) => {
    if (!overlay.contains(document.activeElement) || event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.key === 'Tab') return
    // 预览区的按键不能同时变成编辑器删除、粘贴或移动对象。
    event.stopImmediatePropagation()
    if (event.key === 'Escape') { event.preventDefault(); dispose() }
  }
  window.addEventListener('keydown', keydown, true); exit.addEventListener('click', dispose)
  const urls = new Set<string>()
  const collect = (value: unknown) => {
    if (typeof value === 'string' && value.startsWith('data:image/')) urls.add(value)
    else if (value && typeof value === 'object') Object.values(value).forEach(collect)
  }
  collect(options.slide)
  for (const url of urls) { const image = new Image(); image.onload = () => { if (!disposed) { images.set(url, image); render() } }; image.src = url; images.set(url, image) }
  exit.focus({ preventScroll: true }); overlay.scrollIntoView?.({ block: 'nearest', inline: 'nearest' }); render()
  return { dispose }
}
