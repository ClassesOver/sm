import { validatePdfReplies } from './pdf-replies'
import { validateAttachmentEdits, type PdfAttachmentModel } from './pdf-attachment-edits'
import { validatePendingPdfNote, validatePdfNoteOperation, type SavedPdfNote } from './pdf-notes'
import { validatePdfMarkup, type SavedPdfMarkup } from './pdf-markup'
import type { NativeOperation } from './native-draft'
import type { PDFPageProxy } from 'pdfjs-dist'

export const PDF_PAPER_SIZES = [{ label: 'A3', width: 842, height: 1191 }, { label: 'A4', width: 595, height: 842 }, { label: 'A5', width: 420, height: 595 }, { label: 'Letter', width: 612, height: 792 }, { label: 'Legal', width: 612, height: 1008 }] as const
export function validatePdfSizeOperations(operations: NativeOperation[]) {
  const sizes = operations.filter(op => op.kind === 'setPageSize')
  if (sizes.length > 1 || sizes.some(op => !PDF_PAPER_SIZES.some(paper => paper.label === op.preset)) || (sizes.length && operations.some(op => ['cropPage', 'replaceText', 'replyNote'].includes(op.kind)))) throw new Error('页面尺寸不能重复或与裁切、原位改字、回复混用；请先保存重开')
}
export function setPdfPageSize(operations: NativeOperation[], preset: string): NativeOperation[] {
  validatePdfSizeOperations(operations)
  if (operations.some(op => op.kind === 'setPageSize' && op.preset === preset)) return structuredClone(operations)
  const result = [...structuredClone(operations).filter(op => op.kind !== 'setPageSize'), { kind: 'setPageSize', preset }]
  validatePdfSizeOperations(result)
  if (result.length > 500) throw new Error('页面尺寸变更将超过 500 条修改，请先保存')
  return result
}
export interface PdfBox { x: number; y: number; width: number; height: number }
export interface PdfPageIdentity { pageId: string; index: number; mediaBox: PdfBox; cropBox: PdfBox; rotation: number; textObjects?: PdfTextObject[]; markups?: SavedPdfMarkup[]; markupReadSafe?: boolean; notes?: SavedPdfNote[]; notesReadSafe?: boolean }
export interface PdfFormField { name: string; kind: 'text' | 'checkbox' | 'radio' | 'choice' | 'signature' | 'unsupported'; value: string | boolean | null; options?: string[]; editable: boolean; fieldId: string; expectedFieldSha256: string }
export interface PdfModel extends PdfAttachmentModel { sourceSha256: string; pageCount: number; pages: PdfPageIdentity[]; formFields?: PdfFormField[]; capabilities?: { cropPage?: boolean; selectionMarkup?: boolean; removeMarkup?: boolean; notes?: boolean; noteReplies?: boolean; pageSize?: boolean; pageSizeReason?: string | null } }
export type PdfRect = [number, number, number, number]
export interface PdfViewportInverse { width: number; height: number; convertToPdfPoint(x: number, y: number): number[] }

