export interface ReportDocument {
  path: string
  markdown: string
  sha256: string
  csrfToken?: string
}

export interface ExportResult {
  reportId?: string
  revision: number
  requestId?: string
  pdf: { downloadUrl: string; path?: string; size?: number }
  word: { downloadUrl: string; path?: string; size?: number }
  editor?: { openUrl: string }
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

  async history(limit = 20, offset = 0): Promise<ReportHistoryItem[]> {
    const result = await this.request<{ items: ReportHistoryItem[] }>(
      `/api/history?limit=${limit}&offset=${offset}`,
    )
    return result.items
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
    return this.request<ExportResult>('/api/export', {
      method: 'POST',
      body: JSON.stringify({ expectedSha256, settings, ...(note ? { note } : {}) }),
      headers: { 'X-Request-ID': requestId },
    })
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
      const payload = (await response.json()) as { detail?: { code?: string } }
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
    const payload = (await response.json()) as {
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
