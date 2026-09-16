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
