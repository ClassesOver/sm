import { afterEach, expect, it, vi } from 'vitest'
import { mountPdfCropCanvas } from './pdf-crop-canvas'

const controllers: ReturnType<typeof mountPdfCropCanvas>[] = []
afterEach(() => { controllers.splice(0).forEach(controller => controller.dispose()); document.body.replaceChildren() })
function fixture() {
  const host = document.createElement('div'), canvas = document.createElement('canvas')
  canvas.width = 400; canvas.height = 500; document.body.append(host)
  let enabled = true
  const change = vi.fn()
  const controller = mountPdfCropCanvas({ host, canvas, enabled: () => enabled, change })
  controllers.push(controller)
  const stage = host.querySelector<HTMLElement>('[data-pdf-crop-canvas]')!
  vi.spyOn(stage, 'getBoundingClientRect').mockReturnValue({ x: 10, y: 20, left: 10, top: 20, right: 410, bottom: 520, width: 400, height: 500, toJSON: () => ({}) })
  return { controller, host, stage, change, disable() { enabled = false } }
}
function pointer(target: EventTarget, type: string, x: number, y: number, id = 1) {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 })
  Object.defineProperties(event, { pointerId: { value: id }, isPrimary: { value: true } })
  target.dispatchEvent(event)
}

it('裁切预览提供当前边距的图像说明，鼠标控制柄不作为无效的独立命名控件', () => {
  const f = fixture()
  expect(f.stage.getAttribute('role')).toBe('img')
  expect(f.stage.getAttribute('aria-label')).toBe('裁切预览：左侧裁去 0%，顶部裁去 0%，右侧裁去 0%，底部裁去 0%')
  const region = f.host.querySelector('[data-pdf-crop-region]')!
  expect(region.getAttribute('aria-hidden')).toBe('true')
  expect(region.querySelectorAll('[aria-label]')).toHaveLength(0)
  f.controller.setMargins([10, 20, 5, 15])
  expect(f.stage.getAttribute('aria-label')).toBe('裁切预览：左侧裁去 10%，顶部裁去 20%，右侧裁去 5%，底部裁去 15%')
  pointer(region, 'pointerdown', 100, 150)
  pointer(window, 'pointermove', 140, 200)
  expect(f.stage.getAttribute('aria-label')).toBe('裁切预览：左侧裁去 15%，顶部裁去 30%，右侧裁去 0%，底部裁去 5%')
})

it('resizes eight displayed handles and keeps a 16px minimum preview side', () => {
  const f = fixture()
  expect(f.host.querySelectorAll('[data-pdf-crop-handle]')).toHaveLength(8)
  pointer(f.host.querySelector('[data-pdf-crop-handle="nw"]')!, 'pointerdown', 10, 20)
  pointer(window, 'pointermove', 410, 520)
  pointer(window, 'pointerup', 410, 520)
  expect(f.change).toHaveBeenLastCalledWith([96, 96.8, 0, 0])
  expect(f.controller.margins()).toEqual([96, 96.8, 0, 0])
})

it('moves the retained region with clamped edges and synchronizes numeric margins', () => {
  const f = fixture()
  f.controller.setMargins([10, 20, 30, 40])
  expect(f.change).not.toHaveBeenCalled()
  pointer(f.host.querySelector('[data-pdf-crop-region]')!, 'pointerdown', 100, 150)
  pointer(window, 'pointermove', 900, -500)
  pointer(window, 'pointerup', 900, -500)
  expect(f.controller.margins()).toEqual([40, 0, 0, 60])
})

it.each([
  ['nw', [20, 30, 30, 40]], ['n', [10, 30, 30, 40]],
  ['ne', [10, 30, 20, 40]], ['e', [10, 20, 20, 40]],
  ['se', [10, 20, 20, 30]], ['s', [10, 20, 30, 30]],
  ['sw', [20, 20, 30, 30]], ['w', [20, 20, 30, 40]],
] as const)('changes only the displayed edges addressed by the %s handle', (handle, expected) => {
  const f = fixture()
  f.controller.setMargins([10, 20, 30, 40])
  pointer(f.host.querySelector(`[data-pdf-crop-handle="${handle}"]`)!, 'pointerdown', 100, 150)
  pointer(window, 'pointermove', 140, 200)
  pointer(window, 'pointerup', 140, 200)
  expect(f.controller.margins()).toEqual(expected)
})

