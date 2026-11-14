import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesGeometryPane } from './slides-geometry-pane'

afterEach(() => document.body.replaceChildren())

const source = { target: '0:shape', geometry: { x: 96, y: 72, width: 192, height: 96 }, slideSize: { width: 960, height: 540 } }
function setup() {
  const confirm = vi.fn(), pane = createSlidesGeometryPane(confirm)
  document.body.append(pane.element); pane.update(structuredClone(source))
  const width = () => pane.element.querySelector<HTMLInputElement>('[data-geometry="width"]')!
  return { pane, confirm, width }
}

it('相同来源回填保留正在输入的几何草稿、节点与焦点，随后只提交一次', () => {
  const { pane, confirm, width } = setup(), input = width()
  input.focus(); input.value = '7.'; input.dispatchEvent(new Event('input', { bubbles: true }))
  pane.update(structuredClone(source))
  expect(width()).toBe(input); expect(width().value).toBe('7.'); expect(document.activeElement).toBe(input)
  expect(confirm).not.toHaveBeenCalled()
  input.value = '7.62'; expect(pane.flush()).toBe(true)
  expect(confirm).toHaveBeenCalledOnce(); expect(confirm.mock.lastCall![0].width).toBeCloseTo(288)
  pane.dispose()
})

it('其他属性回填不能悄悄清除几何错误及关联说明', () => {
  const { pane, confirm, width } = setup(), input = width()
  input.focus(); input.value = 'invalid'; expect(pane.flush()).toBe(false)
  const status = pane.element.querySelector<HTMLElement>('[role="status"]')!, text = status.textContent
  pane.update(structuredClone(source))
  expect(width()).toBe(input); expect(input.value).toBe('invalid'); expect(input.getAttribute('aria-invalid')).toBe('true')
  expect(status.isConnected).toBe(true); expect(status.textContent).toBe(text); expect(document.activeElement).toBe(input)
  expect(confirm).not.toHaveBeenCalled(); pane.dispose()
})

it.each(['geometry', 'slideSize', 'reason', 'picture', 'target', 'locked'] as const)('真正的 %s 状态变化仍更新控件并使旧节点失效', field => {
  const { pane, confirm, width } = setup(), old = width()
  old.value = '7.62'
  const next = { ...structuredClone(source), ...(field === 'geometry' ? { geometry: { ...source.geometry, width: 300 } } : {}),
    ...(field === 'slideSize' ? { slideSize: { width: 1000, height: 540 } } : {}),
    ...(field === 'reason' ? { reason: '此对象只读' } : {}), ...(field === 'picture' ? { picture: true } : {}),
    ...(field === 'target' ? { target: '0:other' } : {}) }
  pane.update(next, field === 'locked')
  expect(width()).not.toBe(old); expect(old.isConnected).toBe(false)
  old.dispatchEvent(new Event('change')); expect(confirm).not.toHaveBeenCalled()
  expect(width().value).toBe(field === 'geometry' ? '7.94' : '5.08')
  expect(width().disabled).toBe(field === 'reason' || field === 'locked'); pane.dispose()
})
