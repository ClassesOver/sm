import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { App } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TablePreferenceFields } from './table-editor'
import { TypographyFields } from './typography'
import Preferences from './preferences'
import type { ConfigurationDetail } from './contracts'

vi.mock('../../app/session', () => ({ useSession: () => ({ state: { session: { csrfToken: 'test-csrf' } } }) }))
let root: Root
const update = vi.fn()
const style = { font: null, size: 12, color: '#123456', bold: false, lineHeight: 1.5, spaceBefore: 0, spaceAfter: 3, indent: 0 }
const value = { common: { signer: '表格维护验证', dateFormat: 'iso', font: 'sans', accentColor: '#174a66' },
  pptx: { common: {}, signature: { ...style, align: 'right', description: '' },
    tables: { repeatHeader: true, borders: 'light', striped: true, captionNumbering: true, splitRows: false },
    typography: { body: style, h1: style, table: style, caption: style } },
  word: { common: {}, signature: { ...style, align: 'right', description: '' } } }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })

it('演示文稿表格只开放四项已执行设置，更新精确路径且不显示Word分页开关', async () => {
  await act(async () => root.render(<TablePreferenceFields document={value} format="pptx" onChange={update} />))
  expect(document.querySelector('[aria-label="重复表头"]')).not.toBeNull()
  expect(document.querySelector('[aria-label="边框"]')).not.toBeNull()
  expect(document.querySelector('[aria-label="交替条纹"]')).not.toBeNull()
  const numbering = document.querySelector<HTMLButtonElement>('[aria-label="表格标题编号"]')!
  expect(numbering).not.toBeNull()
  await act(async () => numbering.click())
  expect(update).toHaveBeenLastCalledWith(['pptx', 'tables', 'captionNumbering'], false)
  expect(document.querySelector('[aria-label="允许跨页断行"]')).toBeNull()
  expect(document.querySelector('[aria-label="图片与说明同页"]')).toBeNull()
  await act(async () => root.render(<TablePreferenceFields document={value} format="pptx" onChange={update} disabled />))
  expect(document.querySelector<HTMLButtonElement>('[aria-label="重复表头"]')!.disabled).toBe(true)
})

it('演示文稿可选择真实表格文字角色，首行缩进沿用默认折叠的段落细节', async () => {
  await act(async () => root.render(<TypographyFields document={value} format="pptx" onChange={update} />))
  await act(async () => document.querySelector('[aria-label="排版对象"]')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })))
  const option = document.querySelector<HTMLDivElement>('.ant-select-item-option[title="表格文字"]')!
  expect(option).not.toBeNull()
  await act(async () => option.click())
  expect(document.querySelector('[aria-label="排版行距"]')).toBeNull()
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="排版加粗"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['pptx', 'typography', 'table', 'bold'], true)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="段落细节"]')!.click())
  for (const label of ['排版行距', '段前（磅）', '段后（磅）']) expect(document.querySelector(`[aria-label="${label}"]`)).not.toBeNull()
  expect(document.querySelector('[aria-label="首行缩进（磅）"]')).not.toBeNull()
})

it('偏好页面演示文稿目录可进入表格，仍走同一草稿确认保存流程', async () => {
  const detail: ConfigurationDetail = { draft: { version: 3, document: value, contentHash: 'draft', updatedAt: '2026-11-13' },
    initial: value, effective: null, changes: [], application: { canApply: false, reason: '尚未验收' } }
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  client.setQueryData(['configuration', 'preferences'], detail)
  const router = createMemoryRouter([{ path: '/', element: <Preferences /> }])
  await act(async () => root.render(<App><QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider></App>))
  const tab = [...document.querySelectorAll<HTMLElement>('[role="tab"]')].find(item => item.textContent === '演示文稿')!
  await act(async () => tab.click())
  const menu = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find(item => item.textContent === '表格与图表')!
  expect(menu).not.toBeUndefined()
  await act(async () => menu.click())
  expect(document.querySelector('[aria-label="表格标题编号"]')).not.toBeNull()
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="表格标题编号"]')!.click())
  const save = [...document.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent === '保存偏好草稿')!
  await act(async () => save.click())
  expect(document.querySelector('.ant-modal-body')?.textContent).toContain('标题编号')
  expect(document.querySelector('.ant-modal-body')?.textContent).not.toContain('图注编号')
})

it('演示文稿表格文字校验定位具体字段，不漏过新开放角色', async () => {
  const { validateSignatureDraft, setPreferenceValue } = await import('./preference-draft')
  for (const [property, invalid] of [['size', 99], ['color', 'red'], ['lineHeight', 0.5], ['spaceBefore', -1], ['spaceAfter', 99]]) {
    const changed = setPreferenceValue(value, ['pptx', 'typography', 'table', String(property)], invalid)
    expect(validateSignatureDraft(changed)).toContainEqual(expect.objectContaining({ path: 'pptx.typography.table.' + property }))
  }
})
