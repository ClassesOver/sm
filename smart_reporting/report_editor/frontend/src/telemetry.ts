export type EditorTelemetryEvent =
  | 'document_loaded'
  | 'save_succeeded'
  | 'save_failed'
  | 'export_succeeded'
  | 'export_failed'

export interface EditorTelemetryPayload {
  event: EditorTelemetryEvent
  durationMs?: number
  format?: 'pdf' | 'word'
  errorCode?: string
}

type TelemetrySender = (payload: EditorTelemetryPayload) => Promise<void>

export function createTelemetryReporter(send: TelemetrySender) {
  return {
    async record(payload: EditorTelemetryPayload): Promise<void> {
      const event: EditorTelemetryPayload = { event: payload.event }
      if (payload.durationMs !== undefined) event.durationMs = payload.durationMs
      if (payload.format !== undefined) event.format = payload.format
      if (payload.errorCode !== undefined) event.errorCode = payload.errorCode
      try {
        await send(event)
      } catch {
        // Telemetry must never interrupt editing, saving, or exporting.
      }
    },
  }
}
