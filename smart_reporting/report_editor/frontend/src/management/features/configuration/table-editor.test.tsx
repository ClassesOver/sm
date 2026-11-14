import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TablePreferenceFields } from './table-editor'

let root: Root
const update = vi.fn()
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })
const initial = { word: { tables: { repeatHeader: true, splitRows: false, borders: 'light', striped: true, captionNumbering: true } },
  xlsx: { borders: 'all', striped: false, freezeHeader: true, autoFilter: false,
    numbers: { decimalPlaces: 2, thousandsSeparator: true, negativeStyle: 'minus', percentPlaces: 2, dateFormat: 'iso' } },
  md: { sectionHeadingLevel: 2, listMarker: '*', codeFence: 'tildes', toc: false, tableStyle: 'pipe', imageCaptions: true, references: true } }
async function mount(format: string, disabled = false) {
  await act(async () => root.render(<TablePreferenceFields document={initial} format={format} onChange={update} disabled={disabled} />))
}
it('Word 表格编辑只提交选中字段，不暴露图表渲染参数', async () => {
  await mount('word')
  expect(document.querySelectorAll('[role="switch"]')).toHaveLength(5)
  const toggle = document.querySelector<HTMLButtonElement>('[aria-label="重复表头"]')!
  expect(toggle.getAttribute('aria-checked')).toBe('true')
  await act(async () => toggle.click())
  expect(update).toHaveBeenLastCalledWith(['word', 'tables', 'repeatHeader'], false)
  expect(document.body.textContent).toContain('允许跨页断行')
  expect(document.body.textContent).toContain('表格标题编号')
  expect(document.body.textContent).not.toMatch(/图像分辨率|首行缩进/)
})
it('XLSX 显示筛选冻结，不错误复用 Word 分页字段', async () => {
  await mount('xlsx')
  expect(document.body.textContent).toContain('冻结表头')
  expect(document.body.textContent).toContain('自动筛选')
  expect(document.body.textContent).not.toContain('允许跨页断行')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="自动筛选"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['xlsx', 'autoFilter'], true)
})
it('图文同页只更新当前分页格式，保存期间禁止修改', async () => {
  const value = { ...initial, pdf: { charts: { keepWithCaption: false } }, word: { charts: { keepWithCaption: true } } }
  await act(async () => root.render(<TablePreferenceFields document={value} format="pdf" onChange={update} />))
  let toggle = document.querySelector<HTMLButtonElement>('[aria-label="图片与说明同页"]')!
  expect(toggle).not.toBeNull()
  expect(toggle.getAttribute('aria-checked')).toBe('false')
  await act(async () => toggle.click())
  expect(update).toHaveBeenLastCalledWith(['pdf', 'charts', 'keepWithCaption'], true)
  expect(value.word.charts.keepWithCaption).toBe(true)
  update.mockReset()
  await act(async () => root.render(<TablePreferenceFields document={value} format="word" onChange={update} disabled />))
  toggle = document.querySelector<HTMLButtonElement>('[aria-label="图片与说明同页"]')!
  expect(toggle.getAttribute('aria-checked')).toBe('true')
  expect(toggle.disabled).toBe(true)
  await act(async () => toggle.click())
  expect(update).not.toHaveBeenCalled()
})
it('保存过程中禁止修改输入，避免回读覆盖新的修改', async () => {
  await mount('word', true)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="重复表头"]')!.click())
  expect(update).not.toHaveBeenCalled()
})
it('MD 显示已接通的列表代码与目录，不显示 Office 表格开关', async () => {
  await mount('md')
  expect(document.querySelectorAll('[role="combobox"]')).toHaveLength(4)
  expect(document.querySelector('[aria-label="章节起始级别"]')).not.toBeNull()
  expect(document.body.textContent).toContain('报告总标题保持一级')
  expect(document.querySelector('[aria-label="表格写法"]')).not.toBeNull()
  expect(document.body.textContent).toContain('列表符号')
  expect(document.body.textContent).toContain('代码块围栏')
  expect(document.body.textContent).not.toContain('冻结表头')
  expect(document.querySelectorAll('[role="switch"]')).toHaveLength(3)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="图片说明"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['md', 'imageCaptions'], false)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="生成目录"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['md', 'toc'], true)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="引用编号"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['md', 'references'], false)
  expect(document.body.textContent).toContain('隐藏编号仍保留来源绑定')
})
it('XLSX 数字格式只维护显示，小数位有范围，千分位独立更新', async () => {
  await mount('xlsx')
  const places = document.querySelector<HTMLInputElement>('[aria-label="小数位"]')!
  expect(places).not.toBeNull()
  expect(places.value).toBe('2')
  expect(places.getAttribute('aria-valuemin')).toBe('0')
  expect(places.getAttribute('aria-valuemax')).toBe('15')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="千分位"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['xlsx', 'numbers', 'thousandsSeparator'], false)
  expect(document.querySelector('[aria-label="负数样式"]')).not.toBeNull()
  expect(document.querySelector('[aria-label="百分比小数位"]')).not.toBeNull()
  expect(document.querySelector('[aria-label="数据日期格式"]')).not.toBeNull()
})
