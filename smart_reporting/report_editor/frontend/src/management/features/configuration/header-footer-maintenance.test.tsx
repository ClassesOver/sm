import React, { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { App } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { HeaderFooterFields } from './document-fields'
import { validateSignatureDraft } from './preference-draft'
import { SignatureEditor } from './signature-editor'
import type { ConfigurationDetail } from './contracts'

let root: Root
const update = vi.fn(), navigate = vi.fn()
const layoutFields = [
  ['headerDistance', '页眉距页面顶端（毫米）', 12, 0, 50],
  ['footerDistance', '页脚距页面底端（毫米）', 14, 0, 50],
  ['pageNumberStart', '正文页码起点', 5, 1, 9999],
] as const
const value = { enabled: true, header: { left: '报告', center: '', right: '' },
  footer: { left: '', center: '', right: '{page}/{pages}' },
  style: { font: null, size: 9, color: '#475467', bold: false },
  firstPageDifferent: false, oddEvenDifferent: false,
  headerDistance: 12, footerDistance: 14, divider: false, pageNumberStart: 5 }
const documentValue = (format: string): Record<string, unknown> => ({ common: { signer: '维护验证', dateFormat: 'iso', font: 'sans', accentColor: '#174a66' },
  [format]: { common: {}, signature: { font: null, size: 11, color: null, align: 'right', bold: false, description: '' },
    ...(format === 'xlsx' ? { print: { headerFooter: { ...value } } } : format === 'pptx' ? { footer: value.footer, footerStyle: value.style } : { headerFooter: { ...value } }) } })

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset(); navigate.mockReset() })
async function input(label: string, next: string) {
  const field = document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field, next)
    field.dispatchEvent(new Event('input', { bubbles: true }))
    field.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

it.each(['word', 'pdf'])('%s位置、分隔线、正文页码默认折叠，沿用原路径和真实边界', async format => {
  await act(async () => root.render(<HeaderFooterFields document={documentValue(format)} format={format} onChange={update} />))
  const toggle = document.querySelector<HTMLButtonElement>('[aria-label="页眉页脚样式"]')!
  expect(toggle.getAttribute('aria-expanded')).toBe('false')
  expect(document.querySelector('[aria-label="正文页码起点"]')).toBeNull()
  await act(async () => toggle.click())
  for (const [key, label, initial, min, max] of layoutFields) {
    const field = document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!
    expect(field).not.toBeNull(); expect(Number(field.value)).toBe(initial)
    expect(Number(field.getAttribute('aria-valuemin'))).toBe(min); expect(Number(field.getAttribute('aria-valuemax'))).toBe(max)
    await input(label, key === 'pageNumberStart' ? '6' : '15.5')
    expect(update).toHaveBeenLastCalledWith([format, 'headerFooter', key], key === 'pageNumberStart' ? 6 : 15.5)
  }
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="页眉页脚分隔线"]')!.click())
  expect(update).toHaveBeenLastCalledWith([format, 'headerFooter', 'divider'], true)
  expect(document.querySelectorAll('form')).toHaveLength(1)
})

it.each(['word', 'pdf'])('%s禁用时所有新增控件不能更改', async format => {
  await act(async () => root.render(<HeaderFooterFields document={documentValue(format)} format={format} onChange={update}
    errors={[{ path: format + '.headerFooter.pageNumberStart', message: '页码起点越界' }]} />))
  await act(async () => root.render(<HeaderFooterFields document={documentValue(format)} format={format} onChange={update} disabled />))
  for (const [, label] of layoutFields) expect(document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)?.disabled).toBe(true)
  const divider = document.querySelector<HTMLButtonElement>('[aria-label="页眉页脚分隔线"]')!
  expect(divider.disabled).toBe(true)
  await act(async () => divider.click())
  expect(update).not.toHaveBeenCalled()
})

it.each(['xlsx', 'pptx'])('%s不开放文档位置、页码起点或unsupported分隔线', async format => {
  await act(async () => root.render(<HeaderFooterFields document={documentValue(format)} format={format} onChange={update} />))
  await act(async () => document.querySelector<HTMLButtonElement>(`[aria-label="${format === 'pptx' ? '页脚' : '页眉页脚'}样式"]`)!.click())
  for (const [, label] of layoutFields) expect(document.querySelector(`[aria-label="${label}"]`)).toBeNull()
  expect(document.querySelector('[aria-label="页眉页脚分隔线"]')).toBeNull()
})

