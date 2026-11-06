import type { NativeOperation } from './native-draft'
import type { PdfPageIdentity } from './pdf-operations'
export interface SavedPdfNote { annotationId: string; expectedAnnotationSha256: string; contents: string; editable: boolean; removable: boolean; removalReason: string | null }
export function validatePdfNoteOperation(operation: NativeOperation, page: PdfPageIdentity): SavedPdfNote {
  const allowed = ['kind', 'pageId', 'annotationId', 'expectedAnnotationSha256', 'sourceSha256', ...(operation.kind === 'editNote' ? ['contents', 'modifiedAt'] : [])]
  const note = page.notes?.find(note => note.annotationId === operation.annotationId)
  if (!['editNote', 'removeNote'].includes(operation.kind) || Object.keys(operation).some(key => !allowed.includes(key)) || !page.notesReadSafe || !note?.editable || !note.removable || !/^[a-f0-9]{64}$/.test(String(operation.annotationId)) || note.expectedAnnotationSha256 !== operation.expectedAnnotationSha256 || operation.pageId !== page.pageId || (operation.sourceSha256 !== undefined && page.pageId !== `sha256:${operation.sourceSha256}:page:${page.index}`)) throw new Error(note?.removalReason || '便签身份已过期或当前来源只读；原草稿已保留')
  if (operation.kind === 'editNote') {
    if (typeof operation.contents !== 'string' || !operation.contents.trim() || operation.contents.length > 10000 || operation.contents !== operation.contents.trim()) throw new Error('便签正文须为 1–10000 个字符')
    if (typeof operation.modifiedAt !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(operation.modifiedAt) || !Number.isFinite(Date.parse(operation.modifiedAt)) || new Date(operation.modifiedAt).toISOString() !== operation.modifiedAt.replace('Z', '.000Z')) throw new Error('便签修改时间无效')
  }
  return note
}
/** One source note has at most one pending edit/delete; restoring source text drops its edit. */
export function stagePdfNote(pages: PdfPageIdentity[], operations: NativeOperation[], pageId: string, annotationId: string, contents: string | null, modifiedAt = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')): NativeOperation[] {
  const page = pages.find(page => page.pageId === pageId), note = page?.notes?.find(note => note.annotationId === annotationId)
  if (!page || !note || operations.some(op => op.kind === 'deletePage' && op.pageId === pageId)) throw new Error('便签来源页面已过期或已删除')
  const operation = { kind: contents === null ? 'removeNote' : 'editNote', pageId, annotationId, expectedAnnotationSha256: note.expectedAnnotationSha256, ...(contents === null ? {} : { contents: contents.trim(), modifiedAt }) }
  validatePdfNoteOperation(operation, page)
  const next = structuredClone(operations).filter(op => !(op.pageId === pageId && op.annotationId === annotationId && ['editNote', 'removeNote'].includes(op.kind)))
  if (contents === null || contents.trim() !== note.contents) next.push(operation)
  if (next.length > 500) throw new Error('便签修改将超过 500 条操作，请先保存')
  return next
}
