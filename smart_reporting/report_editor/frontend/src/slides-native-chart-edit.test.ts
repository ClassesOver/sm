import { afterEach, expect, it, vi } from 'vitest'
import { createNativeChartEditDialog } from './slides-native-chart-edit'

afterEach(() => { document.body.replaceChildren() })
const initial = { kind: 'bar' as const, categories: ['甲', '乙'], series: [{ name: '收入', values: [1, 2] }] }
it('单点配色从覆盖回填，只提交变化点并允许恢复系列颜色',()=>{
 const confirm=vi.fn()
 createNativeChartEditDialog(document.body,{mode:'points',initial:{...initial,pointColors:{0:{0:'#FF0000'}},seriesColors:['#4472C4']},onConfirm:confirm,onClose:vi.fn()})
 const first=document.querySelector<HTMLInputElement>('[data-chart-point="0:0"]')
 expect(first).not.toBeNull()
 expect(first!.value).toBe('#ff0000')
 document.querySelector<HTMLButtonElement>('[data-chart-point-reset="0:0"]')!.click()
 const second=document.querySelector<HTMLInputElement>('[data-chart-point="0:1"]')!
 second.value='#123abc';second.dispatchEvent(new Event('input'))
 document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 expect(confirm).toHaveBeenCalledWith({pointColors:{0:{0:null,1:'#123ABC'}}})
})

it('单点配色回填循环方案中的系列颜色',()=>{
 createNativeChartEditDialog(document.body,{mode:'points',initial:{...initial,series:[{name:'甲',values:[1,2]},{name:'乙',values:[3,4]},{name:'丙',values:[5,6]}],seriesColors:['#123456','#ABCDEF']},onConfirm:vi.fn(),onClose:vi.fn()})
 expect(document.querySelector<HTMLInputElement>('[data-chart-point="2:0"]')!.value).toBe('#123456')
})

it('单点配色无变化或取消不提交，主机拒绝后保留弹窗',()=>{
 const confirm=vi.fn()
 createNativeChartEditDialog(document.body,{mode:'points',initial,onConfirm:confirm,onClose:vi.fn()})
 expect(document.querySelectorAll('[data-chart-point]')).toHaveLength(2)
 document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 expect(confirm).not.toHaveBeenCalled()
 createNativeChartEditDialog(document.body,{mode:'points',initial,onConfirm:confirm,onClose:vi.fn()})
 const cancelled=document.querySelector<HTMLInputElement>('[data-chart-point="0:0"]')!
 cancelled.value='#123456';cancelled.dispatchEvent(new Event('input'))
 const cancel=[...document.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='取消')!
 cancel.click();expect(confirm).not.toHaveBeenCalled()
 createNativeChartEditDialog(document.body,{mode:'points',initial,onConfirm:()=>{throw Error('草稿变化')},onClose:vi.fn()})
 const input=document.querySelector<HTMLInputElement>('[data-chart-point="0:0"]')!
 input.value='#123456';input.dispatchEvent(new Event('input'))
 document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 expect(document.querySelector('[role="alert"]')!.textContent).toContain('草稿变化')
})

it('图表设计提供固定配色和十种命名预设，只提交选中预设的变化字段',()=>{
 const confirm=vi.fn()
 createNativeChartEditDialog(document.body,{mode:'design',initial:{...initial,legendPos:'r',dataLabels:true,gridlines:false,gapWidthPct:150},onConfirm:confirm,onClose:vi.fn()})
 const palette=document.querySelector<HTMLSelectElement>('[data-chart-palette]')
 expect(palette).not.toBeNull()
 expect(palette!.options.length).toBe(14)
 const preset=document.querySelector<HTMLSelectElement>('[data-chart-preset]')!
 expect([...preset.options].slice(1).map(o=>o.value)).toEqual(['classic','grid','labeled','detail','minimal','minimal-labeled','bold','slim','legend-top','legend-right'])
 palette!.value='warm';palette!.dispatchEvent(new Event('change'))
 expect(document.querySelectorAll('[data-chart-swatch]').length).toBe(5)
 preset.value='bold'
 document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 expect(confirm).toHaveBeenCalledWith({colorScheme:'warm',legendPos:'b',dataLabels:false,gridlines:true,gapWidthPct:50})
})

it('未选择配色或预设不改变草稿，设计确认失败保留弹窗',()=>{
 const confirm=vi.fn()
 createNativeChartEditDialog(document.body,{mode:'design',initial,onConfirm:confirm,onClose:vi.fn()})
 expect(document.querySelector('[data-chart-palette]')).not.toBeNull()
 document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 expect(confirm).not.toHaveBeenCalled()
 createNativeChartEditDialog(document.body,{mode:'design',initial,onConfirm:()=>{throw Error('草稿已变化')},onClose:vi.fn()})
 document.querySelector<HTMLSelectElement>('[data-chart-palette]')!.value='default'
 document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
 expect(document.querySelector('[role="alert"]')!.textContent).toContain('变化')
})

