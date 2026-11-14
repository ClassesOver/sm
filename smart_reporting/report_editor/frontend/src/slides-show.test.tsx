import { act } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { RenderSlide } from '@genoffice/pptx-render'
import { openSlidesShow } from './slides-show'

vi.mock('react-konva', async () => {
  const React = await import('react')
  const container = ({ children }: any) => React.createElement('div', null, children)
  return { Stage: container, Layer: container, Group: container, Rect: () => null }
})
vi.mock('./vendor/genoffice/renderer/NodeBody', async () => {
  const React = await import('react')
  return { StaticNode: React.memo(({ node, images }: any) => React.createElement('span', null, node.id + (node.imageUrl && images.get(node.imageUrl)?.complete ? '已载图' : ''))) }
})
vi.mock('./vendor/genoffice/renderer/konva-adapter', () => ({ fillToKonva: () => ({}) }))

const resize = { disconnected: vi.fn() }
let show: ReturnType<typeof openSlidesShow> | undefined
const slides = ['第一页', '第二页', '第三页'].map(id => ({ widthPx: 960, heightPx: 540, scale: 1, background: { kind: 'solid', color: '#fff' }, nodes: [{ id, sourceId: id, type: 'shape', box: { x: 0, y: 0, w: 100, h: 50, centerX: 50, centerY: 25, rotationDeg: 0 } }] })) as RenderSlide[]
const key = async (value: string) => { await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true }))) }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() { resize.disconnected() } })
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.open = true } })
  resize.disconnected.mockClear()
})
afterEach(async () => { await act(async () => show?.dispose()); show = undefined; document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('从当前页开始且按给定可播放顺序导航，末页不越界', async () => {
  await act(async () => { show = openSlidesShow(document.body, { slides, startIndex: 1, onClose() {} }) })
  const page = () => document.querySelector('[aria-label="放映页码"]')!.textContent
  expect(page()).toBe('2 / 3')
  expect(document.querySelector('.slides-show-stage')!.textContent).toContain('第二页')
  await key('ArrowRight'); expect(page()).toBe('3 / 3')
  await key('PageDown'); expect(document.querySelector('.ss-end')).not.toBeNull()
  await key('PageUp'); expect(page()).toBe('3 / 3')
  expect(document.querySelector<HTMLButtonElement>('[aria-label="下一页"]')!.disabled).toBe(false)
  await key('Home'); expect(page()).toBe('1 / 3')
  await key('PageUp'); expect(page()).toBe('1 / 3')
  await key('End'); await key('ArrowLeft'); expect(page()).toBe('2 / 3')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="上一页"]')!.click())
  expect(page()).toBe('1 / 3')
})

it('退出只触发一次，释放键盘和resize并恢复焦点，不修改输入快照', async () => {
  const focus = document.body.appendChild(document.createElement('button')); focus.focus()
  const onClose = vi.fn(), before = JSON.stringify(slides), otherKey = vi.fn()
  await act(async () => { show = openSlidesShow(document.body, { slides, onClose }) })
  window.addEventListener('keydown', otherKey)
  await key('ArrowRight'); expect(otherKey).not.toHaveBeenCalled()
  await key('Escape')
  expect(document.querySelector('.slides-show')).toBeNull()
  expect(onClose).toHaveBeenCalledTimes(1)
  expect(document.activeElement).toBe(focus)
  expect(resize.disconnected).toHaveBeenCalledTimes(1)
  await key('ArrowRight'); expect(otherKey).toHaveBeenCalledTimes(1)
  await act(async () => show!.dispose()); expect(onClose).toHaveBeenCalledTimes(1)
  expect(JSON.stringify(slides)).toBe(before)
  window.removeEventListener('keydown', otherKey)
})

it('全屏被拒绝仍可正常放映，空页和越界起点有明确结果', async () => {
  const requestFullscreen = vi.fn(async () => { throw new Error('denied') })
  Object.defineProperty(HTMLDialogElement.prototype, 'requestFullscreen', { configurable: true, value: requestFullscreen })
  await act(async () => { show = openSlidesShow(document.body, { slides, startIndex: 99, onClose() {} }) })
  expect(requestFullscreen).toHaveBeenCalledOnce()
  expect(document.querySelector('[aria-label="放映页码"]')!.textContent).toBe('3 / 3')
  expect(document.querySelector('dialog')!.open).toBe(true)
  await act(async () => show!.dispose())
  await act(async () => { show = openSlidesShow(document.body, { slides: [], onClose() {} }) })
  expect(document.querySelector('.slides-show-stage')!.textContent).toContain('没有可放映页面')
  expect(document.querySelector('[aria-label="放映页码"]')!.textContent).toBe('0 / 0')
  delete (HTMLDialogElement.prototype as any).requestFullscreen
})

it('图片异步加载后更新静态节点，关闭后的加载不重建界面', async () => {
  const loaded: { onload: null | (() => void); src: string; complete: boolean }[] = []
  vi.stubGlobal('Image', class { onload = null; src = ''; complete = false; constructor() { loaded.push(this) } })
  const imageSlides = [{ ...slides[0], nodes: [{ ...slides[0]!.nodes[0], imageUrl: 'data:image/png;base64,a' }] }] as unknown as RenderSlide[]
  await act(async () => { show = openSlidesShow(document.body, { slides: imageSlides, onClose() {} }) })
  expect(document.querySelector('.slides-show-stage')!.textContent).not.toContain('已载图')
  await act(async () => { loaded[0]!.complete = true; loaded[0]!.onload!() })
  expect(document.querySelector('.slides-show-stage')!.textContent).toContain('已载图')
  const stale = loaded[0]!.onload!
  await act(async () => show!.dispose())
  await act(async () => stale())
  expect(document.querySelector('.slides-show')).toBeNull()
})

it('浏览器Esc退出已进入的全屏时同步关闭放映', async () => {
  const onClose = vi.fn()
  await act(async () => { show = openSlidesShow(document.body, { slides, onClose }) })
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: document.querySelector('dialog') })
  await act(async () => document.dispatchEvent(new Event('fullscreenchange')))
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
  await act(async () => document.dispatchEvent(new Event('fullscreenchange')))
  expect(onClose).toHaveBeenCalledOnce()
  expect(document.querySelector('.slides-show')).toBeNull()
  delete (document as any).fullscreenElement
})

