import { expect, it, vi } from 'vitest'
import { expireOfficeSession, officeCsrf } from './office-client'

it('keeps a newer login and its workspace when the startup session arrives late', async () => {
  document.body.innerHTML = '<div id="office"></div>'
  const startup = Promise.withResolvers<Response>()
  const laterWorkspaces = Promise.withResolvers<Response>()
  let workspaceRequests = 0
  const json = (data: unknown) => new Response(JSON.stringify(data))
  const request = vi.fn((url: string, init?: RequestInit) => {
    if (url === '/office/api/session') {
      if (init?.method === 'GET') return startup.promise
      return Promise.resolve(json({
        user: { user: 'current', name: 'Current user', role: 'admin', enabled: true }, csrfToken: 'current-token',
      }))
    }
    if (url === '/office/api/workspaces') {
      if (++workspaceRequests > 1) return laterWorkspaces.promise
      return Promise.resolve(json({
        items: [{ id: 'current-space', name: 'Current workspace', role: 'owner', archived: false, personal_user: null }],
      }))
    }
    if (url.endsWith('/library')) return Promise.resolve(json({ folders: [], files: [] }))
    if (url === '/office/api/settings') return Promise.resolve(json({ scope: 'current', theme: 'system' }))
    return Promise.resolve(json({}))
  })
  vi.stubGlobal('fetch', request)
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
  const dialog = HTMLDialogElement.prototype
  const showModal = Object.getOwnPropertyDescriptor(dialog, 'showModal')
  const close = Object.getOwnPropertyDescriptor(dialog, 'close')
  Object.defineProperties(dialog, {
    showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true } },
    close: { configurable: true, value(this: HTMLDialogElement) {
      this.open = false
      this.dispatchEvent(new Event('close'))
    } },
  })
  try {
    await import('./office-main')
    const login = () => {
      document.querySelector<HTMLButtonElement>('[data-action="login"]')!.click()
      const form = document.querySelector<HTMLFormElement>('dialog form')!
      form.dispatchEvent(new Event('submit', { cancelable: true }))
    }
    login()
    await vi.waitFor(() => expect(document.body.textContent).toContain('Current workspace'))
    startup.resolve(json({
      user: { user: 'stale', name: 'Stale user', role: 'admin', enabled: true }, csrfToken: 'stale-token',
    }))
    await startup.promise
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(document.body.textContent).toContain('Current user')
    expect(document.body.textContent).not.toContain('Stale user')
    expect(request.mock.calls.filter(([url]) => url === '/office/api/workspaces')).toHaveLength(1)
    expect(officeCsrf()).toBe('current-token')

    expireOfficeSession()
    login()
    await vi.waitFor(() => expect(workspaceRequests).toBe(2))
    expireOfficeSession()
    laterWorkspaces.resolve(json({
      items: [{ id: 'late-space', name: 'Expired workspace', role: 'owner', archived: false, personal_user: null }],
    }))
    await laterWorkspaces.promise
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(document.body.textContent).toContain('登录已失效')
    expect(document.body.textContent).not.toContain('Expired workspace')
    expect(request.mock.calls.some(([url]) => url.includes('/late-space/'))).toBe(false)
  } finally {
    if (showModal) Object.defineProperty(dialog, 'showModal', showModal)
    else Reflect.deleteProperty(dialog, 'showModal')
    if (close) Object.defineProperty(dialog, 'close', close)
    else Reflect.deleteProperty(dialog, 'close')
    vi.unstubAllGlobals()
    document.body.replaceChildren()
  }
})
