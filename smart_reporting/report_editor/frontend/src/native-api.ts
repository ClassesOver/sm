import type { NativeDraftIdentity, NativeOperation, NativeSaveRequest } from './native-draft'

export interface NativeFileIdentity { path: string; size: number; sha256: string; mediaType: string }
export interface NativeContext {
  documentId: string
  format: 'docx' | 'pdf' | 'xlsx' | 'pptx'
  revision: number
  parentRevision: number | null
  scope: NativeDraftIdentity['scope']
  sourceFile: NativeFileIdentity
  origin: 'report' | 'upload'
}
export interface NativeContextResponse {
  context: NativeContext
  csrfToken: string
  capabilities: Record<string, unknown>
  editingEnabled: boolean
  aiEnabled?: boolean
  pdfTextEnabled?: boolean
}
export type NativeAISelection = {blockId: string; cellId?: string} | {pageId: string; objectId: string}
type NativeSkippedOperation = {operationIndex: number; kind: string; pageId: string; reason: string}
export interface NativeAIJob {
  editId: string
  status: 'running' | 'succeeded' | 'failed' | 'cancelled'
  snapshotSha256: string
  proposal?: {
    summary: string
    operations: NativeOperation[]
    previewDigest?: string
    skippedOperations?: NativeSkippedOperation[]
    issues?: {code: string; message: string}[]
  }
  error?: { code: string; message: string }
}
export interface NativePreviewRequest { expectedSha256: string; operations: NativeOperation[]; expectedPreviewDigest?: string }
export interface NativePreviewResponse<Model = Record<string, unknown>> {
  sourceSha256: string
  draftSha256: string
  model: Model
  previewDigest?: string
  skippedOperations?: NativeSkippedOperation[]
  appliedOperationIndices?: number[]
}
export interface NativeSaveResponse {
  documentId: string
  revision: number
  parentRevision: number
  revisionRegistered: boolean
  note?: string
  artifacts: Partial<Record<'word' | 'pdf' | 'xlsx' | 'pptx', { downloadUrl?: string; path?: string; size?: number; sha256?: string }>>
  editor?: { openUrl: string } | null
  validation: { ok: boolean; issues: { code: string; message?: string }[] }
}
export class NativeApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) { super(message) }
}

/** 文档路径由可信上下文提供；请求身份不能由可写磁盘路径代替。 */
export function createNativeApi(documentId: string, revision: number, csrfToken?: string) {
  if (!documentId || documentId.length > 256 || /[\x00-\x1f/\\]/.test(documentId) || documentId === '.' || documentId === '..'
    || !Number.isSafeInteger(revision) || revision < 1) throw new Error('原生文档路径无效')
  const base = `/reports/v1/native/${encodeURIComponent(documentId)}/${revision}/api`
  async function request(path: string, payload?: object, signal?: AbortSignal) {
    const headers = new Headers()
    if (payload !== undefined) {
      if (!csrfToken) throw new NativeApiError(403, 'native_csrf_missing', '缺少原生编辑授权，请重新打开文档')
      headers.set('Content-Type', 'application/json')
      headers.set('X-CSRF-Token', csrfToken)
    }
    const response = await fetch(`${base}/${path}`, { method: payload === undefined ? 'GET' : 'POST',
      credentials: 'same-origin', cache: 'no-store', headers, signal,
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }) })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new NativeApiError(response.status, body.detail?.code ?? 'native_request_failed',
        body.detail?.message ?? `请求失败 (${response.status})`)
    }
    return response
  }
  return {
    context: async (signal?: AbortSignal): Promise<NativeContextResponse> => (await request('context', undefined, signal)).json(),
    file: async (signal?: AbortSignal): Promise<ArrayBuffer> => (await request('file', undefined, signal)).arrayBuffer(),
    preview: async <Model = Record<string, unknown>>(payload: NativePreviewRequest, signal?: AbortSignal): Promise<NativePreviewResponse<Model>> => (await request('preview', payload, signal)).json(),
    renderTree: async (payload: NativePreviewRequest, signal?: AbortSignal): Promise<Record<string, unknown>> => (await request('render-tree', payload, signal)).json(),
    previewFile: async (payload: NativePreviewRequest, signal?: AbortSignal): Promise<ArrayBuffer> => {
      const response = await request('preview.pdf', payload, signal)
      if (payload.expectedPreviewDigest && response.headers.get('X-Native-Preview-Digest') !== payload.expectedPreviewDigest) throw new NativeApiError(409, 'native_pdf_text_preview_changed', 'PDF 预览与确认清单不一致，请重新校验修改')
      return response.arrayBuffer()
    },
    save: async (payload: NativeSaveRequest, signal?: AbortSignal): Promise<NativeSaveResponse> => (await request('save', payload, signal)).json(),
    export: async (payload: NativeSaveRequest, signal?: AbortSignal): Promise<NativeSaveResponse> => (await request('export', payload, signal)).json(),
    aiStart: async (payload: NativePreviewRequest & { instruction: string; selection: NativeAISelection[] }, signal?: AbortSignal): Promise<NativeAIJob> => (await request('ai/start', payload, signal)).json(),
    aiStatus: async (id: string, signal?: AbortSignal): Promise<NativeAIJob> => (await request(`ai/${encodeURIComponent(id)}?waitMs=20000`, undefined, signal)).json(),
    aiAccept: async (id: string, payload: NativePreviewRequest & { snapshotSha256: string }, signal?: AbortSignal): Promise<{operations: NativeOperation[]}> => (await request(`ai/${encodeURIComponent(id)}/accept`, payload, signal)).json(),
    aiCancel: async (id: string): Promise<NativeAIJob> => (await request(`ai/${encodeURIComponent(id)}/cancel`, {})).json(),
  }
}

export interface NativeOfficeReadContext {
  operations: NativeOperation[];
  selection: null | { sheetName: string; startRow: number; endRow: number; startColumn: number; endColumn: number } | { slideIndex: number; elementId: string }[];
}
