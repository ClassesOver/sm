import type { NativeOperation } from './native-draft'
import { pdfPageState, validatePdfDrawing, type PdfPageIdentity } from './pdf-operations'

/** Web references are scoped to the complete draft, not geometry or a displayed page index. */
export interface PendingDrawingReference { index: number; snapshot: string; pageId: string }
const movable = new Set(['rect', 'ellipse', 'image', 'arrow', 'measure', 'ink', 'polygon', 'caret'])
export function pendingDrawingTarget(pages: PdfPageIdentity[], operations: NativeOperation[], reference: PendingDrawingReference) {
  if (reference.snapshot !== JSON.stringify(operations) || !Number.isInteger(reference.index) || reference.index < 0) throw Error('绘图列表已变化，请重新选择')
  const operation = operations[reference.index]
  const page = pages.find(item => item.pageId === reference.pageId)
  if (!page || page.blank || !operation || operation.kind !== 'addDrawing' || operation.pageId !== reference.pageId || !pdfPageState(pages, operations).some(item => item.pageId === page.pageId)) throw Error('待保存绘图来源无效，请重新选择')
  validatePdfDrawing(operation, page.cropBox)
  return { operation, page, movable: movable.has(String(operation.shape)) }
}
export function movePendingDrawing(pages: PdfPageIdentity[], operations: NativeOperation[], reference: PendingDrawingReference, dx: number, dy: number): NativeOperation[] {
  const target = pendingDrawingTarget(pages, operations, reference)
  if (!target.movable) throw Error('此类型暂不支持移动')
  if (!Number.isFinite(dx) || !Number.isFinite(dy)) throw Error('位移必须是有限数值')
  const next = structuredClone(operations), changed = next[reference.index]!
  const point = (value: number[]) => [value[0]! + dx, value[1]! + dy]
  switch (changed.shape) {
    case 'rect': case 'ellipse': case 'image': {
      const rect = changed.rect as number[]
      changed.rect = [...point(rect), ...point(rect.slice(2))]; break
    }
    case 'arrow': case 'measure': changed.from = point(changed.from as number[]); changed.to = point(changed.to as number[]); break
    case 'ink': changed.paths = (changed.paths as number[][]).map(path => path.map((value, index) => value + (index % 2 === 0 ? dx : dy))); break
    case 'polygon': changed.vertices = (changed.vertices as number[][]).map(point); break
    case 'caret': changed.point = point(changed.point as number[]); break
  }
  // Reject an out-of-page translation instead of clamping and distorting its shape.
  validatePdfDrawing(changed, target.page.cropBox)
  pdfPageState(pages, next)
  return next
}
export function removePendingDrawing(pages: PdfPageIdentity[], operations: NativeOperation[], reference: PendingDrawingReference): NativeOperation[] {
  pendingDrawingTarget(pages, operations, reference)
  const next = operations.filter((_, index) => index !== reference.index)
  pdfPageState(pages, next)
  return structuredClone(next)
}
