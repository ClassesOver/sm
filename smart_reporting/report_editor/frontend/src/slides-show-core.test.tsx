import { act } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { RenderSlide } from '@genoffice/pptx-render'
import { openSlidesShow } from './slides-show'

vi.mock('react-konva', async () => {
  const React = await import('react')
  const container = ({ children, opacity }: any) => React.createElement('div', { 'data-opacity': opacity }, children)
  return { Stage: container, Layer: container, Group: container, Rect: () => null }
})
vi.mock('./vendor/genoffice/renderer/NodeBody', () => ({ StaticNode: ({ node }: any) => <span>{node.id}</span> }))
const slides = ['一', '二', '三'].map((id, index) => ({ widthPx: 960, heightPx: 540, hidden: index === 1,
  background: { kind: 'solid', color: '#ffffff' }, nodes: [{ id, sourceId: id, type: 'shape', box: { x: 10, y: 10, w: 100, h: 50, centerX: 60, centerY: 35, rotationDeg: 0 } }] })) as unknown as RenderSlide[]
let show: ReturnType<typeof openSlidesShow> | undefined
const key = async (value: string) => act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true })) })
const tick = async (ms = 1000) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
const counter = () => document.querySelector('[aria-label="放映页码"]')?.textContent
beforeEach(() => {
  vi.useFakeTimers(); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function () { this.open = true } })
})
afterEach(async () => { await act(async () => show?.dispose()); show = undefined; document.body.replaceChildren(); vi.unstubAllGlobals(); vi.useRealTimers() })

it('来源动画先按step播放，再跳过隐藏页翻页，末页进入结束屏后再次前进才退出', async () => {
  const onClose = vi.fn(), before = JSON.stringify(slides)
  await act(async () => { show = openSlidesShow(document.body, { slides, onClose,
    animations: [[{ sourceId: '一', targetName: '一', effect: 'appear', trigger: 'onClick', durationMs: 100, delayMs: 0 }], [], []],
  } as any) })
  await tick(); expect(counter()).toBe('1 / 2')
  expect(document.querySelector('.slideshow')!.textContent).not.toContain('一')
  await key('ArrowRight'); await tick(); expect(counter()).toBe('1 / 2')
  expect(document.querySelector('.slideshow')!.textContent).toContain('一')
  await key('ArrowRight'); expect(counter()).toBe('2 / 2')
  await key('ArrowRight'); expect(document.querySelector('.ss-end')).not.toBeNull(); expect(onClose).not.toHaveBeenCalled()
  await key('ArrowLeft'); expect(document.querySelector('.ss-end')).toBeNull()
  await key('ArrowRight'); await key('ArrowRight'); expect(onClose).toHaveBeenCalledOnce()
  expect(JSON.stringify(slides)).toBe(before)
})

it('黑白屏先恢复而不翻页，数字Enter遵守来源页码且可从隐藏当前页起播', async () => {
  await act(async () => { show = openSlidesShow(document.body, { slides, startIndex: 1, onClose() {} }) })
  await tick(); expect(counter()).toBe('2 / 3')
  await key('b'); expect(document.querySelector('.ss-black')).not.toBeNull()
  await key('ArrowRight'); expect(document.querySelector('.ss-black')).toBeNull(); expect(counter()).toBe('2 / 3')
  await key('w'); expect(document.querySelector('.ss-white')).not.toBeNull()
  await key('w'); expect(document.querySelector('.ss-white')).toBeNull()
  await key('3'); await key('Enter'); expect(counter()).toBe('3 / 3')
  await key('1'); await key('Escape'); expect(document.querySelector('.slides-show')).not.toBeNull()
  await key('Escape'); expect(document.querySelector('.slides-show')).toBeNull()
})

