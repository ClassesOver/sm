import { afterEach, expect, it, vi } from 'vitest'
import { z } from 'zod'
import { advanceSession, request, setUnauthorized } from './http'
afterEach(() => {
  vi.unstubAllGlobals()
  setUnauthorized(undefined)
})
it('成功响应载荷不合法时返回协议错误', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}')))
  await expect(
    request('/me', z.object({ username: z.string() })),
  ).rejects.toMatchObject({ code: 'protocol_error' })
})
it('解析缓慢的旧401不能清除新会话', async () => {
  let finish!: (value: unknown) => void
  const unauthorized = vi.fn()
  setUnauthorized(unauthorized)
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      headers: new Headers(),
      json: () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    }),
  )
  const result = request('/me', z.object({}))
  await new Promise((resolve) => setTimeout(resolve, 0))
  advanceSession()
  finish({ code: 'unauthorized' })
  await expect(result).rejects.toMatchObject({ name: 'AbortError' })
  expect(unauthorized).not.toHaveBeenCalled()
})

it('当前密码错误不会清除仍有效的会话', async () => {
  const handler = vi.fn()
  setUnauthorized(handler)
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'management_credentials_invalid',
          message: '密码错误',
        }),
        { status: 401 },
      ),
    ),
  )
  await expect(
    request('/auth/password', z.object({}), { method: 'POST', body: {} }),
  ).rejects.toMatchObject({ status: 401 })
  expect(handler).not.toHaveBeenCalled()
})
it('sends multipart bodies unchanged without a JSON content type and keeps CSRF', async () => {
 const data = new FormData(); data.set('metadata', '{"id":"rules"}')
 const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })))
 vi.stubGlobal('fetch', fetcher)
 await request('/business-documents', z.object({ ok: z.boolean() }), { method: 'POST', body: data, csrf: 'csrf-value' })
 const options = fetcher.mock.calls[0][1]
 expect(options.body).toBe(data)
 expect(options.headers['content-type']).toBeUndefined()
 expect(options.headers['x-csrf-token']).toBe('csrf-value')
 expect(options.credentials).toBe('same-origin'); expect(options.cache).toBe('no-store')
})
