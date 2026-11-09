import { afterEach, describe, expect, it, vi } from 'vitest'
import { attachNativeLaunchActions } from './native-launcher'

afterEach(() => { vi.unstubAllGlobals(); document.body.replaceChildren() })
const tick = async () => { await new Promise(resolve => setTimeout(resolve, 0)) }

describe('published native branch launcher', () => {
  it('labels published artifacts explicitly and opens the returned native editor', async () => {
    const container = document.createElement('div')
    document.body.append(container)
    const navigate = vi.fn()
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ editor: { url: '/reports/v1/native/open/grant' } })))
    vi.stubGlobal('fetch', fetcher)
    attachNativeLaunchActions(container, { basePath: '/reports/v1/editor/report/2', csrfToken: 'csrf', formats: ['docx'], navigate, requestId: () => 'request-docx' })
    const button = container.querySelector('button')!
    expect(button.textContent).toBe('编辑已发布 Word')
    button.click()
    await tick()
    expect(fetcher.mock.calls[0][0]).toBe('/reports/v1/editor/report/2/api/native/open')
    const init = fetcher.mock.calls[0][1]
    expect(init.credentials).toBe('same-origin')
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf')
    expect(JSON.parse(init.body)).toEqual({ format: 'docx', requestId: 'request-docx' })
    expect(navigate).toHaveBeenCalledWith('/reports/v1/native/open/grant')
  })

  it('shows a specific failure and retries with the same per-format identity', async () => {
    const container = document.createElement('div')
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: 'native_source_changed', message: '来源文件已变化' } }), { status: 409 }))
      .mockImplementation(async () => new Response(JSON.stringify({ editor: { url: '/reports/v1/native/open/grant' } })))
    vi.stubGlobal('fetch', fetcher)
    let sequence = 0
    const onError = vi.fn()
    attachNativeLaunchActions(container, { basePath: '/reports/v1/editor/report/2', csrfToken: 'csrf', formats: ['docx', 'pdf'], navigate: vi.fn(), onError, requestId: () => `request-${++sequence}` })
    const [word, pdf] = container.querySelectorAll('button')
    word.click(); await tick()
    expect(container.textContent).toContain('来源文件已变化')
    expect(word.disabled).toBe(false)
    word.click(); await tick()
    pdf.click(); await tick()
    expect(JSON.parse(fetcher.mock.calls[0][1].body).requestId).toBe(JSON.parse(fetcher.mock.calls[1][1].body).requestId)
    expect(JSON.parse(fetcher.mock.calls[2][1].body).requestId).not.toBe(JSON.parse(fetcher.mock.calls[1][1].body).requestId)
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'native_source_changed', status: 409 }))
  })

  it('does not request twice while pending or accept an external editor URL', async () => {
    const container = document.createElement('div')
    let done!: (response: Response) => void
    const fetcher = vi.fn().mockImplementation(() => new Promise<Response>(resolve => { done = resolve }))
    vi.stubGlobal('fetch', fetcher)
    const navigate = vi.fn()
    attachNativeLaunchActions(container, { basePath: '/reports/v1/editor/report/2', csrfToken: 'csrf', formats: ['pdf'], navigate })
    const button = container.querySelector('button')!
    button.click(); button.click()
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(button.disabled).toBe(true)
    done(new Response(JSON.stringify({ editor: { url: 'https://external.example/grant' } })))
    await tick()
    expect(navigate).not.toHaveBeenCalled()
    expect(container.textContent).toContain('编辑入口')
  })

  it('does not render unsupported or unavailable formats and supports disposal', () => {
    const container = document.createElement('div')
    const dispose = attachNativeLaunchActions(container, { basePath: '/reports/v1/editor/report/2', csrfToken: 'csrf', formats: [] })
    expect(container.querySelector('button')).toBeNull()
    dispose()
    expect(container.children).toHaveLength(0)
  })
})