it('工具栏按钮的空格保留原生激活，不被全局翻页抢走',async()=>{
 const onClose=vi.fn(),outside=vi.fn()
 await act(async()=>{show=openSlidesShow(document.body,{slides,onClose})})
 const exit=document.querySelector<HTMLButtonElement>('[aria-label="退出放映"]')!;exit.focus()
 const event=new KeyboardEvent('keydown',{key:' ',bubbles:true,cancelable:true});window.addEventListener('keydown',outside)
 await act(async()=>exit.dispatchEvent(event))
 window.removeEventListener('keydown',outside)
 expect(event.defaultPrevented).toBe(false);expect(outside).not.toHaveBeenCalled();expect(document.querySelector('[aria-label="放映页码"]')!.textContent).toBe('1 / 3')
 await act(async()=>exit.click());expect(onClose).toHaveBeenCalledOnce()
})

it('输入法组合按键不翻页也不提前退出',async()=>{
 const onClose=vi.fn();await act(async()=>{show=openSlidesShow(document.body,{slides,onClose})})
 for(const value of ['ArrowRight','Home','End','Escape']){
  await act(async()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:value,isComposing:true,bubbles:true,cancelable:true})))
  expect(document.querySelector('[aria-label="放映页码"]')?.textContent).toBe('1 / 3');expect(onClose).not.toHaveBeenCalled()
 }
})

it('第一页的上一页禁用后恢复到下一步，末页仍可进入结束屏',async()=>{
 await act(async()=>{show=openSlidesShow(document.body,{slides,startIndex:1,onClose(){}})})
 const next=document.querySelector<HTMLButtonElement>('[aria-label="下一页"]')!,previous=document.querySelector<HTMLButtonElement>('[aria-label="上一页"]')!
 previous.focus();await act(async()=>previous.click());expect(previous.disabled).toBe(true);expect(document.activeElement).toBe(next)
 await key('End');expect(next.disabled).toBe(false);await act(async()=>next.click());expect(document.querySelector('.ss-end')).not.toBeNull()
})

it('自定义放映按重复序列播放并返回最后来源页，不借用普通页序',async()=>{
 const onClose=vi.fn();await act(async()=>{show=openSlidesShow(document.body,{slides,startIndex:2,customOrder:[2,0,2],onClose})})
 const counter=()=>document.querySelector('[aria-label="放映页码"]')!.textContent
 expect(counter()).toBe('1 / 3');expect(document.querySelector('.slides-show-stage')!.textContent).toContain('第三页')
 await key('ArrowRight');expect(counter()).toBe('2 / 3');expect(document.querySelector('.slides-show-stage')!.textContent).toContain('第一页')
 await key('ArrowRight');expect(counter()).toBe('3 / 3');expect(document.querySelector('.slides-show-stage')!.textContent).toContain('第三页')
 await act(async()=>document.querySelector<HTMLButtonElement>('[aria-label="退出放映"]')!.click());expect(onClose).toHaveBeenCalledWith(2)
})
