import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PdfOutputFields } from './pdf-output'

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
const initial = { pdf: { bookmarks: true, imageQuality: 90, embedFonts: true } }
it('只维护已验证的书签与图像质量，不暴露未接通的字体开关', async () => {
  await act(async () => root.render(<PdfOutputFields document={initial} onChange={update} />))
  expect(document.querySelector('[aria-label="生成书签"]')).not.toBeNull()
  expect(document.querySelector<HTMLInputElement>('[aria-label="JPEG 图像质量"]')!.value).toBe('90')
  expect(document.body.textContent).not.toContain('嵌入字体')
  expect(document.body.textContent).toContain('字体始终嵌入')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="生成书签"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['pdf', 'bookmarks'], false)
})
it('保存期间禁止修改且质量范围匹配服务端', async () => {
  await act(async () => root.render(<PdfOutputFields document={initial} onChange={update} disabled />))
  expect(document.querySelector<HTMLButtonElement>('[aria-label="生成书签"]')!.disabled).toBe(true)
  const quality = document.querySelector<HTMLInputElement>('[aria-label="JPEG 图像质量"]')!
  expect(quality.disabled).toBe(true)
  expect(quality.getAttribute('aria-valuemin')).toBe('50')
  expect(quality.getAttribute('aria-valuemax')).toBe('100')
})
