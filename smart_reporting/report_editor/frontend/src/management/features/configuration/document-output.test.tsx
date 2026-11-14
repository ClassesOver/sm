import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DocumentStructureFields } from './document-output'

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
const initial = { word: { cover: true, toc: true, sources: false }, pdf: { cover: false, toc: false, sources: true } }

it('Word结构选项逐项维护，不修改PDF或落款设置', async () => {
  await act(async () => root.render(<DocumentStructureFields document={initial} format="word" onChange={update} />))
  expect(document.querySelectorAll('[role="switch"]')).toHaveLength(3)
  expect(document.querySelector('[aria-label="生成封面"]')!.getAttribute('aria-checked')).toBe('true')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="来源附录"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['word', 'sources'], true)
  expect(initial.pdf).toEqual({ cover: false, toc: false, sources: true })
  expect(document.body.textContent).toContain('实际登记来源')
})

it('PDF独立读取结构选项并在保存期间禁止修改', async () => {
  await act(async () => root.render(<DocumentStructureFields document={initial} format="pdf" onChange={update} disabled />))
  expect(document.querySelector('[aria-label="生成目录"]')!.getAttribute('aria-checked')).toBe('false')
  const toggle = document.querySelector<HTMLButtonElement>('[aria-label="来源附录"]')!
  expect(toggle.getAttribute('aria-checked')).toBe('true')
  expect(toggle.disabled).toBe(true)
  await act(async () => toggle.click())
  expect(update).not.toHaveBeenCalled()
})