it.each(['word', 'pdf'].flatMap(format => [...layoutFields.map(([key]) => key), 'divider'].map(key => [format, key])))('%s的%s错误自动展开并聚焦，修正后保留展开', async (format, key) => {
  await act(async () => root.render(<HeaderFooterFields document={documentValue(format)} format={format} onChange={update}
    errors={[{ path: `${format}.headerFooter.${key}`, message: '当前字段需修正' }]} />))
  expect(document.activeElement?.id).toBe(`preference-${format}.headerFooter.${key}`)
  expect(document.querySelector('[aria-label="页眉页脚样式"]')?.getAttribute('aria-expanded')).toBe('true')
  expect(document.body.textContent).toContain('当前字段需修正')
  await act(async () => root.render(<HeaderFooterFields document={documentValue(format)} format={format} onChange={update} />))
  expect(document.querySelector('[aria-label="正文页码起点"]')).not.toBeNull()
})

it.each(['word', 'pdf'])('%s数值校验遵守现有0–50毫米与1–9999整数边界', format => {
  const document = documentValue(format)
  Object.assign((document[format] as { headerFooter: typeof value }).headerFooter,
    { headerDistance: -1, footerDistance: 51, pageNumberStart: 1.2 })
  expect(validateSignatureDraft(document).map(error => error.path)).toEqual(expect.arrayContaining([
    `${format}.headerFooter.headerDistance`, `${format}.headerFooter.footerDistance`, `${format}.headerFooter.pageNumberStart`,
  ]))
  Object.assign((document[format] as { headerFooter: typeof value }).headerFooter,
    { headerDistance: 0, footerDistance: 50, pageNumberStart: 9999 })
  expect(validateSignatureDraft(document).filter(error => error.path.includes('headerFooter'))).toEqual([])
})

async function mountEditor(format: string, invalid = false) {
  const document = documentValue(format)
  if (invalid) document[format] = { ...(document[format] as object), headerFooter: { ...value, pageNumberStart: 0 } }
  const detail: ConfigurationDetail = { draft: { version: 3, document, contentHash: 'draft', updatedAt: '2026-11-13' },
    initial: document, effective: null, changes: [], application: { canApply: false, reason: '尚未验收' } }
  function Editor() {
    const [section, setSection] = useState(invalid ? 'signature' : 'headerFooter')
    return <SignatureEditor detail={detail} format={format} common={false} csrf="test" section={section}
      active={section === 'signature'} readonlyContent={null} onNavigate={(format, next = 'signature') => {
        navigate(format, next); setSection(next)
      }} />
  }
  const router = createMemoryRouter([{ path: '/', element: <Editor /> }])
  await act(async () => root.render(<App><QueryClientProvider client={new QueryClient()}><RouterProvider router={router} /></QueryClientProvider></App>))
}
const save = () => [...document.querySelectorAll('button')].find(button => button.textContent === '保存偏好草稿')!

it.each(['word', 'pdf'])('%s保存差异准确展示四个维护标签', async format => {
  await mountEditor(format)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="页眉页脚样式"]')!.click())
  for (const [key, label] of layoutFields) await input(label, key === 'pageNumberStart' ? '6' : '15.5')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="页眉页脚分隔线"]')!.click())
  await act(async () => save().click())
  const changes = [...document.querySelectorAll('.ant-modal-body li')].map(item => item.textContent)
  expect(changes).toHaveLength(4)
  for (const label of [...layoutFields.map(([, label]) => label), '页眉页脚分隔线']) expect(changes.some(text => text?.includes(label))).toBe(true)
  expect(changes.some(text => text?.includes('附加说明'))).toBe(false)
})

it.each(['word', 'pdf'])('%s保存错误从落款导航到页眉页脚并定位页码起点', async format => {
  await mountEditor(format, true)
  await input('格式署名', '修改署名')
  await act(async () => save().click())
  expect(navigate).toHaveBeenLastCalledWith(format, 'headerFooter')
  expect(document.activeElement?.id).toBe(`preference-${format}.headerFooter.pageNumberStart`)
})
