import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CredentialReplacement } from './credential-replacement'
import { request } from '../../api/http'

vi.mock('../../api/http', () => ({ request: vi.fn() }))
let root: Root
const refresh = vi.fn()
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); vi.clearAllMocks() })

it('替换按需打开，输入隐藏且关闭后清空，普通表单不常驻密码框', async () => {
  await act(async () => root.render(<CredentialReplacement credentialKey="OPENAI_API_KEY" label="模型服务凭据" version={3} csrf="csrf" configured disabled={false} onSaved={refresh} />))
  expect(document.querySelector('input[type="password"]')).toBeNull()
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="替换模型服务凭据"]')!.click())
  const input = document.querySelector<HTMLInputElement>('[aria-label="新凭据"]')!
  expect(input.type).toBe('password')
  expect(input.autocomplete).toBe('new-password')
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => { setter.call(input, 'private-value'); input.dispatchEvent(new Event('input', { bubbles: true })) })
  vi.mocked(request).mockResolvedValue({ version: 4, contentHash: 'hash' })
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="保存新凭据到草稿"]')!.click())
  expect(request).toHaveBeenCalledWith('/configuration/system/credentials/OPENAI_API_KEY', expect.anything(), {
    method: 'PUT', csrf: 'csrf', body: { expectedVersion: 3, secret: 'private-value' },
  })
  expect(refresh).toHaveBeenCalledOnce()
  expect(document.querySelector('input[type="password"]')).toBeNull()
})

it('存在普通配置未保存修改时禁止替换，避免回读覆盖输入', async () => {
  await act(async () => root.render(<CredentialReplacement credentialKey="OPENAI_API_KEY" label="模型服务凭据" version={3} csrf="csrf" configured disabled onSaved={refresh} />))
  expect(document.querySelector<HTMLButtonElement>('[aria-label="替换模型服务凭据"]')!.disabled).toBe(true)
})

it('提交结果不明时清空秘密并保留回读提示，禁止直接重复空提交', async () => {
  await act(async () => root.render(<CredentialReplacement credentialKey="OPENAI_API_KEY" label="模型服务凭据" version={3} csrf="csrf" configured disabled={false} onSaved={refresh} />))
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="替换模型服务凭据"]')!.click())
  const input = document.querySelector<HTMLInputElement>('[aria-label="新凭据"]')!
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => { setter.call(input, 'private-value'); input.dispatchEvent(new Event('input', { bubbles: true })) })
  vi.mocked(request).mockRejectedValue(new Error('提交结果待确认'))
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="保存新凭据到草稿"]')!.click())
  expect(document.querySelector<HTMLInputElement>('[aria-label="新凭据"]')!.value).toBe('')
  expect(document.body.textContent).toContain('回读最新状态')
  expect(document.querySelector<HTMLButtonElement>('[aria-label="保存新凭据到草稿"]')!.disabled).toBe(true)
  expect(refresh).not.toHaveBeenCalled()
})
