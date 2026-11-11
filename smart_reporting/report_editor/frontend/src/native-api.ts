import type {PDFFormAIClient,PDFFormAIJob} from './native-pdf-form-ai'
import { nativeAIProgressListener } from './native-ai-progress'
import type { NativeDraftIdentity, NativeOperation, NativeSaveRequest } from './native-draft'

export interface NativeFileIdentity { path: string; size: number; sha256: string; mediaType: string }
export interface NativeContext {
  documentId: string
  format: 'docx' | 'pdf' | 'xlsx' | 'pptx'
  revision: number
  parentRevision: number | null
  scope: NativeDraftIdentity['scope']
  sourceFile: NativeFileIdentity
  origin: 'report' | 'upload' | 'derived'
}
export interface NativeContextResponse {
  context: NativeContext
  csrfToken: string
  capabilities: Record<string, unknown>
  editingEnabled: boolean
  aiEnabled?: boolean
  wordReadAIEnabled?: boolean
  pdfTextEnabled?: boolean
  pdfReadAIEnabled?: boolean
  pdfReviewAIEnabled?: boolean
  pdfFormAIEnabled?: boolean
}
export type NativeAIReviewSelection = {sourceId: string; targetId: string} | {blockId: string; revisionId: string}
export type NativeAINoteSelection = {selectionKind:'note';noteKind:'footnote'|'endnote';noteId:string} | {selectionKind:'noteAnchor';blockId:string}
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
export type NativePDFReadAction = 'ask' | 'summarize' | 'keyPoints' | 'reviewSummary'
export interface NativePDFReadTask {
  taskId: string
  clientRequestId: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  result?: {
    answer: string
    coverage?: { pageCount?: number; fullyReadPages?: number[]; scopeReadComplete?: boolean; annotationsReadComplete?: boolean }
    citations?: {pageNumber: number | null; pageId: string | null; sourceSha256?: string; originalPageNumber?: number | null; originalPageId?: string | null; effectivePageNumber?: number; effectivePageId?: string; effectiveSha256?: string}[]
    projection?: {
      originalSourceSha256: string
      effectiveSha256: string
      effectiveSize: number
      previewDigest: string
      draftSnapshotSha256: string
      appliedOperationIndices: number[]
      skippedOperations: NativeSkippedOperation[]
      pageMapping: {originalPageNumber: number | null; originalPageId: string | null; effectivePageNumber: number; effectivePageId: string}[]
      selectionMapping: {originalPageId: string; originalObjectId: string; effectivePageId: string; effectiveObjectId: string}[]
    }
    issues?: {code: string; message: string}[]
    toolEvents?: {tool: string}[]
  }
  error?: {code: string; message: string}
}
export interface NativePDFReviewJob {
  editId: string
  clientRequestId: string
  status: 'running' | 'succeeded' | 'failed' | 'cancelled'
  snapshotSha256: string
  proposal?: {
    operations: NativeOperation[]; previewDigest: string
    removedBaseOperationIndices?: number[]
    appliedOperationIndices: number[]; skippedOperations: NativeSkippedOperation[]
    answer: string
    coverage?: {fullyReadPages?: number[]}
    notes: {contents: string; author?: string; pageNumber?: number; status: string; reason: string; operationIndices: number[]; removedBaseOperationIndices?: number[]; reply?: {contents: string; intent: string} | null; replyOmittedReason?: string}[]
    issues?: {code: string; message: string}[]
  }
  error?: {code: string; message: string}
}
export interface NativePDFReviewIssue {
  operationIndex: number
  kind: string
  fieldName: string
  code: string
  message: string
}
export interface NativePreviewRequest { expectedSha256: string; operations: NativeOperation[]; expectedPreviewDigest?: string }
export interface NativePreviewResponse<Model = Record<string, unknown>> {
  sourceSha256: string
  draftSha256: string
  model: Model
  previewDigest?: string
  skippedOperations?: NativeSkippedOperation[]
  appliedOperationIndices?: number[]
  reviewIssues?: NativePDFReviewIssue[]
}
export interface NativeSaveResponse {
  documentId: string
  revision: number
  parentRevision: number | null
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
      ...((path === 'ai/forms/cancel' || path === 'ai/read/cancel' || path === 'ai/review/cancel') ? { keepalive: true } : {}),
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
    readModel: async <Model = Record<string, unknown>>(signal?: AbortSignal): Promise<{sourceSha256: string; model: Model}> => (await request('read-model', undefined, signal)).json(),
    preview: async <Model = Record<string, unknown>>(payload: NativePreviewRequest, signal?: AbortSignal): Promise<NativePreviewResponse<Model>> => (await request('preview', payload, signal)).json(),
    renderTree: async (payload: NativePreviewRequest, signal?: AbortSignal): Promise<Record<string, unknown>> => (await request('render-tree', payload, signal)).json(),
    previewFile: async (payload: NativePreviewRequest, signal?: AbortSignal): Promise<ArrayBuffer> => {
      const response = await request('preview.pdf', payload, signal)
      if (payload.expectedPreviewDigest && response.headers.get('X-Native-Preview-Digest') !== payload.expectedPreviewDigest) throw new NativeApiError(409, 'native_pdf_text_preview_changed', 'PDF 预览与确认清单不一致，请重新校验修改')
      return response.arrayBuffer()
    },
    save: async (payload: NativeSaveRequest, signal?: AbortSignal): Promise<NativeSaveResponse> => (await request('save', payload, signal)).json(),
    extractPages: async (payload: {requestId: string; expectedSha256: string; pages: number[]}, signal?: AbortSignal): Promise<NativeSaveResponse> => (await request('extract-pages', payload, signal)).json(),
    protectPdf: async (payload: import('./pdf-protection').PdfProtectionRequest, signal?: AbortSignal): Promise<NativeSaveResponse> => (await request('protect-pdf',payload,signal)).json(),
    externalPages: async (payload: import('./pdf-external-pages').PdfExternalPagesRequest, signal?: AbortSignal): Promise<NativeSaveResponse> => (await request('external-pages',payload,signal)).json(),
    convertOffice: async (payload: import('./pdf-convert-office').PdfConvertOfficeRequest, signal?: AbortSignal): Promise<import('./pdf-convert-office').PdfConvertOfficeResult> => (await request('convert-office',payload,signal)).json(),
    exportImages: async (payload: import('./pdf-image-export').PdfImageExportRequest, signal?: AbortSignal): Promise<import('./pdf-image-export').PdfImageExportResult> => {
      const response=await request('export-images',payload,signal)
      return {content:await response.arrayBuffer(),sha256:response.headers.get('X-Native-Export-Sha256')??'',size:Number(response.headers.get('X-Native-Export-Size')),sourceSha256:response.headers.get('X-Native-Source-Sha256')??'',filename:'pdf-pages-'+payload.format+'.zip'}
    },
    pdfFormAIStart: async (payload: Parameters<PDFFormAIClient['pdfFormAIStart']>[0], signal?: AbortSignal): Promise<PDFFormAIJob> => (await request('ai/forms/start',payload,signal)).json(),
    pdfFormAIStatus: async (id:string,signal?:AbortSignal): Promise<PDFFormAIJob> => (await request('ai/forms/'+encodeURIComponent(id)+'?waitMs=20000',undefined,signal)).json(),
    pdfFormAIEvents: nativeAIProgressListener(`${base}/ai/forms`),
    pdfFormAIAccept: async (id:string,payload:Parameters<PDFFormAIClient['pdfFormAIAccept']>[1],signal?:AbortSignal):Promise<{operations:NativeOperation[];previewDigest:string}> => (await request('ai/forms/'+encodeURIComponent(id)+'/accept',payload,signal)).json(),
    pdfFormAICancel: async (clientRequestId:string):Promise<unknown> => (await request('ai/forms/cancel',{clientRequestId})).json(),
    pdfReviewStart: async (payload: NativePreviewRequest & {clientRequestId: string; instruction: string}, signal?: AbortSignal): Promise<NativePDFReviewJob> => (await request('ai/review/start', payload, signal)).json(),
    pdfReviewStatus: async (id: string, signal?: AbortSignal): Promise<NativePDFReviewJob> => (await request('ai/review/' + encodeURIComponent(id) + '?waitMs=20000', undefined, signal)).json(),
    pdfReviewEvents: nativeAIProgressListener(`${base}/ai/review`),
    pdfReviewAccept: async (id: string, payload: NativePreviewRequest & {snapshotSha256: string}, signal?: AbortSignal): Promise<{operations: NativeOperation[]; previewDigest: string; appliedOperationIndices: number[]; skippedOperations: NativeSkippedOperation[]}> => (await request('ai/review/' + encodeURIComponent(id) + '/accept', payload, signal)).json(),
    pdfReviewCancel: async (clientRequestId: string): Promise<NativePDFReviewJob> => (await request('ai/review/cancel', {clientRequestId})).json(),
    pdfAIStart: async (payload: NativePreviewRequest & {clientRequestId: string; action: NativePDFReadAction; instruction: string; selection: {pageId: string; objectId: string}[]}, signal?: AbortSignal): Promise<NativePDFReadTask> => (await request('ai/read/start', payload, signal)).json(),
    pdfAIStatus: async (id: string, signal?: AbortSignal): Promise<NativePDFReadTask> => (await request('ai/read/' + encodeURIComponent(id) + '?waitMs=20000', undefined, signal)).json(),
    pdfAIEvents: nativeAIProgressListener(`${base}/ai/read`),
    pdfAICancel: async (clientRequestId: string): Promise<NativePDFReadTask> => (await request('ai/read/cancel', {clientRequestId})).json(),
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