/** 所有操作引用不可变来源索引；排序后的页面位置永远不能当作来源身份。 */
export function pdfPageState(pages: PdfPageIdentity[], operations: NativeOperation[]): PdfPageIdentity[] {
  validatePdfSizeOperations(operations)
  validateAttachmentEdits(operations)
  validatePdfReplies(pages, operations)
  const byId = new Map(pages.map(page => [page.pageId, { ...page }]))
  const deleted = new Set<string>()
  const removed = new Set<string>()
  let order = pages.map(page => page.pageId)
  for (const operation of operations) {
    if (operation.kind === 'reorderPages') {
      if (!Array.isArray(operation.pageIds) || operation.pageIds.some(id => typeof id !== 'string' || !byId.has(id)) || new Set(operation.pageIds).size !== operation.pageIds.length) throw new Error('页面排序无效')
      order = operation.pageIds as string[]
      continue
    }
    if (['setFormValue', 'setPageSize', 'addAttachment', 'removeAttachment', 'replyNote'].includes(operation.kind)) continue
    const page = byId.get(String(operation.pageId))
    if (!page) throw new Error('页面身份已过期，请重新打开文件')
    if (operation.kind === 'deletePage') deleted.add(page.pageId)
    else if (operation.kind === 'rotatePage') {
      if (![90, 180, 270].includes(Number(operation.delta))) throw new Error('页面旋转无效')
      page.rotation = (page.rotation + Number(operation.delta)) % 360
    } else if (operation.kind === 'cropPage') {
      if (deleted.has(page.pageId)) throw new Error('裁切不能引用已删除页面')
      const rect = validatedPdfCrop(operation.rect, page.cropBox)
      page.cropBox = { x: rect[0], y: rect[1], width: rect[2] - rect[0], height: rect[3] - rect[1] }
    } else if (operation.kind === 'addTextAnnotation') {
      if (deleted.has(page.pageId)) throw new Error('便签不能引用已删除页面')
      validatePendingPdfNote(operation, page)
    } else if (operation.kind === 'editNote' || operation.kind === 'removeNote') {
      if (deleted.has(page.pageId)) throw new Error('便签不能引用已删除页面')
      const note = validatePdfNoteOperation(operation, pages.find(item => item.pageId === page.pageId)!)
      if (removed.has(note.annotationId)) throw new Error('同一便签不能重复编辑或删除')
      removed.add(note.annotationId)
      page.notes = operation.kind === 'removeNote' ? page.notes?.filter(item => item.annotationId !== note.annotationId) : page.notes?.map(item => item.annotationId === note.annotationId ? { ...item, contents: String(operation.contents) } : item)
    } else if (operation.kind === 'removeMarkup') {
      if (deleted.has(page.pageId)) throw new Error('文字标注不能引用已删除页面')
      const source = pages.find(item => item.pageId === page.pageId)!
      const mark = source.markups?.find(item => item.annotationId === operation.annotationId)
      if (Object.keys(operation).some(key => !['kind', 'pageId', 'annotationId', 'expectedAnnotationSha256', 'sourceSha256'].includes(key)) || typeof operation.annotationId !== 'string' || !/^[a-f0-9]{64}$/.test(operation.annotationId) || !source.markupReadSafe || !mark?.removable || mark.expectedAnnotationSha256 !== operation.expectedAnnotationSha256 || removed.has(operation.annotationId)) throw new Error('标注身份已过期或暂不支持移除；原草稿已保留')
      removed.add(operation.annotationId)
      page.markups = page.markups?.filter(item => item.annotationId !== operation.annotationId)
    } else if (operation.kind === 'addMarkup') {
      if (deleted.has(page.pageId)) throw new Error('文字标注不能引用已删除页面')
      validatePdfMarkup(operation)
      for (const q of operation.quads as number[][]) validatedPdfCrop([q[0], q[5], q[2], q[1]], page.cropBox)
    } else if (!['addMarkup', 'highlight', 'addTextAnnotation', 'replaceText'].includes(operation.kind)) throw new Error('不支持的 PDF 操作')
  }
  const remaining = order.filter(id => !deleted.has(id))
  if (remaining.length !== pages.length - deleted.size) throw new Error('页面排序必须包含所有保留页面')
  if (!remaining.length) throw new Error('不能删除全部页面')
  return remaining.map(id => byId.get(id)!)
}


/** Native crop stores unrotated PDF coordinates, never a displayed page index. */
export function validatedPdfCrop(value: unknown, box: PdfBox): PdfRect {
  if (!Array.isArray(value) || value.length !== 4 || !value.every(item => typeof item === 'number' && Number.isFinite(item))) throw new Error('裁切范围无效')
  const [x1, y1, x2, y2] = value
  if (x2 - x1 < .5 || y2 - y1 < .5 || x1 < box.x || y1 < box.y || x2 > box.x + box.width || y2 > box.y + box.height) throw new Error('裁切范围必须在当前页面内，且宽高至少为 0.5 PDF 单位')
  return [x1, y1, x2, y2]
}

/** Reuse PDF.js PageViewport construction for CropBox/UserUnit/rotation transforms. */
export function pdfPageViewport(page: PDFPageProxy, identity: PdfPageIdentity, scale: number) {
  const base = page.getViewport({ scale, rotation: identity.rotation })
  const box = identity.cropBox
  const viewBox = [box.x, box.y, box.x + box.width, box.y + box.height]
  if (viewBox.every((value, index) => value === base.viewBox[index])) return base
  // PDF.js exposes viewport instances through getViewport, but not its class export.
  const Viewport = base.constructor as new (params: { viewBox: number[]; userUnit: number; scale: number; rotation: number }) => typeof base
  return new Viewport({ viewBox, userUnit: page.userUnit, scale, rotation: identity.rotation })
}

