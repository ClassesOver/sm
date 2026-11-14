import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { WorkbookPrintFields } from './workbook-print'

let root: Root
const update = vi.fn()
const print = { page: { paper: 'A4' }, headerFooter: { enabled: true }, fitToWidth: 1, fitToHeight: null, scalePercent: null, repeatTitleRows: 1 }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })
it('适配页宽仅显示方式与重复标题，不重复纸张页眉或百分比参数', async () => {
  await act(async () => root.render(<WorkbookPrintFields document={{ xlsx: { print } }} onChange={update} />))
  expect(document.querySelector('[aria-label="打印缩放方式"]')).not.toBeNull()
  expect(document.querySelector<HTMLInputElement>('[aria-label="重复标题行数"]')?.value).toBe('1')
  expect(document.querySelector('[aria-label="打印缩放（%）"]')).toBeNull()
  expect(document.body.textContent).not.toMatch(/纸张|页眉|边距/)
})
it('按比例打印不展示适配页数，重复标题可设为零', async () => {
  await act(async () => root.render(<WorkbookPrintFields document={{ xlsx: { print: { ...print, fitToWidth: null, scalePercent: 75 } } }} onChange={update} />))
  const scale = document.querySelector<HTMLInputElement>('[aria-label="打印缩放（%）"]')!
  expect(Number(scale.value)).toBe(75)
  expect(scale.getAttribute('aria-valuemin')).toBe('10')
  expect(scale.getAttribute('aria-valuemax')).toBe('400')
  const repeat = document.querySelector<HTMLInputElement>('[aria-label="重复标题行数"]')!
  expect(repeat.getAttribute('aria-valuemin')).toBe('0')
  expect(document.querySelector('[aria-label="适配宽度（页）"]')).toBeNull()
})
it('切换缩放方式一次性清除冲突字段，保留纸张和页眉配置', async () => {
  await act(async () => root.render(<WorkbookPrintFields document={{ xlsx: { print: { ...print, fitToWidth: null, scalePercent: 75 } } }} onChange={update} />))
  await act(async () => document.querySelector('[aria-label="打印缩放方式"]')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })))
  const option = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option')].find(item => item.textContent === '整张表适配一页')!
  expect(option).toBeTruthy()
  await act(async () => option.click())
  expect(update).toHaveBeenLastCalledWith(['xlsx', 'print'], { ...print, fitToWidth: 1, fitToHeight: 1, scalePercent: null })
})
