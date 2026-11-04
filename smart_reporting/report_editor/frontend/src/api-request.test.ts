// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { requestJson } from './api-request'

describe('requestJson', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    for (const name of ['report_slides_csrf', 'report_workbook_csrf']) {
      document.cookie = `${name}=; Max-Age=0`
    }
  })

  it('adds the editor CSRF token and reports API errors consistently', async () => {
    document.cookie = 'report_slides_csrf=token%20value'
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({ detail: { message: 'Denied' } }),
      { status: 403, headers: { 'Content-Type': 'application/json' } },
    ))

    await expect(requestJson('/slides/api/edit', {
      method: 'POST',
      body: JSON.stringify({ prompt: 'update' }),
    }, 'report_slides_csrf')).rejects.toThrow('Denied')
    expect(fetchMock).toHaveBeenCalledWith('/slides/api/edit', expect.objectContaining({
      credentials: 'same-origin',
    }))
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(headers.get('X-CSRF-Token')).toBe('token value')
  })

  it('uses the workbook token rather than the slides token for workbook POSTs', async () => {
    document.cookie = 'report_slides_csrf=slides-token'
    document.cookie = 'report_workbook_csrf=workbook-token'
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"revision":2}'))
    const payload = JSON.stringify({ operations: [] })

    await expect(requestJson('/workbooks/api/save', { method: 'POST', body: payload }, 'report_workbook_csrf'))
      .resolves.toEqual({ revision: 2 })
    const init = fetchMock.mock.calls[0][1]!
    expect(init.body).toBe(payload)
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('workbook-token')
  })

  it('omits the CSRF header for GET requests and preserves caller headers', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"status":"succeeded"}'))

    await expect(requestJson('/slides/api/deck', { headers: { 'X-Request-ID': 'request-1' } }, 'report_slides_csrf'))
      .resolves.toEqual({ status: 'succeeded' })
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(headers.has('X-CSRF-Token')).toBe(false)
    expect(headers.get('X-Request-ID')).toBe('request-1')
  })

  it('preserves explicit caller header overrides', async () => {
    document.cookie = 'report_slides_csrf=cookie-token'
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'))

    await requestJson('/slides/api/edit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/custom+json', 'X-CSRF-Token': 'caller-token' },
    }, 'report_slides_csrf')
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
    expect(headers.get('Content-Type')).toBe('application/custom+json')
    expect(headers.get('X-CSRF-Token')).toBe('caller-token')
  })

  it('falls back to the HTTP status when an error body is not JSON', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('Unavailable', { status: 503 }))

    await expect(requestJson('/slides/api/deck')).rejects.toThrow('请求失败 (503)')
  })
})