export function cropPdfPage(pages: PdfPageIdentity[], operations: NativeOperation[], pageId: string, rect: unknown): NativeOperation[] {
  if (operations.some(op => op.kind === 'setPageSize')) throw new Error('请先保存页面尺寸并重开，再裁切')
  const page = pdfPageState(pages, operations).find(item => item.pageId === pageId)
  if (!page) throw new Error('页面不存在')
  const bounds = validatedPdfCrop(rect, page.cropBox)
  if (bounds.every((value, index) => value === [page.cropBox.x, page.cropBox.y, page.cropBox.x + page.cropBox.width, page.cropBox.y + page.cropBox.height][index])) return structuredClone(operations)
  if (operations.length >= 500) throw new Error('裁切将超过 500 条修改；请先保存当前修改')
  return [...structuredClone(operations), { kind: 'cropPage', pageId, rect: bounds }]
}

/** Prepare every surviving page before committing one NativeDraft history step. */
export async function cropAllPdfPages(pages: PdfPageIdentity[], operations: NativeOperation[], margins: number[], getViewport: (page: PdfPageIdentity) => Promise<PdfViewportInverse>): Promise<NativeOperation[]> {
  const snapshot = structuredClone(operations), selection = [...margins]
  const survivors = pdfPageState(pages, snapshot)
  let result = snapshot
  for (const page of survivors) {
    const viewport = await getViewport(page)
    const rect = pdfCropFromMargins(viewport, page.cropBox, selection)
    result = cropPdfPage(pages, result, page.pageId, rect)
  }
  return result
}

export function pdfCropFromMargins(viewport: PdfViewportInverse, box: PdfBox, margins: number[]): PdfRect {
  if (margins.length !== 4 || !margins.every(value => Number.isFinite(value) && value >= 0 && value < 100)) throw new Error('裁切边距须为 0–100% 之间的数值')
  const [left, top, right, bottom] = margins
  if (left + right >= 100 || top + bottom >= 100) throw new Error('裁切边距不能覆盖整个页面')
  const bounds = { left: 0, top: 0, width: viewport.width, height: viewport.height }
  return validatedPdfCrop(pdfRectFromClient(viewport, bounds, [viewport.width * left / 100, viewport.height * top / 100], [viewport.width * (1 - right / 100), viewport.height * (1 - bottom / 100)], box), box)
}

export function pdfPrintPages(pages: PdfPageIdentity[], operations: NativeOperation[]): PdfPageIdentity[] {
  return pdfPageState(pages, operations)
}

export function pdfCanPrint(state: { loaded: boolean; locked: boolean; dirty: boolean; previewing: boolean; printing: boolean; previewDocument: boolean }): boolean {
  return state.loaded && !state.locked && !state.dirty && !state.previewing && !state.printing && !state.previewDocument
}

