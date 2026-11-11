import { afterEach, expect, it, vi } from 'vitest'
import { createNativeApi } from './native-api'
afterEach(() => vi.unstubAllGlobals())
it('binds extraction to the immutable native route, CSRF and ordered 1-based page selection', async () => {
  const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ documentId: 'child' })))
  vi.stubGlobal('fetch', fetcher)
  const payload = { requestId: 'extract-1', expectedSha256: 'a'.repeat(64), pages: [3, 1] }
  expect(await createNativeApi('doc name', 4, 'csrf').extractPages(payload)).toEqual({ documentId: 'child' })
  expect(fetcher.mock.calls[0]![0]).toBe('/reports/v1/native/doc%20name/4/api/extract-pages')
  const init = fetcher.mock.calls[0]![1]!
  expect(init.method).toBe('POST'); expect(init.credentials).toBe('same-origin')
  expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf')
  expect(JSON.parse(init.body as string)).toEqual(payload)
})
