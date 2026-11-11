import { afterEach, expect, it, vi } from 'vitest'
import { createSlidesGeometryPane } from './slides-geometry-pane'

afterEach(() => { document.body.innerHTML = '' })
const original = { x: 96.123456, y: 72, width: 192, height: 96 }
function setup() {
  const confirm = vi.fn(), pane = createSlidesGeometryPane(confirm)
  document.body.append(pane.element)
  const state = { target: '0:shape', geometry: original, slideSize: { width: 960, height: 540 } }
  pane.update(state)
  const input = (name: string) => pane.element.querySelector<HTMLInputElement>(`[data-geometry="${name}"]`)!
  const change = (name: string, value: string) => { const field = input(name); field.value = value; field.dispatchEvent(new Event('input')); field.dispatchEvent(new Event('change')) }
  return { pane, confirm, state, input, change }
}
it('厘米显示无变化不写入，改一维保留其他来源精度，步进使用真实值', () => {
  const { pane, confirm, input, change } = setup()
  expect(input('width').value).toBe('5.08')
  input('x').dispatchEvent(new Event('change')); expect(confirm).not.toHaveBeenCalled()
  change('height', '5.08')
  expect(confirm).toHaveBeenLastCalledWith({ ...original, height: 192 }, '0:shape')
  pane.element.querySelector<HTMLButtonElement>('[data-geometry-step="x:1"]')!.click()
  expect(confirm.mock.lastCall![0].x).toBeCloseTo(original.x + 96 / 2.54 * 0.1)
  pane.dispose()
})
it('锁定纵横比分别修改宽高，中心参考独立转换为来源左上角', () => {
  const { pane, confirm, input, change } = setup()
  pane.element.querySelector<HTMLInputElement>('[data-geometry-ratio]')!.click()
  change('width', '10.16'); expect(confirm.mock.lastCall![0]).toEqual({ ...original, width: 384, height: 192 })
  change('height', '2.54'); expect(confirm.mock.lastCall![0]).toEqual(original)
  const reference = pane.element.querySelector<HTMLSelectElement>('[data-geometry-reference="x"]')!
  reference.value = 'center'; reference.dispatchEvent(new Event('change'))
  expect(Number(input('x').value)).toBeCloseTo((original.x + 96 - 480) / (96 / 2.54), 2)
  expect(input('y').value).toBe('1.91')
  change('x', '0'); expect(confirm.mock.lastCall![0]).toEqual({ ...original, x: 384 })
  pane.dispose()
})
it('空值、越界和不完整数字不写入，保存前flush提交未失焦字段并保留失败重试', () => {
  const { pane, confirm, input, change } = setup()
  for (const value of ['', '-1', '0', '999999', '2oops']) change('width', value)
  change('x', '-1'); expect(confirm).not.toHaveBeenCalled(); expect(pane.flush()).toBe(false)
  change('x', '2.54'); confirm.mockClear()
  const field = input('width'); field.value = '7.62'; field.dispatchEvent(new Event('input'))
  confirm.mockImplementationOnce(() => { throw new Error('暂时失败') })
  expect(pane.flush()).toBe(false); expect(pane.element.textContent).toContain('暂时失败')
  expect(pane.flush()).toBe(true); expect(confirm.mock.lastCall![0].width).toBeCloseTo(288)
  pane.dispose()
})
it('切目标、锁定和销毁后旧控件失效，只读来源给出原因', () => {
  const { pane, confirm, state, input } = setup()
  const old = input('width'); old.value = '10.16'; old.dispatchEvent(new Event('input'))
  pane.update({ ...state, target: '0:other' }); old.dispatchEvent(new Event('change')); expect(confirm).not.toHaveBeenCalled()
  const beforeLock = input('height'); pane.setLocked(true); beforeLock.value = '10.16'; beforeLock.dispatchEvent(new Event('change')); expect(confirm).not.toHaveBeenCalled()
  pane.setLocked(false); expect(input('height').disabled).toBe(false)
  pane.update({ ...state, reason: '连接线暂不支持' }); expect(input('width').disabled).toBe(true); expect(pane.element.textContent).toContain('连接线暂不支持')
  pane.update(state); const beforeDispose = input('x'); pane.dispose(); beforeDispose.value = '2.54'; beforeDispose.dispatchEvent(new Event('change')); expect(confirm).not.toHaveBeenCalled()
})
it('宿主提交回填保留同一输入和步进节点，防止失焦提交吞掉后续点击', () => {
  let state = { target: 'shape', geometry: original, slideSize: { width: 960, height: 540 } }
  const pane = createSlidesGeometryPane(geometry => { state = { ...state, geometry }; pane.update(state) })
  pane.update(state); document.body.append(pane.element)
  const input = pane.element.querySelector<HTMLInputElement>('[data-geometry="width"]')!
  const step = pane.element.querySelector<HTMLButtonElement>('[data-geometry-step="width:1"]')!
  input.value = '7.62'; input.dispatchEvent(new Event('change'))
  expect(pane.element.querySelector('[data-geometry="width"]')).toBe(input)
  expect(pane.element.contains(step)).toBe(true)
  step.click(); expect(state.geometry.width).toBeCloseTo(288 + 96 / 2.54 * 0.1)
  const ref = pane.element.querySelector<HTMLSelectElement>('[data-geometry-reference="y"]')!
  ref.value = 'center'; ref.dispatchEvent(new Event('change'))
  const y = pane.element.querySelector<HTMLInputElement>('[data-geometry="y"]')!;y.value = '0'; y.dispatchEvent(new Event('change'))
  expect(state.geometry.y).toBe(222)
  pane.dispose()
})
it('非法输入改回原显示值后清除错误，且不新增几何写入', () => {
  const { pane, confirm, input, change } = setup()
  change('width', '')
  expect(input('width').getAttribute('aria-invalid')).toBe('true')
  change('width', '5.08')
  expect(pane.element.querySelector('[role="status"]')!.textContent).toBe('')
  expect(input('width').hasAttribute('aria-invalid')).toBe(false)
  expect(pane.flush()).toBe(true); expect(confirm).not.toHaveBeenCalled()
  pane.dispose()
})