export async function renderPdfPrintHost(root: HTMLElement, pages: PdfPageIdentity[], getPage: (sourceIndex: number) => Promise<PDFPageProxy>, annotationMode: number, pixelLimit: number) {
  const host = root.ownerDocument.createElement('div')
  host.className = 'pdf-print-document'
  root.append(host)
  try {
    for (const [index, identity] of pages.entries()) {
      const page = await getPage(identity.index)
      const viewport = page.getViewport({ scale: 1, rotation: identity.rotation })
      const dpr = Math.min(1.5, Math.sqrt(pixelLimit / (viewport.width * viewport.height)))
      const canvas = root.ownerDocument.createElement('canvas')
      canvas.width = Math.max(1, Math.floor(viewport.width * dpr)); canvas.height = Math.max(1, Math.floor(viewport.height * dpr))
      canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`
      const sheet = root.ownerDocument.createElement('section')
      sheet.className = 'pdf-print-page'; sheet.setAttribute('aria-label', `第 ${index + 1} 页`)
      sheet.append(canvas); host.append(sheet)
      await page.render({ canvas, viewport, annotationMode, transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0] }).promise
    }
    return { host, print: (start: () => void) => start(), cleanup: () => host.remove() }
  } catch (error) {
    host.remove()
    throw error
  }
}

function withOrder(operations: NativeOperation[], pageIds: string[]): NativeOperation[] {
  return [...operations.filter(operation => operation.kind !== 'reorderPages'), { kind: 'reorderPages', pageIds }]
}
export function movePdfPage(pages: PdfPageIdentity[], operations: NativeOperation[], pageId: string, direction: -1 | 1): NativeOperation[] {
  const order = pdfPageState(pages, operations).map(page => page.pageId)
  const index = order.indexOf(pageId), destination = index + direction
  if (index < 0 || destination < 0 || destination >= order.length) return structuredClone(operations)
  ;[order[index], order[destination]] = [order[destination], order[index]]
  return withOrder(operations, order)
}
export function reversePdfPages(pages: PdfPageIdentity[], operations: NativeOperation[]): NativeOperation[] {
  const order = pdfPageState(pages, operations).map(page => page.pageId)
  if (order.length <= 1) return structuredClone(operations)
  return withOrder(operations, order.reverse())
}
/** Pinned source rotateAllPages(90): one draft action over surviving source IDs. */
export function rotateAllPdfPages(pages: PdfPageIdentity[], operations: NativeOperation[]): NativeOperation[] {
  const survivors = pdfPageState(pages, operations)
  if (operations.length + survivors.length > 500) throw new Error('旋转全部页面将超过 500 条修改；请先保存当前修改或减少页面后重开')
  return [...structuredClone(operations), ...survivors.map(page => ({ kind: 'rotatePage', pageId: page.pageId, delta: 90 }))]
}
export function deletePdfPage(pages: PdfPageIdentity[], operations: NativeOperation[], pageId: string): NativeOperation[] {
  const order = pdfPageState(pages, operations).map(page => page.pageId)
  if (!order.includes(pageId)) throw new Error('页面不存在')
  if (order.length === 1) throw new Error('不能删除全部页面')
  // 删除同时丢弃该页未保存的标注/旋转；撤销会恢复完整前一个操作快照。
  return withOrder([...operations.filter(operation => operation.pageId !== pageId), { kind: 'deletePage', pageId }], order.filter(id => id !== pageId))
}

/** 使用 PDF.js 的逆变换处理 CropBox、UserUnit、旋转和缩放，避免再次实现页面变换。 */
export function pdfRectFromClient(viewport: PdfViewportInverse, bounds: { left: number; top: number; width: number; height: number }, start: readonly number[], end: readonly number[], crop: PdfBox): PdfRect {
  if (!(bounds.width > 0 && bounds.height > 0)) throw new Error('页面范围无效')
  const point = (value: readonly number[]) => viewport.convertToPdfPoint((value[0] - bounds.left) * viewport.width / bounds.width, (value[1] - bounds.top) * viewport.height / bounds.height)
  const first = point(start), second = point(end)
  const result: PdfRect = [Math.max(crop.x, Math.min(first[0], second[0])), Math.max(crop.y, Math.min(first[1], second[1])), Math.min(crop.x + crop.width, Math.max(first[0], second[0])), Math.min(crop.y + crop.height, Math.max(first[1], second[1]))]
  if (!result.every(Number.isFinite) || result[2] - result[0] < .5 || result[3] - result[1] < .5) throw new Error('请选择页面内的有效范围')
  return result
}
export function stickyNoteRect(point: readonly number[], crop: PdfBox): PdfRect {
  if (crop.width < 20 || crop.height < 18 || !point.every(Number.isFinite)) throw new Error('该页面无法放置文字批注')
  const x = Math.max(crop.x, Math.min(crop.x + crop.width - 20, point[0]))
  const y = Math.max(crop.y + 18, Math.min(crop.y + crop.height, point[1]))
  return [x, y - 18, x + 20, y]
}

export interface PdfTextObject { objectId: string; text: string; rect: PdfRect; expectedTextSha256: string; fontSize: number; fontName: string; fontSha256: string | null }

/** Confirmation belongs to one complete operation snapshot and never survives undo via a changed draft. */
export class PdfPreviewReview {
  private snapshot?: string
  private digest?: string
  private checked = false
  reset() { this.snapshot = undefined; this.digest = undefined; this.checked = false }
  invalidate(operations: NativeOperation[]) { if (this.snapshot !== JSON.stringify(operations)) this.reset() }
  stage(operations: NativeOperation[], digest: string) {
    if (!/^[a-f0-9]{64}$/.test(digest)) throw new Error('PDF 预览摘要无效')
    this.snapshot = JSON.stringify(operations); this.digest = digest; this.checked = false
  }
  isPrepared(operations: NativeOperation[]) { this.invalidate(operations); return !!this.digest }
  confirm(operations: NativeOperation[], checked: boolean) {
    if (!this.isPrepared(operations)) throw new Error('请先生成当前草稿的实际 PDF 预览')
    this.checked = checked
  }
  confirmedDigest(operations: NativeOperation[]): string | undefined {
    return this.isPrepared(operations) && this.checked ? this.digest : undefined
  }
}
