import { act } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { RenderSlide } from '@genoffice/pptx-render'
import { openSlidesAnimationPreview } from './slides-animation-preview'

vi.mock('react-konva', async () => {
  const React = await import('react')
  const container = ({ children }: any) => React.createElement('div', null, children)
  return { Stage: container, Layer: container, Group: container, Rect: () => null }
})
vi.mock('./vendor/genoffice/renderer/NodeBody', () => ({ StaticNode: () => null }))
const slide = { widthPx: 960, heightPx: 540, background: { kind: 'solid', color: '#ffffff' }, nodes: [] } as unknown as RenderSlide
const items = [{ sourceId: 'title', targetName: 'title', effect: 'fade' as const, trigger: 'onClick' as const, durationMs: 100, delayMs: 0 }]
let preview: ReturnType<typeof openSlidesAnimationPreview> | undefined
const disconnected = vi.fn()
beforeEach(() => {
  vi.useFakeTimers(); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() { disconnected() } })
  disconnected.mockClear()
})
afterEach(async () => { await act(async () => preview?.dispose()); preview = undefined; document.body.replaceChildren(); vi.unstubAllGlobals(); vi.useRealTimers() })
const tick = async (ms: number) => { for (let n = 0; n < ms; n += 25) await act(async () => vi.advanceTimersByTimeAsync(25)) }

it('按源350ms步间隔播放并完成退出，恢复焦点且不改输入快照', async () => {
  const opener = document.body.appendChild(document.createElement('button')); opener.focus()
  const onClose = vi.fn(), before = JSON.stringify({ slide, items })
  await act(async () => { preview = openSlidesAnimationPreview(document.body, { slide, items, onClose }) })
  expect(document.querySelector('.slides-animation-preview')).not.toBeNull()
  await tick(1600)
  expect(document.querySelector('.slides-animation-preview')).toBeNull()
  expect(onClose).toHaveBeenCalledTimes(1); expect(document.activeElement).toBe(opener)
  expect(JSON.stringify({ slide, items })).toBe(before); expect(disconnected).toHaveBeenCalledTimes(1)
})

it.each(['Escape', 'click'])('通过%s退出释放计时/rAF/resize和捕获键盘，随后可从头再次预览', async action => {
  const onClose = vi.fn(), outside = vi.fn()
  await act(async () => { preview = openSlidesAnimationPreview(document.body, { slide, items, onClose }) })
  if (action === 'Escape') await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })))
  else await act(async () => document.querySelector<HTMLElement>('.anim-preview-overlay')!.click())
  await tick(1600); expect(onClose).toHaveBeenCalledTimes(1)
  window.addEventListener('keydown', outside)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete' })); expect(outside).toHaveBeenCalledTimes(1)
  window.removeEventListener('keydown', outside)
  await act(async () => { preview = openSlidesAnimationPreview(document.body, { slide, items, onClose }) })
  expect(document.querySelectorAll('.slides-animation-preview')).toHaveLength(1)
  await tick(1600); expect(onClose).toHaveBeenCalledTimes(2)
})

it('预览获得焦点时删除/粘贴快捷键不冒泡至编辑器，销毁后异步图片不得重建预览', async () => {
  const images: { onload: (() => void) | null; src: string }[] = []
  vi.stubGlobal('Image', class { onload = null; src = ''; constructor() { images.push(this) } })
  const imageSlide = { ...slide, background: { type: 'blip', dataUrl: 'data:image/png;base64,a' } } as unknown as RenderSlide
  const outside = vi.fn(); window.addEventListener('keydown', outside)
  await act(async () => { preview = openSlidesAnimationPreview(document.body, { slide: imageSlide, items, onClose() {} }) })
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true, cancelable: true }))
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'v', ctrlKey: true, bubbles: true, cancelable: true }))
  expect(outside).not.toHaveBeenCalled(); window.removeEventListener('keydown', outside)
  const stale = images[0]!.onload!
  await act(async () => preview!.dispose()); await act(async () => stale())
  expect(document.querySelector('.slides-animation-preview')).toBeNull()
})

it('Tab和ShiftTab圈定在结束控件，组合或已消费Escape不关闭播放器', async () => {
  const onClose = vi.fn()
  await act(async () => { preview = openSlidesAnimationPreview(document.body, { slide, items, onClose }) })
  const exit = document.querySelector<HTMLButtonElement>('.slides-animation-preview-controls button')!
  Object.defineProperty(exit, 'offsetParent', { configurable: true, get: () => exit.parentElement })
  exit.focus()
  for (const shiftKey of [false, true]) {
    const event = new KeyboardEvent('keydown', { key: 'Tab', shiftKey, bubbles: true, cancelable: true })
    exit.dispatchEvent(event); expect(event.defaultPrevented).toBe(true); expect(document.activeElement).toBe(exit)
  }
  const consumed = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }); consumed.preventDefault(); exit.dispatchEvent(consumed)
  exit.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', isComposing: true, bubbles: true, cancelable: true }))
  expect(onClose).not.toHaveBeenCalled()
})
