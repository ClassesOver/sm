import React, { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { App } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SignatureEditor } from './signature-editor'
import type { ConfigurationDetail } from './contracts'

let root: Root
const navigate = vi.fn()
const style = { font: null, size: 14, color: '#345678', bold: false }
function detail(invalid?: string): ConfigurationDetail {
  const documentValue = { common: { signer: '维护验证', dateFormat: 'iso', font: 'sans', accentColor: '#174a66' },
    pptx: { common: {}, signature: { ...style, size: 11, align: 'right', description: '' },
      footer: { left: '', center: '', right: '{slide}/{slides}' },
      footerStyle: { ...style, ...(invalid === 'size' ? { size: 99 } : invalid === 'color' ? { color: 'red' } : {}) } } }
  return { draft: { version: 3, document: documentValue, contentHash: 'draft', updatedAt: '2026-11-13' },
    initial: documentValue, effective: null, changes: [], application: { canApply: false, reason: '尚未验收' } }
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); navigate.mockReset() })
async function mount(value: ConfigurationDetail, initialSection: string) {
  function Editor() {
    const [section, setSection] = useState(initialSection)
    return <SignatureEditor detail={value} format="pptx" common={false} csrf="test" section={section}
      active={section === 'signature'} readonlyContent={null} onNavigate={(format, next = 'signature') => {
        navigate(format, next); setSection(next)
      }} />
  }
  const router = createMemoryRouter([{ path: '/', element: <Editor /> }])
  await act(async () => root.render(<App><QueryClientProvider client={new QueryClient()}><RouterProvider router={router} /></QueryClientProvider></App>))
}
const save = () => [...document.querySelectorAll('button')].find(button => button.textContent === '保存偏好草稿')!

it.each(['size', 'color'])('PPTX页脚%s错误从落款导航到页脚设置并聚焦真实字段', async invalid => {
  await mount(detail(invalid), 'signature')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="落款样式"]')!.click())
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="落款加粗"]')!.click())
  await act(async () => save().click())
  expect(navigate).toHaveBeenLastCalledWith('pptx', 'headerFooter')
  expect(document.activeElement?.id).toBe('preference-pptx.footerStyle.' + invalid)
  expect(document.querySelector('[aria-label="页脚样式"]')?.getAttribute('aria-expanded')).toBe('true')
})

it('PPTX保存差异把页脚样式准确标为页脚加粗', async () => {
  await mount(detail(), 'headerFooter')
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="页脚样式"]')!.click())
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="页脚加粗"]')!.click())
  await act(async () => save().click())
  const changes = [...document.querySelectorAll('.ant-modal-body li')].map(item => item.textContent)
  expect(changes).toEqual([expect.stringContaining('页脚 · 加粗')])
  expect(changes[0]).toContain('关闭 → 开启')
  expect(changes[0]).not.toContain('附加说明')
})
