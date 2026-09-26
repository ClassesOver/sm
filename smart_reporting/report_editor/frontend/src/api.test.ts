import { describe, expect, it, vi } from 'vitest'

import { ReportEditorClient } from './api'

describe('ReportEditorClient', () => {
  it('returns history pagination metadata', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ items: [], total: 41, hasMore: true }), { status: 200 }))
    const client = new ReportEditorClient('/reports/v1/editor/report-1/1', fetcher as typeof fetch)
    await expect(client.historyPage(20, 20)).resolves.toMatchObject({ total: 41, hasMore: true })
    expect(fetcher).toHaveBeenCalledWith(
      '/reports/v1/editor/report-1/1/api/history?limit=20&offset=20',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('loads history markdown only after selecting a revision', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({ revision: 2, markdown: '# 第二版\n', sha256: 'b'.repeat(64) }),
        { status: 200 },
      ),
    )
    const client = new ReportEditorClient('/reports/v1/editor/report-1/1', fetcher)
    await expect(client.historyRevision(2)).resolves.toMatchObject({ revision: 2, markdown: '# 第二版\n' })
    expect(fetcher).toHaveBeenCalledWith(
      '/reports/v1/editor/report-1/1/api/history/2',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('calls a browser fetch implementation with the Window receiver', async () => {
    const browserFetch = vi.fn(function (this: Window) {
      if (this !== window) throw new TypeError('invalid Window receiver')
      return Promise.resolve(
        new Response(
          JSON.stringify({ markdown: '# 报告\n', sha256: 'a'.repeat(64), csrfToken: 'csrf' }),
          { status: 200 },
        ),
      )
    })
    const client = new ReportEditorClient(
      '/reports/v1/editor/report-1/1',
      browserFetch as unknown as typeof fetch,
    )

    await expect(client.load()).resolves.toMatchObject({ markdown: '# 报告\n' })
  })

  it('loads, saves with CAS, and exports the saved revision', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            path: 'reports/revision-1/report.md',
            markdown: '# 报告\n',
            sha256: 'a'.repeat(64),
            csrfToken: 'csrf-token',
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            path: 'reports/revision-1/draft/report.md',
            markdown: '# 修订\n',
            sha256: 'b'.repeat(64),
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ exportId: 'export-1', status: 'running', requestId: 'export-1' }), {
          status: 202,
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ exportId: 'export-1', status: 'running' }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            exportId: 'export-1',
            status: 'succeeded',
            requestId: 'export-1',
            result: {
              revision: 2,
              pdf: { downloadUrl: '/reports/v1/download/pdf' },
              word: { downloadUrl: '/reports/v1/download/word' },
            },
          }),
          { status: 200 },
        ),
      )
    const client = new ReportEditorClient('/reports/v1/editor/report-1/1', fetcher, 0)

    const loaded = await client.load()
    const saved = await client.save('# 修订\n', loaded.sha256)
    const exported = await client.export(saved.sha256)

    expect(saved.sha256).toBe('b'.repeat(64))
    expect(exported.revision).toBe(2)
    expect(exported.requestId).toBe('export-1')
    expect(fetcher).toHaveBeenNthCalledWith(
      5,
      '/reports/v1/editor/report-1/1/api/export/export-1',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      '/reports/v1/editor/report-1/1/api/document',
      expect.objectContaining({
        body: JSON.stringify({
          markdown: '# 修订\n',
          expectedSha256: 'a'.repeat(64),
        }),
        credentials: 'same-origin',
        headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf-token' }),
        method: 'PUT',
      }),
    )
    expect(fetcher).toHaveBeenNthCalledWith(
      3,
      '/reports/v1/editor/report-1/1/api/export',
      expect.objectContaining({
        body: JSON.stringify({ expectedSha256: 'b'.repeat(64), settings: {} }),
        method: 'POST',
      }),
    )
  })

  it('surfaces a CAS conflict without replacing the local document', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: { code: 'report_editor_conflict' } }),
        { status: 409 },
      ),
    )
    const client = new ReportEditorClient('/reports/v1/editor/report-1/1', fetcher)

    await expect(client.save('# 本地内容\n', 'a'.repeat(64))).rejects.toMatchObject({
      code: 'report_editor_conflict',
      status: 409,
    })
  })

  it('falls back to a generic API error when the gateway returns non-JSON', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response('<html>Bad Gateway</html>', {
        status: 502,
        headers: { 'Content-Type': 'text/html' },
      }),
    )
    const client = new ReportEditorClient('/reports/v1/editor/report-1/1', fetcher)

    await expect(client.load()).rejects.toMatchObject({
      code: 'report_editor_request_failed',
      status: 502,
    })
  })

  it('falls back to a generic AI error when the rewrite response is non-JSON', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response('upstream error page', {
        status: 504,
        headers: { 'Content-Type': 'text/plain' },
      }),
    )
    const client = new ReportEditorClient('/reports/v1/editor/report-1/1', fetcher)

    await expect(
      Array.fromAsync(client.streamRewrite('正文', 'polish', new AbortController().signal)),
    ).rejects.toMatchObject({
      code: 'report_editor_ai_failed',
      status: 504,
    })
  })

  it('streams a selection AI rewrite with the current CSRF token', async () => {
    const encoder = new TextEncoder()
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ markdown: '# 报告\n', sha256: 'a'.repeat(64), csrfToken: 'csrf' }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          new ReadableStream({
            start(controller) {
              controller.enqueue(encoder.encode('改写后的'))
              controller.enqueue(encoder.encode('正文'))
              controller.close()
            },
          }),
          { status: 200, headers: { 'Content-Type': 'text/markdown' } },
        ),
      )
    const client = new ReportEditorClient('/reports/v1/editor/report-1/1', fetcher)
    const controller = new AbortController()
    await client.load()

    const chunks = await Array.fromAsync(
      client.streamRewrite('原始正文', 'polish', controller.signal),
    )

    expect(chunks).toEqual(['改写后的', '正文'])
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      '/reports/v1/editor/report-1/1/api/ai/rewrite',
      expect.objectContaining({
        body: JSON.stringify({ selection: '原始正文', action: 'polish' }),
        headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf' }),
        method: 'POST',
        signal: controller.signal,
      }),
    )
  })
  it('surfaces a failed background export with its status and code', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ exportId: 'export-2', status: 'running' }), { status: 202 }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            exportId: 'export-2',
            status: 'failed',
            requestId: 'export-2',
            error: { code: 'report_editor_revision_stale', status: 409 },
          }),
          { status: 200 },
        ),
      )
    const client = new ReportEditorClient('/reports/v1/editor/report-1/1', fetcher, 0)

    await expect(client.export('a'.repeat(64))).rejects.toMatchObject({
      status: 409,
      code: 'report_editor_revision_stale',
      requestId: 'export-2',
    })
  })

  it('keeps polling through a transient network failure', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ exportId: 'export-3', status: 'running' }), { status: 202 }),
      )
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            exportId: 'export-3',
            status: 'succeeded',
            result: { revision: 3, pdf: { downloadUrl: '/pdf' }, word: { downloadUrl: '/word' } },
          }),
          { status: 200 },
        ),
      )
    const client = new ReportEditorClient('/reports/v1/editor/report-1/1', fetcher, 0)

    expect((await client.export('a'.repeat(64))).revision).toBe(3)
  })
})
