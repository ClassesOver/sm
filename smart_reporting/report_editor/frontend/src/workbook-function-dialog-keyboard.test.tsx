import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterAll, afterEach, expect, it, vi } from 'vitest'
import { FunctionArgumentsDialog } from './workbook-function-arguments-dialog'
import { InsertFunctionDialog } from './workbook-function-catalog-dialog'
import type { FunctionTarget, ExternalPickTarget } from './workbook-function-runtime'

vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
afterAll(() => vi.unstubAllGlobals())
const roots: Root[] = []
afterEach(async () => { await act(async () => { roots.splice(0).forEach(root => root.unmount()) }); document.body.replaceChildren() })
const target: FunctionTarget = { workbookCore: {}, sheetCore: {}, unitId: 'book', sheetId: 'sheet', sheetName: 'Sheet', row: 0, col: 0, label: 'A1', formula: '', caret: 0, editorText: null }
const spec = { name: 'SUM', category: 'Math' as const, syntax: 'SUM(number1)', abstract: '求和', description: '求和说明', params: [{ name: 'number1', detail: '数值区域', require: true, repeat: false }] }
const protections = ['composition', 'legacy', 'handled'] as const
async function press(node: EventTarget, key: string, protection?: typeof protections[number]) {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
  if (protection === 'handled') event.preventDefault()
  await act(async () => { node.dispatchEvent(event) }); return event
}
async function setup(mode: 'args' | 'catalog' = 'args', external = false) {
  const trigger = document.body.appendChild(document.createElement('button')); trigger.focus()
  const container = document.body.appendChild(document.createElement('div')), root = createRoot(container); roots.push(root)
  const onOk = vi.fn(), onCancel = vi.fn()
  const links: ExternalPickTarget[] = external ? [{ index: 1, name: '预算.xlsx', source: '/fixture/budget.xlsx', open: false, wcId: null, sheetNames: ['数据表'] }] : []
  const host = { evaluate: vi.fn(async () => []), observeRangePick: vi.fn(() => () => {}), listExternalPickTargets: vi.fn(async () => links), pickExternalRange: vi.fn(() => () => {}) }
  await act(async () => root.render(mode === 'args'
    ? <FunctionArgumentsDialog spec={spec} target={target} initialArgs={['A1:A3']} host={host} error={null} onOk={onOk} onCancel={onCancel} />
    : <InsertFunctionDialog targetLabel="A1" catalog={[spec, { ...spec, name: 'SUMIF', syntax: 'SUMIF(range, criteria)' }, { ...spec, name: 'SUMIFS', syntax: 'SUMIFS(sum_range, criteria_range1, criteria1)' }]} recent={[]} initialCategory="All" onPick={onOk} onClose={onCancel} />))
  const input = container.querySelector<HTMLInputElement>('#fn-arg-0') ?? container.querySelector<HTMLInputElement>('input')!
  return { container, input, onOk, onCancel, trigger }
}
async function change(input: HTMLInputElement, value: string) {
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })) })
}

it.each(protections)('函数参数中的受保护Enter不确认整个函数：%s', async protection => {
  const f = await setup(); f.input.focus()
  await press(f.input, 'Enter', protection)
  expect(f.onOk).not.toHaveBeenCalled(); expect(f.input.value).toBe('A1:A3'); expect(document.activeElement).toBe(f.input)
  await press(f.input, 'Enter'); expect(f.onOk).toHaveBeenCalledExactlyOnceWith(['A1:A3'])
})

it.each(protections)('折叠取区域时受保护Enter不提前展开：%s', async protection => {
  const f = await setup(), toggle = f.container.querySelector<HTMLButtonElement>('.fn-args-pick')!
  await act(async () => toggle.click()); expect(toggle.getAttribute('aria-expanded')).toBe('false')
  await press(f.input, 'Enter', protection)
  expect(toggle.getAttribute('aria-expanded')).toBe('false'); expect(f.onOk).not.toHaveBeenCalled()
  await press(f.input, 'Enter'); expect(toggle.getAttribute('aria-expanded')).toBe('true'); expect(f.onOk).not.toHaveBeenCalled()
})

it.each(protections)('外部区域受保护Enter不替换参数或确认函数：%s', async protection => {
  const f = await setup('args', true), range = f.container.querySelector<HTMLInputElement>('[placeholder="A1:B2"]')!
  await change(range, 'B2:B4'); range.focus()
  await press(range, 'Enter', protection)
  expect(f.input.value).toBe('A1:A3'); expect(range.value).toBe('B2:B4'); expect(document.activeElement).toBe(range); expect(f.onOk).not.toHaveBeenCalled()
})

it('外部区域的普通Enter只插入区域，下一次参数Enter才提交最新参数', async () => {
  const f = await setup('args', true), range = f.container.querySelector<HTMLInputElement>('[placeholder="A1:B2"]')!
  await change(range, 'B2:B4'); range.focus(); await press(range, 'Enter')
  expect(f.input.value).toBe("'[1]数据表'!B2:B4"); expect(f.onOk).not.toHaveBeenCalled(); expect(document.activeElement).toBe(f.input)
  await press(f.input, 'Enter'); expect(f.onOk).toHaveBeenCalledExactlyOnceWith(["'[1]数据表'!B2:B4"])
})

it('外部区域输入有包含来源工作簿的可访问名称', async () => {
  const f = await setup('args', true)
  expect(f.container.querySelector('[placeholder="A1:B2"]')?.getAttribute('aria-label')).toBe('外部区域：预算.xlsx')
})

it.each(['args', 'catalog'] as const)('函数窗口%s内外的受保护Escape不取消，普通Escape仍可取消', async mode => {
  const f = await setup(mode)
  for (const outside of [false, true]) for (const protection of protections) {
    if (outside) { f.input.blur(); document.body.focus() } else f.input.focus()
    await press(outside ? window : f.input, 'Escape', protection)
    expect(f.onCancel).not.toHaveBeenCalled()
  }
  f.input.focus(); await press(f.input, 'Escape'); expect(f.onCancel).toHaveBeenCalledOnce(); expect(f.onOk).not.toHaveBeenCalled()
})

it.each(protections)('函数列表受保护的方向和首尾按键不改变选择：%s', async protection => {
  const f = await setup('catalog')
  const options = [...f.container.querySelectorAll<HTMLButtonElement>('[role="option"]')]
  await act(async () => options[1]!.focus())
  for (const key of ['ArrowDown', 'ArrowUp', 'Home', 'End']) {
    const event = await press(options[1]!, key, protection)
    expect(document.activeElement).toBe(options[1])
    expect(options[1]!.getAttribute('aria-selected')).toBe('true')
    expect(event.defaultPrevented).toBe(protection === 'handled')
  }
  expect(f.onOk).not.toHaveBeenCalled()
  expect(f.onCancel).not.toHaveBeenCalled()
})

it('函数列表普通方向和首尾按键保持选项与焦点同步', async () => {
  const f = await setup('catalog')
  const options = [...f.container.querySelectorAll<HTMLButtonElement>('[role="option"]')]
  await act(async () => options[0]!.focus())
  for (const [key, index] of [['ArrowDown', 1], ['End', 2], ['Home', 0], ['ArrowUp', 0]] as const) {
    await press(document.activeElement!, key)
    expect(document.activeElement).toBe(options[index])
    expect(options[index]!.getAttribute('aria-selected')).toBe('true')
    expect(options.filter(option => option.tabIndex === 0)).toEqual([options[index]])
  }
})
