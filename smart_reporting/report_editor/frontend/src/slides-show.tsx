import type { SlideMediaSource } from './slides-media'
import React from 'react'
import { createRoot } from 'react-dom/client'
import type { RenderSlide } from '@genoffice/pptx-render'
import type { AnimationItem } from './vendor/genoffice/animation-types'
import type { LinkTargetOp, ShapeKey, TransitionKind } from './vendor/genoffice/renderer/show-types'
import { SlideShowView, type ShowViewState } from './vendor/genoffice/renderer/SlideShowView'
import { INITIAL_SHOW_KEYS, reduceShowKey } from './vendor/genoffice/renderer/show-keys'
import { installFocusTrap } from './focus-trap'
import './slides-show.css'

/** 完整渲染快照按草稿顺序排列；隐藏页交由固定源computePlayOrder处理，startIndex按该完整数组。 */
export type SlidesShowOptions = {
  customOrder?:number[];
  mediaSources?: readonly (readonly SlideMediaSource[])[];
  slides: RenderSlide[]; startIndex?: number; animations?: AnimationItem[][]; transitions?: TransitionKind[];
  shapeKeys?: ShapeKey[][]; links?: Array<Array<{ sourceId: string; target: LinkTargetOp }>>; warnings?: string[];
  onClose: (lastIndex?: number) => void;
}

/** 固定源真实放映核心的浏览器宿主；快照只读，全部动画/转场由源组件执行。 */
export function openSlidesShow(host: HTMLElement, options: SlidesShowOptions): { dispose(): void } {
  const slides = options.slides.slice(), animations = options.animations ?? slides.map(() => []), transitions = options.transitions ?? slides.map(() => 'none' as const)
  const shapeKeys = options.shapeKeys ?? slides.map(() => []), links = options.links ?? slides.map(() => [])
  const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : undefined
  const dialog = document.createElement('dialog'); dialog.className = 'slides-show'; dialog.setAttribute('aria-label', '幻灯片放映'); dialog.tabIndex = -1
  const stageHost = document.createElement('div'); stageHost.className = 'slides-show-stage'
  const toolbar = document.createElement('div'); toolbar.className = 'slides-show-controls'; toolbar.setAttribute('role', 'group'); toolbar.setAttribute('aria-label', '放映控制')
  const previous = document.createElement('button'); previous.type = 'button'; previous.textContent = '上一页'; previous.setAttribute('aria-label', '上一页')
  const next = document.createElement('button'); next.type = 'button'; next.textContent = '下一步'; next.setAttribute('aria-label', '下一页')
  const exit = document.createElement('button'); exit.type = 'button'; exit.textContent = '退出放映'; exit.setAttribute('aria-label', '退出放映')
  const counter = document.createElement('span'); counter.setAttribute('aria-label', '放映页码'); counter.setAttribute('aria-live', 'polite'); counter.textContent = '0 / 0'
  const note = document.createElement('p'); note.className = 'slides-show-note'; note.textContent = options.warnings?.join('；') || '方向键/空格分步 · B/W 黑白屏 · 数字+Enter跳页 · 右键菜单 · Esc退出；屏幕录制及演讲者视图未验收'
  toolbar.append(previous, counter, next, exit); dialog.append(stageHost, toolbar, note); host.append(dialog)
  const root = createRoot(stageHost), releaseFocus = installFocusTrap(dialog)
  let images = new Map<string, HTMLImageElement>(), disposed = false, enteredFullscreen = false
  const startAt = Math.min(Math.max(0, Number.isInteger(options.startIndex) ? options.startIndex! : 0), Math.max(0, slides.length - 1))
  let lastIndex = startAt
  const onState = (state: ShowViewState) => {
    lastIndex = state.slideIndex
    counter.textContent = String(state.pos + 1) + ' / ' + state.count
    const focused = document.activeElement
    previous.disabled = !state.ended && state.pos === 0; next.disabled = false
    if (focused === previous && previous.disabled) next.focus()
    if (focused !== dialog && !dialog.contains(document.activeElement)) exit.focus({ preventScroll: true })
  }
  const render = () => {
    if (disposed) return
    if (!slides.length) { previous.disabled = next.disabled = true; root.render(<p>没有可放映页面</p>); return }
    root.render(<SlideShowView slides={slides} images={images} startAt={startAt} customOrder={options.customOrder} animations={animations} transitions={transitions}
      mediaSources={options.mediaSources} shapeKeys={shapeKeys} links={links} onState={onState} viewport={{ w: stageHost.clientWidth || Math.max(1, window.innerWidth - 32), h: stageHost.clientHeight || Math.max(1, window.innerHeight - 120) }}
      onExit={index => { lastIndex = index; dispose() }} />)
  }
  const observer = new ResizeObserver(render); observer.observe(stageHost)
  const dispose = () => {
    if (disposed) return
    disposed = true; window.removeEventListener('keydown', isolateKeys, true); window.removeEventListener('resize', render)
    document.removeEventListener('fullscreenchange', onFullscreenChange); observer.disconnect(); releaseFocus()
    for (const image of images.values()) image.onload = null
    root.unmount(); dialog.remove()
    if (document.fullscreenElement === dialog) { try { void document.exitFullscreen().catch(() => {}) } catch {} }
    if (previousFocus?.isConnected) previousFocus.focus()
    options.onClose(lastIndex)
  }
  const isolateKeys = (event: KeyboardEvent) => {
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.key === 'Tab') return
    // 原生按钮自己处理Enter/空格；其click只执行该按钮，不同时推进源播放器。
    const buttonKey = [' ', 'Enter'].includes(event.key) && event.target instanceof Element && event.target.closest('button')
    if (buttonKey || event.ctrlKey || event.metaKey || event.altKey || !reduceShowKey(INITIAL_SHOW_KEYS, event.key)) event.stopImmediatePropagation()
  }
  const onFullscreenChange = () => { if (document.fullscreenElement === dialog) enteredFullscreen = true; else if (enteredFullscreen) dispose() }
  const navigate = (key: string) => dialog.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  previous.addEventListener('click', () => navigate('ArrowLeft')); next.addEventListener('click', () => navigate('ArrowRight')); exit.addEventListener('click', dispose)
  dialog.addEventListener('keydown', event => event.stopPropagation())
  dialog.addEventListener('cancel', event => { event.preventDefault(); dispose() }); dialog.addEventListener('close', dispose)
  window.addEventListener('keydown', isolateKeys, true); window.addEventListener('resize', render); document.addEventListener('fullscreenchange', onFullscreenChange)
  const urls = new Set<string>()
  const collect = (value: unknown) => { if (typeof value === 'string' && value.startsWith('data:image/')) urls.add(value); else if (value && typeof value === 'object') Object.values(value).forEach(collect) }
  collect(slides)
  for (const url of urls) { const image = new Image(); images.set(url, image); image.onload = () => { if (!disposed) { images = new Map(images); render() } }; image.src = url }
  dialog.showModal(); dialog.focus(); render()
  try { void dialog.requestFullscreen?.().catch(() => {}) } catch {}
  return { dispose }
}
