import { describe, expect, it, vi } from 'vitest'

import { createTelemetryReporter } from './telemetry'

describe('editor telemetry', () => {
  it('sends only allowlisted operational fields', async () => {
    const send = vi.fn().mockResolvedValue(undefined)
    const reporter = createTelemetryReporter(send)

    await reporter.record({
      event: 'save_failed',
      durationMs: 321,
      errorCode: 'report_editor_conflict',
      markdown: '# 不应发送\n',
      selection: '敏感选区',
    } as never)

    expect(send).toHaveBeenCalledWith({
      event: 'save_failed',
      durationMs: 321,
      errorCode: 'report_editor_conflict',
    })
  })

  it('silently ignores telemetry transport failures', async () => {
    const reporter = createTelemetryReporter(vi.fn().mockRejectedValue(new Error('offline')))
    await expect(reporter.record({ event: 'document_loaded', durationMs: 12 })).resolves.toBeUndefined()
  })
})

it.each([204, 500])('MD export telemetry keeps the actual format and tolerates HTTP %s', async status => {
  const { ReportEditorClient } = await import('./api')
  const { createExportPanel } = await import('./enhancements')
  let payload: unknown
  const fetcher = async (_input: RequestInfo | URL, init?: RequestInit) => {
    payload = JSON.parse(String(init?.body))
    return new Response(null, { status })
  }
  const client = new ReportEditorClient('/editor', fetcher as typeof fetch)
  const reporter = createTelemetryReporter(event => client.reportEvent(event))
  await expect(reporter.record({ event: 'export_succeeded', format: 'md' })).resolves.toBeUndefined()
  expect(payload).toEqual({ event: 'export_succeeded', format: 'md' })
  const panel = createExportPanel()
  panel.show({ revision: 2, md: { downloadUrl: '/md' }, validation: { ok: true, issues: [] } }, 'md', 'md')
  expect(panel.dialog.querySelector<HTMLAnchorElement>('[data-format="md"]')?.getAttribute('href')).toBe('/md')
  expect(panel.dialog.querySelector('#export-title')?.textContent).toBe('MD 导出完成')
  panel.dialog.remove()
})
