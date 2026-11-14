import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Form } from 'antd'
import { CommonStyleFields } from './common-style'
let root: Root
const update = vi.fn()
const values = { common: { font: 'sans', accentColor: '#174a66' }, word: { common: { font: 'serif', accentColor: null } } }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })
async function mount(format = 'word', disabled = false) {
  await act(async () => root.render(<Form><CommonStyleFields document={values} format={format} onChange={update} disabled={disabled} /></Form>))
}
it('格式覆盖显示实际字体与沿用来源，恢复只更新当前字段', async () => {
  await mount()
  expect(document.querySelector<HTMLInputElement>('[aria-label="主题色"]')?.value).toBe('#174a66')
  expect(document.body.textContent).toContain('已单独设置')
  expect(document.body.textContent).toContain('沿用通用偏好')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="恢复沿用字体"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['word', 'common', 'font'], null)
})
it('通用样式不提供继承按钮，Markdown不显示物理样式', async () => {
  await mount('common')
  expect(document.querySelector('[aria-label="字体"]')).not.toBeNull()
  expect(document.querySelector('[aria-label="恢复沿用字体"]')).toBeNull()
  await mount('md')
  expect(document.querySelector('[aria-label="字体"]')).toBeNull()
  expect(document.querySelector('[aria-label="主题色"]')).toBeNull()
})
it('保存时禁止恢复覆盖', async () => {
  await mount('word', true)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="恢复沿用字体"]')!.click())
  expect(update).not.toHaveBeenCalled()
})
