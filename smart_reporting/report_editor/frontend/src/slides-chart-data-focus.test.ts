import { afterEach, expect, it, vi } from 'vitest'
import { createNativeChartEditDialog } from './slides-native-chart-edit'

afterEach(() => document.body.replaceChildren())
const initial = { kind: 'bar' as const, categories: ['甲', '乙'], series: [{ name: '收入', values: [1, 2] }, { name: '成本', values: [3, 4] }] }
function open() {
  const confirm = vi.fn(), close = vi.fn()
  const editor = createNativeChartEditDialog(document.body, { mode: 'data', initial, onConfirm: confirm, onClose: close })
  const dialog = document.querySelector<HTMLDialogElement>('dialog')!
  return { editor, dialog, confirm, close }
}

it.each(['category', 'series'])('添加%s后焦点到新名称字段，保留当前编辑值且取消不写入', kind => {
  const { dialog, confirm } = open()
  dialog.querySelector<HTMLInputElement>('[data-chart-value="0:0"]')!.value = '27.5'
  const button = dialog.querySelector<HTMLButtonElement>(`[data-chart-add-${kind}]`)!
  button.focus(); button.click()
  expect(document.activeElement).toBe(dialog.querySelector(`[data-chart-${kind}="2"]`))
  expect(dialog.querySelector<HTMLInputElement>('[data-chart-value="0:0"]')!.value).toBe('27.5')
  expect(confirm).not.toHaveBeenCalled()
  ;[...dialog.querySelectorAll('button')].find(button => button.textContent === '取消')!.click()
  expect(confirm).not.toHaveBeenCalled(); expect(initial.series[0]!.values[0]).toBe(1)
})

for (const kind of ['category', 'series']) for (const index of [0, 1]) it(`删除${kind} ${index}后聚焦存活的相邻名称，数据跟随正确索引`, () => {
  const { dialog, confirm } = open()
  const name = dialog.querySelector<HTMLInputElement>(`[data-chart-${kind}="${index}"]`)!
  const button = name.parentElement!.querySelector<HTMLButtonElement>('button')!
  button.focus(); button.click()
  const survivor = dialog.querySelector<HTMLInputElement>(`[data-chart-${kind}="0"]`)!
  expect(document.activeElement).toBe(survivor)
  expect(survivor.value).toBe(kind === 'category' ? (index ? '甲' : '乙') : (index ? '收入' : '成本'))
  expect(survivor.parentElement!.querySelector('button')!.disabled).toBe(true)
  dialog.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  const expected = kind === 'category'
    ? { categories: [index ? '甲' : '乙'], series: initial.series.map(series => ({ name: series.name, values: [series.values[index ? 0 : 1]] })) }
    : { categories: initial.categories, series: [initial.series[index ? 0 : 1]] }
  expect(confirm).toHaveBeenCalledWith(expected)
})
