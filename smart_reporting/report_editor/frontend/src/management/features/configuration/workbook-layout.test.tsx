import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { WorkbookLayoutFields } from './workbook-layout'

let root: Root
const update = vi.fn()
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })
it('默认尺寸可留空、换行只修改显示字段，错误显示在原生单位旁', async () => {
  await act(async () => root.render(<WorkbookLayoutFields document={{ xlsx: { alignment: 'left', wrapText: true, rowHeight: null, columnWidth: null } }} onChange={update}
    errors={[{ path: 'xlsx.rowHeight', message: '行高越界' }]} />))
  expect(document.querySelector<HTMLInputElement>('[aria-label="行高（磅）"]')?.value).toBe('')
  expect(document.body.textContent).toContain('行高越界')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="自动换行"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['xlsx', 'wrapText'], false)
})
it('保存时禁用所有布局输入', async () => {
  await act(async () => root.render(<WorkbookLayoutFields document={{ xlsx: { alignment: 'right', wrapText: false } }} onChange={update} disabled />))
  expect(document.querySelector<HTMLInputElement>('[aria-label="列宽（字符）"]')?.disabled).toBe(true)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="自动换行"]')!.click())
  expect(update).not.toHaveBeenCalled()
})