it.each(['pointercancel', 'blur', 'resize', 'disabled', 'dispose'])('cancels %s without letting a stale gesture update margins', reason => {
  const f = fixture()
  const handle = f.host.querySelector('[data-pdf-crop-handle="e"]')!
  pointer(handle, 'pointerdown', 410, 300)
  if (reason === 'disabled') f.disable()
  else if (reason === 'dispose') f.controller.dispose()
  else if (reason === 'pointercancel') pointer(window, reason, 410, 300)
  else window.dispatchEvent(new Event(reason))
  pointer(window, 'pointermove', 200, 300)
  pointer(window, 'pointerup', 200, 300)
  expect(f.change).not.toHaveBeenCalled()
})

it('ignores foreign pointers and invalid margin input, retaining the last valid rectangle', () => {
  const f = fixture()
  f.controller.setMargins([10, 20, 30, 40])
  expect(() => f.controller.setMargins([80, 0, 80, 0])).toThrow()
  pointer(f.host.querySelector('[data-pdf-crop-handle="e"]')!, 'pointerdown', 410, 300)
  pointer(window, 'pointermove', 200, 300, 2)
  pointer(window, 'pointerup', 200, 300, 2)
  expect(f.change).not.toHaveBeenCalled()
  expect(f.controller.margins()).toEqual([10, 20, 30, 40])
})

it('does not cancel an active pointer for another pointer and can expand a sub-16px numeric crop', () => {
  const f = fixture()
  f.controller.setMargins([99, 0, 0, 0])
  pointer(f.host.querySelector('[data-pdf-crop-handle="w"]')!, 'pointerdown', 406, 250)
  pointer(window, 'pointercancel', 406, 250, 2)
  pointer(window, 'pointermove', 402, 250)
  expect(f.controller.margins()).toEqual([98, 0, 0, 0])
})

it.each(['scroll', 'wheel'])('cancels a drag when dialog %s invalidates its screen coordinates', reason => {
  const f = fixture()
  pointer(f.host.querySelector('[data-pdf-crop-handle="e"]')!, 'pointerdown', 410, 300)
  if (reason === 'scroll') vi.mocked(f.stage.getBoundingClientRect).mockReturnValue({ ...f.stage.getBoundingClientRect(), top: 40, y: 40 })
  f.stage.dispatchEvent(new Event(reason, { bubbles: false }))
  pointer(window, 'pointermove', 200, 300)
  expect(f.change).not.toHaveBeenCalled()
})

it('continues a drag while a background sibling scrolls without moving the crop canvas', () => {
  const f = fixture(), background = document.createElement('div')
  document.body.append(background)
  pointer(f.host.querySelector('[data-pdf-crop-handle="nw"]')!, 'pointerdown', 10, 20)
  pointer(window, 'pointermove', 15, 30)
  background.dispatchEvent(new Event('scroll'))
  pointer(window, 'pointermove', 50, 120)
  expect(f.controller.margins()).toEqual([10, 20, 0, 0])
})

it.each(['consumed', 'composition', '229'])('preserves the active crop gesture when Escape belongs to %s input', reason => {
  const f = fixture(), input = document.createElement('input'); f.host.append(input); input.focus()
  if (reason === 'consumed') input.addEventListener('keydown', event => event.preventDefault())
  pointer(f.host.querySelector('[data-pdf-crop-handle="e"]')!, 'pointerdown', 410, 300)
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: reason === 'composition', keyCode: reason === '229' ? 229 : 27 }))
  pointer(window, 'pointermove', 310, 300)
  expect(f.controller.margins()).toEqual([0, 0, 25, 0])
})

it('stops the active crop gesture on an unconsumed Escape', () => {
  const f = fixture()
  pointer(f.host.querySelector('[data-pdf-crop-handle="e"]')!, 'pointerdown', 410, 300)
  f.host.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  pointer(window, 'pointermove', 310, 300)
  expect(f.controller.margins()).toEqual([0, 0, 0, 0])
})

it.each(['width', 'height'] as const)('cancels a scrolled drag when canvas %s changes', dimension => {
  const f = fixture()
  pointer(f.host.querySelector('[data-pdf-crop-handle="e"]')!, 'pointerdown', 410, 300)
  vi.mocked(f.stage.getBoundingClientRect).mockReturnValue({ ...f.stage.getBoundingClientRect(), [dimension]: 300 })
  f.host.dispatchEvent(new Event('scroll'))
  pointer(window, 'pointermove', 200, 300)
  expect(f.change).not.toHaveBeenCalled()
})
