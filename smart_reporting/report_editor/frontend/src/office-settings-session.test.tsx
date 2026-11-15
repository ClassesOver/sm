import { act } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { showOfficeSettings } from './office-settings'
import { applyOfficeTheme } from './office-personal-theme'

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({matches: false, addEventListener() {}, removeEventListener() {}}))
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable: true, value(this: HTMLDialogElement) { this.open = true }})
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {configurable: true, value(this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) }})
  document.body.innerHTML = '<main id="host"></main>'
})
afterEach(async () => {
  await act(async () => { for (const dialog of document.querySelectorAll('dialog')) dialog.close() })
  vi.restoreAllMocks(); vi.unstubAllGlobals(); document.body.replaceChildren()
  delete document.documentElement.dataset.officeTheme
})

it.each([false, true])('退出响应仅影响发起请求的账户（账户已切换=%s）', async changed => {
  let current = true, finish!: (response: Response) => void
  const onLogout = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/logout')) return await new Promise<Response>(resolve => { finish = resolve })
    return new Response(JSON.stringify({theme: 'light', skills: [], version: 0, scope: 'alice'}))
  }))
  await act(async () => { await showOfficeSettings(document.querySelector('#host')!, {
    user: {user: 'alice', name: 'Alice', role: 'user', enabled: true},
    isCurrent: () => current, onLogout,
  }) })
  await act(async () => { [...document.querySelectorAll('button')].find(x => x.textContent === '退出登录')!.click() })
  expect(finish).toBeDefined()
  current = !changed
  applyOfficeTheme('dark')
  await act(async () => { finish(new Response('{}')) })
  if (changed) {
    expect(onLogout).not.toHaveBeenCalled()
    expect(document.documentElement.dataset.officeTheme).toBe('dark')
    expect(document.querySelector('[role="alert"]')!.textContent).toContain('账户已变化')
  } else {
    expect(onLogout).toHaveBeenCalledOnce()
    expect(document.documentElement.dataset.officeTheme).toBe('light')
    expect(document.querySelector('dialog')).toBeNull()
  }
})
