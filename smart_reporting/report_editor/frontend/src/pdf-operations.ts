import type { NativeOperation } from './native-draft'
import type { PDFPageProxy } from 'pdfjs-dist'

export interface PdfBox { x: number; y: number; width: number; height: number }
export interface PdfPageIdentity { pageId: string; index: number; mediaBox: PdfBox; cropBox: PdfBox; rotation: number; textObjects?: PdfTextObject[] }
export interface PdfFormField { name: string; kind: 'text' | 'checkbox' | 'radio' | 'choice' | 'signature' | 'unsupported'; value: string | boolean | null; options?: string[]; editable: boolean; fieldId: string; expectedFieldSha256: string }
export interface PdfModel { sourceSha256: string; pageCount: number; pages: PdfPageIdentity[]; formFields?: PdfFormField[] }
export type PdfRect = [number, number, number, number]
export interface PdfViewportInverse { width: number; height: number; convertToPdfPoint(x: number, y: number): number[] }

/** 所有操作引用不可变来源索引；排序后的页面位置永远不能当作来源身份。 */
export function pdfPageState(pages: PdfPageIdentity[], operations: NativeOperation[]): PdfPageIdentity[] {
  const byId = new Map(pages.map(page => [page.pageId, { ...page }]))
  const deleted = new Set<string>()
  let order = pages.map(page => page.pageId)
  for (const operation of operations) {
    if (operation.kind === 'reorderPages') {
      if (!Array.isArray(operation.pageIds) || operation.pageIds.some(id => typeof id !== 'string' || !byId.has(id)) || new Set(operation.pageIds).size !== operation.pageIds.length) throw new Error('页面排序无效')
      order = operation.pageIds as string[]
      continue
    }
    if (operation.kind === 'setFormValue') continue
    const page = byId.get(String(operation.pageId))
    if (!page) throw new Error('页面身份已过期，请重新打开文件')
    if (operation.kind === 'deletePage') deleted.add(page.pageId)
    else if (operation.kind === 'rotatePage') {
      if (![90, 180, 270].includes(Number(operation.delta))) throw new Error('页面旋转无效')
      page.rotation = (page.rotation + Number(operation.delta)) % 360
    } else if (!['highlight', 'addTextAnnotation', 'replaceText'].includes(operation.kind)) throw new Error('不支持的 PDF 操作')
  }
  const remaining = order.filter(id => !deleted.has(id))
  if (remaining.length !== pages.length - deleted.size) throw new Error('页面排序必须包含所有保留页面')
  if (!remaining.length) throw new Error('不能删除全部页面')
  return remaining.map(id => byId.get(id)!)
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