it('右键菜单操作只执行一次，看全部页可跳页并返回上次查看', async () => {
  await act(async () => { show = openSlidesShow(document.body, { slides, onClose() {} }) }); await tick()
  const openMenu = async () => { await act(async () => { (document.querySelector('.slideshow') ?? document.querySelector('.slides-show-stage'))!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 20, clientY: 20 })) }); expect(document.querySelector('.ctx-menu')).not.toBeNull() }
  const choose = async (text: string) => act(async () => { [...document.querySelectorAll<HTMLButtonElement>('.ctx-item')].find(node => node.textContent?.includes(text))!.click() })
  await openMenu(); await choose('查看所有幻灯片'); expect(document.querySelectorAll('.ss-grid-item')).toHaveLength(2)
  await act(async () => document.querySelectorAll<HTMLButtonElement>('.ss-grid-item')[1]!.click()); expect(counter()).toBe('2 / 2')
  await openMenu(); await choose('上次查看'); expect(counter()).toBe('1 / 2')
  await openMenu(); await choose('下一页'); expect(counter()).toBe('2 / 2')
  expect(document.querySelector('.ss-end')).toBeNull()
})

it('菜单与看全部页接管焦点，Tab不逃至编辑器，Escape只关闭当前层', async () => {
  const onClose = vi.fn()
  await act(async () => { show = openSlidesShow(document.body, { slides, onClose }) }); await tick()
  await act(async () => document.querySelector('.slideshow')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 20, clientY: 20 })))
  const menu = document.querySelector<HTMLElement>('.ctx-menu')!
  expect(menu.contains(document.activeElement)).toBe(true)
  await key('End'); expect((document.activeElement as HTMLElement).textContent).toContain('结束放映')
  await key('Home'); expect((document.activeElement as HTMLElement).textContent).toContain('下一页')
  const enabled = [...menu.querySelectorAll<HTMLButtonElement>('.ctx-item:not([disabled])')]
  enabled.forEach(button => Object.defineProperty(button, 'offsetParent', { configurable: true, get: () => menu }))
  enabled.at(-1)!.focus()
  const tab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
  enabled.at(-1)!.dispatchEvent(tab); expect(tab.defaultPrevented).toBe(true); expect(document.activeElement).toBe(enabled[0])
  await act(async () => enabled.find(node => node.textContent?.includes('查看所有幻灯片'))!.click())
  expect(document.activeElement?.classList.contains('ss-grid-item')).toBe(true)
  await key('Escape'); expect(document.querySelector('.ss-grid')).toBeNull(); expect(onClose).not.toHaveBeenCalled()
  expect(document.querySelector('.slides-show')!.contains(document.activeElement)).toBe(true)
  await key('Escape'); expect(onClose).toHaveBeenCalledOnce()
})

it('从后页打开看全部页时焦点落在当前页，不能悄悄跳回第一页', async () => {
  await act(async () => { show = openSlidesShow(document.body, { slides, startIndex: 2, onClose() {} }) }); await tick()
  await act(async () => document.querySelector('.slideshow')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true })))
  await act(async () => [...document.querySelectorAll<HTMLButtonElement>('.ctx-item')].find(node => node.textContent?.includes('查看所有幻灯片'))!.click())
  expect(document.activeElement?.classList.contains('ss-grid-cur')).toBe(true)
})

it('前进挂接来源转场类，返回和数字跳页不重放转场，random选用源支持效果', async () => {
  vi.spyOn(Math, 'random').mockReturnValue(0)
  await act(async () => { show = openSlidesShow(document.body, { slides, transitions: ['none', 'none', 'push'], onClose() {} }) }); await tick()
  await key('ArrowRight'); expect(document.querySelector('.ss-frame')?.classList.contains('ss-anim-push')).toBe(true)
  await key('ArrowLeft'); expect(document.querySelector('.ss-frame')?.className).toBe('ss-frame')
  await key('3'); await key('Enter'); expect(document.querySelector('.ss-frame')?.className).toBe('ss-frame')
  await act(async () => show!.dispose())
  await act(async () => { show = openSlidesShow(document.body, { slides, transitions: ['none', 'none', 'random'], onClose() {} }) }); await tick()
  await key('ArrowRight'); expect(document.querySelector('.ss-frame')?.classList.contains('ss-anim-fade')).toBe(true)
  vi.restoreAllMocks()
})

it('控制栏退出也返回最后查看的完整数组页号，用于退出后定位编辑页', async () => {
  const onClose = vi.fn()
  await act(async () => { show = openSlidesShow(document.body, { slides, onClose }) }); await tick()
  await key('ArrowRight'); expect(counter()).toBe('2 / 2')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="退出放映"]')!.click())
  expect(onClose).toHaveBeenCalledExactlyOnceWith(2)
})