it('图表元素编辑从来源回填，只提交变化字段并保留显式清空和false', () => {
  const confirm = vi.fn()
  createNativeChartEditDialog(document.body, { mode: 'style', initial: { ...initial, title: '来源标题', catAxisTitle: '月份', valAxisTitle: '万元', legendPos: 'r', dataLabels: true, gridlines: false }, onConfirm: confirm, onClose: vi.fn() })
  const title = document.querySelector<HTMLInputElement>('[data-chart-style="title"]')
  expect(title).not.toBeNull()
  expect(title!.value).toBe('来源标题')
  title!.value = '  新标题😀 <&>  '
  document.querySelector<HTMLInputElement>('[data-chart-style="catAxisTitle"]')!.value = ''
  document.querySelector<HTMLSelectElement>('[data-chart-style="legendPos"]')!.value = 'none'
  document.querySelector<HTMLInputElement>('[data-chart-style="dataLabels"]')!.checked = false
  document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(confirm).toHaveBeenCalledWith({ title: '新标题😀 <&>', catAxisTitle: '', legendPos: 'none', dataLabels: false })
})

it('图表元素取消或未改变不产生格式候选，非法标题保留弹窗', () => {
  const confirm = vi.fn(), close = vi.fn()
  createNativeChartEditDialog(document.body, { mode: 'style', initial, onConfirm: confirm, onClose: close })
  document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(confirm).not.toHaveBeenCalled()
  expect(close).toHaveBeenCalledOnce()
  createNativeChartEditDialog(document.body, { mode: 'style', initial, onConfirm: confirm, onClose: close })
  const title = document.querySelector<HTMLInputElement>('[data-chart-style="title"]')!
  title.value = 'x'.repeat(1001)
  document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(confirm).not.toHaveBeenCalled()
  expect(document.querySelector('[role="alert"]')!.textContent).toContain('1000')
})

it.each(['pie', 'pie3D', 'doughnut'] as const)('无轴图表 %s 禁用轴标题和网格线且不提交禁用字段', kind => {
  const confirm = vi.fn()
  createNativeChartEditDialog(document.body, { mode: 'style', initial: { ...initial, kind }, onConfirm: confirm, onClose: vi.fn() })
  for (const key of ['catAxisTitle', 'valAxisTitle', 'gridlines']) {
    const control = document.querySelector<HTMLInputElement>(`[data-chart-style="${key}"]`)!
    expect(control.disabled).toBe(true)
    control.value = '忽略的轴'; control.checked = true
  }
  document.querySelector<HTMLInputElement>('[data-chart-style="title"]')!.value = '饼图标题'
  document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(confirm).toHaveBeenCalledWith({ title: '饼图标题' })
})

it('edits a category/series grid and preserves the pinned invalid numeric input to zero rule', () => {
  const confirm = vi.fn(), close = vi.fn()
  const editor = createNativeChartEditDialog(document.body, { mode: 'data', initial, onConfirm: confirm, onClose: close })
  const input = document.querySelector<HTMLInputElement>('[data-chart-value="0:0"]')!
  input.value = '错误'; input.dispatchEvent(new Event('input'))
  document.querySelector<HTMLInputElement>('[data-chart-series="0"]')!.value = ' '
  document.querySelector<HTMLButtonElement>('[data-chart-add-category]')!.click()
  document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(confirm).toHaveBeenCalledWith({ categories: ['甲', '乙', '类别 3'], series: [{ name: '', values: [0, 2, 0] }] })
  expect(close).toHaveBeenCalledOnce()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  expect(initial.series[0]!.values).toEqual([1, 2])
  editor.dispose()
})

it('offers the 13 pinned chart types and applies a double click without data replacement', () => {
  const confirm = vi.fn()
  createNativeChartEditDialog(document.body, { mode: 'type', initial, onConfirm: confirm, onClose: vi.fn() })
  expect(document.querySelectorAll('[data-chart-kind]')).toHaveLength(13)
  document.querySelector<HTMLButtonElement>('[data-chart-kind="barH"]')!.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
  expect(confirm).toHaveBeenCalledWith({ kind: 'barH' })
})

it('cancel, escape and disposal never commit; disposal prevents stale confirmation', () => {
  const confirm = vi.fn(), close = vi.fn()
  const editor = createNativeChartEditDialog(document.body, { mode: 'type', initial, onConfirm: confirm, onClose: close })
  const stale = document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!
  editor.dispose(); stale.click()
  expect(confirm).not.toHaveBeenCalled(); expect(close).toHaveBeenCalledOnce()
  createNativeChartEditDialog(document.body, { mode: 'data', initial, onConfirm: confirm, onClose: close })
  document.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(close).toHaveBeenCalledTimes(2); expect(confirm).not.toHaveBeenCalled()
})

it('keeps the dialog open and displays a host confirmation rejection without a page error', () => {
  const close = vi.fn()
  createNativeChartEditDialog(document.body, { mode: 'type', initial, onConfirm: () => { throw new Error('所选图表已改变，请重新选择。') }, onClose: close })
  document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(document.querySelector('[role="alert"]')!.textContent).toBe('所选图表已改变，请重新选择。')
  expect(document.querySelector('[role="dialog"]')).not.toBeNull()
  expect(close).not.toHaveBeenCalled()
})

it('rejects labels outside the 100-character publication contract before calling the host', () => {
  const confirm = vi.fn()
  createNativeChartEditDialog(document.body, { mode: 'data', initial, onConfirm: confirm, onClose: vi.fn() })
  document.querySelector<HTMLInputElement>('[data-chart-category="0"]')!.value = '字'.repeat(101)
  document.querySelector<HTMLButtonElement>('[data-chart-confirm]')!.click()
  expect(confirm).not.toHaveBeenCalled()
  expect(document.querySelector('[role="alert"]')!.textContent).toContain('100')
})
