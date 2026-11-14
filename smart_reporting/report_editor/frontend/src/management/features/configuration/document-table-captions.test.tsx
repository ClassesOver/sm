import React, { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { App } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TablePreferenceFields } from './table-editor'
import { SignatureEditor } from './signature-editor'
import type { ConfigurationDetail } from './contracts'

let root: Root
const update = vi.fn(), navigate = vi.fn()
const documentValue = { common: { signer: '表题维护验证', dateFormat: 'iso', font: 'sans', accentColor: '#174a66' },
  word: { common: {}, tables: { repeatHeader: true, splitRows: false, borders: 'light', striped: false, captionNumbering: true }, signature: { description: '', size: 11, align: 'right' } },
  pdf: { common: {}, tables: { repeatHeader: true, splitRows: false, borders: 'light', striped: false, captionNumbering: false }, signature: { description: '', size: 11, align: 'right' } } }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset(); navigate.mockReset() })

it.each(['word', 'pdf'])('%s表题开关只更新当前格式，保存时禁止输入', async format => {
  await act(async () => root.render(<TablePreferenceFields document={documentValue} format={format} onChange={update} />))
  const toggle = document.querySelector<HTMLButtonElement>('[aria-label="表格标题编号"]')!
  expect(toggle).not.toBeNull()
  expect(toggle.getAttribute('aria-checked')).toBe(String(format === 'word'))
  expect(document.body.textContent).toContain('仅对已登记的表格标题编号')
  await act(async () => toggle.click())
  expect(update).toHaveBeenLastCalledWith([format, 'tables', 'captionNumbering'], format !== 'word')
  expect(documentValue.word.tables.captionNumbering).toBe(true)
  expect(documentValue.pdf.tables.captionNumbering).toBe(false)
  update.mockReset()
  await act(async () => root.render(<TablePreferenceFields document={documentValue} format={format} onChange={update} disabled />))
  expect(document.querySelector<HTMLButtonElement>('[aria-label="表格标题编号"]')!.disabled).toBe(true)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="表格标题编号"]')!.click())
  expect(update).not.toHaveBeenCalled()
})

async function mountEditor(format: string, invalid = false) {
  const value = structuredClone(documentValue)
  if (invalid) (value[format as 'word' | 'pdf'].tables as Record<string, unknown>).captionNumbering = 'bad'
  const detail: ConfigurationDetail = { draft: { version: 3, document: value, contentHash: 'draft', updatedAt: '2026-11-13' },
    initial: value, effective: null, changes: [], application: { canApply: false, reason: '尚未验收' } }
  function Editor() {
    const [section, setSection] = useState(invalid ? 'signature' : 'tables')
    return <SignatureEditor detail={detail} format={format} common={false} csrf="test" section={section}
      active={section === 'signature'} readonlyContent={null} onNavigate={(nextFormat, next = 'signature') => {
        navigate(nextFormat, next); setSection(next)
      }} />
  }
  const router = createMemoryRouter([{ path: '/', element: <Editor /> }])
  await act(async () => root.render(<App><QueryClientProvider client={new QueryClient()}><RouterProvider router={router} /></QueryClientProvider></App>))
}
const save = () => [...document.querySelectorAll('button')].find(button => button.textContent === '保存偏好草稿')!

it.each(['word', 'pdf'])('%s保存差异明确是表题编号，不混同图注', async format => {
  await mountEditor(format)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="表格标题编号"]')!.click())
  await act(async () => save().click())
  const changes = [...document.querySelectorAll('.ant-modal-body li')].map(item => item.textContent)
  expect(changes).toEqual([expect.stringContaining('表格标题编号')])
  expect(changes[0]).not.toContain('图注编号')
  expect(changes[0]).toContain(format === 'word' ? '开启 → 关闭' : '关闭 → 开启')
})

it.each(['word', 'pdf'])('%s表题错误从落款导航到表格并聚焦开关', async format => {
  await mountEditor(format, true)
  const signer = document.querySelector<HTMLInputElement>('[aria-label="格式署名"]')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(signer, '修改后的署名')
    signer.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await act(async () => save().click())
  expect(navigate).toHaveBeenLastCalledWith(format, 'tables')
  expect(document.activeElement?.id).toBe('preference-' + format + '.tables.captionNumbering')
  expect(document.body.textContent).toContain('请选择开启或关闭表格标题编号')
  expect(document.querySelector('.ant-modal-body')).toBeNull()
})
