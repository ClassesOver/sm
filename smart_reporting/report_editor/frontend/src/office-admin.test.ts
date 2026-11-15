import { expect, it, vi } from 'vitest'

it('保存期间冻结全局表单，防止在途编辑被服务器回执覆盖', async () => {
  document.body.innerHTML = '<main id="office-admin"></main>'
  const defaults = { version: 0, modelId: '', imageModel: '', searchEnabled: true, integrationsEnabled: true }
  let finish!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/session')) return new Response(JSON.stringify({ user: { user: '10', name: 'Admin', role: 'admin', enabled: true }, csrfToken: 'token' }))
    if (url.endsWith('/admin/providers')) return new Response(JSON.stringify({settings:{chatModel:{enabled:false,provider:'custom',model:'',baseUrl:'https://example.com',version:0,hasKey:false}},catalog:{chatModel:[{id:'custom',label:'Custom',model:'',baseUrl:'https://example.com'}]},credentialStorageAvailable:true}))
    if (options?.method === 'PUT') return await new Promise<Response>(resolve => { finish = resolve })
    return new Response(JSON.stringify(defaults))
  }))
  await import('./office-admin')
  await vi.waitFor(() => expect(document.querySelector('input')).not.toBeNull())
  const input = document.querySelector<HTMLInputElement>('.office-admin-layout > section > form input')!
  input.value = 'new-model'; input.dispatchEvent(new Event('input', { bubbles: true }))
  document.querySelector('.office-admin-layout > section > form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  expect(input.disabled).toBe(true)
  expect([...document.querySelectorAll<HTMLButtonElement>('nav button')].every(x => x.disabled)).toBe(true)
  finish(new Response(JSON.stringify({ ...defaults, version: 1, modelId: 'new-model' })))
  await vi.waitFor(() => expect(input.disabled).toBe(false))
  expect(document.querySelector('.office-admin-layout > section > [role="status"]')!.textContent).toContain('已保存')
  vi.unstubAllGlobals()
})
