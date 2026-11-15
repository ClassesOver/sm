import { afterEach, expect, it, vi } from 'vitest'

const defaults = { version: 0, modelId: '', imageModel: '', searchEnabled: true, integrationsEnabled: true }
afterEach(() => { vi.unstubAllGlobals(); document.body.replaceChildren(); vi.resetModules() })

it.each(['load', 'save', 'provider'])('登录失效后忽略迟到的管理员配置%s响应', async phase => {
  document.body.innerHTML = '<main id="office-admin"></main>'
  let finish!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit) => {
    if (url.endsWith('/session')) return new Response(JSON.stringify({ user: { user: '10', name: 'Admin', role: 'admin' }, csrfToken: 'token' }))
    if (url.endsWith('/admin/providers')) return new Response(JSON.stringify({ settings: {chatModel: {enabled: true, provider: 'custom', model: 'test-model', baseUrl: 'https://example.com', version: 0, hasKey: true}}, catalog: {chatModel: [{id: 'custom', label: 'Custom', model: 'test-model', baseUrl: 'https://example.com'}]}, credentialStorageAvailable: true }))
    if (phase === 'load' || options.method === 'PUT' || url.endsWith('/test')) return await new Promise<Response>(resolve => { finish = resolve })
    return new Response(JSON.stringify(defaults))
  }))
  await import('./office-admin')
  if (phase === 'save') {
    await vi.waitFor(() => expect(document.querySelector('.office-admin-layout > section > form input')).not.toBeNull())
    const input = document.querySelector<HTMLInputElement>('.office-admin-layout > section > form input')!
    input.value = 'pending-model'; input.dispatchEvent(new Event('input', { bubbles: true }))
    document.querySelector('.office-admin-layout > section > form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  }
  if (phase === 'provider') {
    await vi.waitFor(() => expect([...document.querySelectorAll('button')].find(x => x.textContent === '测试对话模型')).toBeDefined())
    ;[...document.querySelectorAll('button')].find(x => x.textContent === '测试对话模型')!.click()
  }
  await vi.waitFor(() => expect(finish).toBeDefined())
  const { expireOfficeSession } = await import('./office-client')
  expireOfficeSession()
  expect(document.querySelector('#office-admin')!.textContent).toContain('登录已失效')
  const pendingUnload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(pendingUnload)
  expect(pendingUnload.defaultPrevented).toBe(false)
  finish(new Response(JSON.stringify({ ...defaults, modelId: 'late-model', version: 1 })))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(document.querySelector('#office-admin')!.textContent).toContain('登录已失效')
  expect(document.querySelector('input')).toBeNull()
  const unload = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(unload)
  expect(unload.defaultPrevented).toBe(false)
})
