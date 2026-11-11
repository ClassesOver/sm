import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesGeometryPane } from './slides-geometry-pane'

afterEach(() => { document.body.innerHTML = '' })
const initial = { x: 96.123456, y: 72, width: 192, height: 96 }
function setup() {
  let state = { target: '0:shape', geometry: initial, slideSize: { width: 960, height: 540 } }
  const confirm = vi.fn((geometry: typeof initial) => { state = { ...state, geometry }; pane.update(state) })
  const pane = createSlidesGeometryPane(confirm)
  document.body.append(pane.element); pane.update(state)
  const field = (key: string) => pane.element.querySelector<HTMLInputElement>(`[data-geometry="${key}"]`)!
  const change = (key: string, value: string) => { field(key).value = value; field(key).dispatchEvent(new Event('change')) }
  return { pane, confirm, field, change, state: () => state }
}

it('百分比使用选中时基准而非连续乘法，厘米和外部历史回填不重设基准', () => {
  const { pane, confirm, field, change, state } = setup()
  expect(field('scaleWidth')?.value).toBe('100')
  change('scaleWidth', '150%'); expect(state().geometry).toEqual({ ...initial, width: 288 })
  change('scaleWidth', '200'); expect(state().geometry).toEqual({ ...initial, width: 384 })
  expect(field('width').value).toBe('10.16'); expect(field('scaleHeight').value).toBe('100')
  change('height', '5.08'); expect(field('scaleHeight').value).toBe('200')
  pane.update({ ...state(), geometry: initial }); expect(field('scaleWidth').value).toBe('100')
  pane.update(state()); expect(field('scaleWidth').value).toBe('200')
  const calls = confirm.mock.calls.length
  field('scaleWidth').dispatchEvent(new Event('blur')); expect(confirm.mock.calls).toHaveLength(calls)
  pane.update({ ...state(), target: '0:other' }); expect(field('scaleWidth').value).toBe('100')
  pane.update(state()); expect(field('scaleWidth').value).toBe('100')
  pane.dispose()
})

it('百分比锁比例双向联动，1%步进基于显示百分比且保持输入节点', () => {
  const { pane, field, change, state } = setup()
  expect(field('scaleWidth')).not.toBeNull()
  pane.element.querySelector<HTMLInputElement>('[data-geometry-ratio]')!.click()
  change('scaleWidth', '150'); expect(state().geometry).toEqual({ ...initial, width: 288, height: 144 })
  const input = field('scaleHeight'), step = pane.element.querySelector<HTMLButtonElement>('[data-geometry-step="scaleHeight:1"]')!
  change('scaleHeight', '125'); expect(state().geometry).toEqual({ ...initial, width: 240, height: 120 })
  expect(field('scaleHeight')).toBe(input); expect(pane.element.contains(step)).toBe(true)
  step.click(); expect(state().geometry.width).toBeCloseTo(241.92); expect(state().geometry.height).toBeCloseTo(120.96)
  expect(field('scaleWidth').value).toBe('126'); expect(field('scaleHeight').value).toBe('126')
  expect(state().geometry.x).toBe(initial.x); expect(state().geometry.y).toBe(72)
  pane.dispose()
})

it('非法百分比不提交，恢复原显示值清错且保存前flush可重试', () => {
  const { pane, confirm, field, change, state } = setup()
  expect(field('scaleWidth')).not.toBeNull()
  for (const value of ['', '0', '-1', 'Infinity', '10oops', '1e2', '999999']) {
    change('scaleWidth', value); expect(pane.flush()).toBe(false); expect(confirm).not.toHaveBeenCalled()
  }
  change('scaleWidth', '100'); expect(pane.flush()).toBe(true); expect(confirm).not.toHaveBeenCalled()
  expect(pane.element.querySelector('[role="status"]')!.textContent).toBe('')
  field('scaleWidth').value = '175.5'
  confirm.mockImplementationOnce(() => { throw new Error('暂时失败') })
  expect(pane.flush()).toBe(false); expect(field('scaleWidth').value).toBe('175.5')
  expect(pane.flush()).toBe(true); expect(state().geometry.width).toBe(336.96)
  expect(field('scaleWidth').value).toBe('176')
  const calls = confirm.mock.calls.length
  expect(pane.flush()).toBe(true); expect(confirm.mock.calls).toHaveLength(calls)
  change('scaleWidth', '176%'); expect(confirm.mock.calls).toHaveLength(calls)
  expect(state().geometry.width).toBe(336.96)
  pane.dispose()
})

it('切选择或取消选择重置百分比基准，锁定只读和销毁令旧控件失效', () => {
  const { pane, confirm, field, change, state } = setup()
  expect(field('scaleWidth')).not.toBeNull()
  change('scaleWidth', '150'); confirm.mockClear()
  const old = field('scaleWidth'); pane.update(null); old.value = '200'; old.dispatchEvent(new Event('change'))
  pane.update(state()); expect(field('scaleWidth').value).toBe('100')
  const beforeLock = field('scaleHeight'); pane.setLocked(true); beforeLock.value = '200'; beforeLock.dispatchEvent(new Event('change'))
  expect(field('scaleWidth').disabled).toBe(true)
  pane.setLocked(false); expect(field('scaleWidth').value).toBe('100')
  pane.update({ ...state(), reason: '来源只读' }); expect(field('scaleWidth').disabled).toBe(true)
  pane.update(state()); const last = field('scaleWidth'); pane.dispose(); last.value = '200'; last.dispatchEvent(new Event('change'))
  expect(confirm).not.toHaveBeenCalled()
})
