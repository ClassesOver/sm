export interface ReportDocument {
  path: string
  markdown: string
  sha256: string
  csrfToken?: string
  interactiveCharts?: Record<string, string>
}

export interface ExportResult {
  reportId?: string
  revision: number
  requestId?: string
  pdf: { downloadUrl: string; path?: string; size?: number }
  word: { downloadUrl: string; path?: string; size?: number }
  editor?: { openUrl: string }
}

interface ExportJobState {
  exportId: string
  status: 'running' | 'succeeded' | 'failed'
  requestId?: string
  result?: ExportResult
  error?: { code: string; message?: string; status?: number }
}

export interface ReportHistoryItem {
  revision: number
  sha256: string
  markdown?: string
  source?: string
  createdAt?: string | null
  note?: string
}
export interface ReportHistoryPage { items: ReportHistoryItem[]; total: number; hasMore: boolean }

export type SelectionAIAction = 'polish' | 'shorten' | 'expand' | 'professional'

export class ReportEditorApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
  ) {
    super(code)
  }
}

export class ReportEditorClient {
  private csrfToken = ''

  constructor(
    private readonly basePath: string,
    private readonly fetcher: typeof fetch = fetch,
    private readonly exportPollIntervalMs = 2000,
  ) {}

  async load(): Promise<ReportDocument> {
    const document = await this.request<ReportDocument>('/api/document')
    this.csrfToken = document.csrfToken ?? ''
    return document
  }

  async save(markdown: string, expectedSha256: string): Promise<ReportDocument> {
    return this.request<ReportDocument>('/api/document', {
      method: 'PUT',
      body: JSON.stringify({ markdown, expectedSha256 }),
    })
  }

  async historyPage(limit = 20, offset = 0): Promise<ReportHistoryPage> {
    return this.request<ReportHistoryPage>(`/api/history?limit=${limit}&offset=${offset}`)
  }

  async historyRevision(revision: number): Promise<ReportHistoryItem & { markdown: string }> {
    return this.request<ReportHistoryItem & { markdown: string }>(`/api/history/${revision}`)
  }

  async export(
    expectedSha256: string,
    settings: Record<string, boolean> = {},
    note = '',
  ): Promise<ExportResult> {
    const requestId = globalThis.crypto.randomUUID()
    // 渲染与验收可能持续数分钟：服务端立即返回后台任务标识，这里轮询到终态，
    // 避免同步请求被网关读超时切断。
    const started = await this.request<ExportJobState>('/api/export', {
      method: 'POST',
      body: JSON.stringify({ expectedSha256, settings, ...(note ? { note } : {}) }),
      headers: { 'X-Request-ID': requestId },
    })
    const statusPath = `/api/export/${encodeURIComponent(started.exportId)}`
    let transientFailures = 0
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, this.exportPollIntervalMs))
      let state: ExportJobState
      try {
        state = await this.request<ExportJobState>(statusPath)
        transientFailures = 0
      } catch (error) {
        // 短暂断网不应让仍在服务端运行的导出失败；连续失败才放弃。
        if (error instanceof TypeError && ++transientFailures < 5) continue
        throw error
      }
      if (state.status === 'succeeded' && state.result) {
        return { ...state.result, requestId: state.requestId }
      }
      if (state.status === 'failed') {
        throw new ReportEditorApiError(
          state.error?.status ?? 500,
          state.error?.code ?? 'report_editor_export_failed',
          state.requestId,
        )
      }
    }
  }

  async reportEvent(payload: {
    event: string
    durationMs?: number
    format?: 'pdf' | 'word'
    errorCode?: string
  }): Promise<void> {
    const response = await this.fetcher.call(window, `${this.basePath}/api/events`, {
      body: JSON.stringify(payload),
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(this.csrfToken ? { 'X-CSRF-Token': this.csrfToken } : {}),
      },
      method: 'POST',
    })
    if (!response.ok) throw new ReportEditorApiError(response.status, 'report_editor_event_failed')
  }

  async *streamRewrite(
    selection: string,
    action: SelectionAIAction,
    signal: AbortSignal,
  ): AsyncIterable<string> {
    const response = await this.fetcher.call(window, `${this.basePath}/api/ai/rewrite`, {
      body: JSON.stringify({ selection, action }),
      credentials: 'same-origin',
      headers: {
        Accept: 'text/markdown',
        'Content-Type': 'application/json',
        ...(this.csrfToken ? { 'X-CSRF-Token': this.csrfToken } : {}),
      },
      method: 'POST',
      signal,
    })
    if (!response.ok) {
      const payload = await parseErrorBody(response)
      throw new ReportEditorApiError(
        response.status,
        payload.detail?.code ?? 'report_editor_ai_failed',
      )
    }
    if (!response.body) throw new ReportEditorApiError(502, 'report_editor_ai_empty_stream')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value, { stream: true })
      if (chunk) yield chunk
    }
    const remaining = decoder.decode()
    if (remaining) yield remaining
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.fetcher.call(window, `${this.basePath}${path}`, {
      ...init,
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(this.csrfToken ? { 'X-CSRF-Token': this.csrfToken } : {}),
        ...init.headers,
      },
    })
    const payload = (await response.json().catch(() => ({}))) as {
      detail?: { code?: string; requestId?: string }
    }
    if (!response.ok) {
      throw new ReportEditorApiError(
        response.status,
        payload.detail?.code ?? 'report_editor_request_failed',
        payload.detail?.requestId,
      )
    }
    return payload as T
  }
}

async function parseErrorBody(
  response: Response,
): Promise<{ detail?: { code?: string } }> {
  try {
    return (await response.json()) as { detail?: { code?: string } }
  } catch {
    return {}
  }
}
