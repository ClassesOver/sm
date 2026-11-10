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
  return { operation, page, movable: movable.has(String(operation.shape)), resizable: operation.shape === 'image' }
}
export function translateDrawingGeometry(operation: NativeOperation, dx: number, dy: number): NativeOperation {
  if (operation.kind !== 'addDrawing' || !movable.has(String(operation.shape)) || !Number.isFinite(dx) || !Number.isFinite(dy)) throw Error('此绘图暂不支持移动或位移无效')
  const result = { ...operation }
  const point = (value: number[]) => [value[0]! + dx, value[1]! + dy]
  switch (result.shape) {
    case 'rect': case 'ellipse': case 'image': {
      const rect = result.rect as number[]
      result.rect = [...point(rect), ...point(rect.slice(2))]; break
    }
    case 'arrow': case 'measure': result.from = point(result.from as number[]); result.to = point(result.to as number[]); break
    case 'ink': result.paths = (result.paths as number[][]).map(path => path.map((value, index) => value + (index % 2 === 0 ? dx : dy))); break
    case 'polygon': result.vertices = (result.vertices as number[][]).map(point); break
    case 'caret': result.point = point(result.point as number[]); break
  }
  return result
}
export function movePendingDrawing(pages: PdfPageIdentity[], operations: NativeOperation[], reference: PendingDrawingReference, dx: number, dy: number): NativeOperation[] {
  const target = pendingDrawingTarget(pages, operations, reference)
  if (!target.movable) throw Error('此类型暂不支持移动')
  if (!Number.isFinite(dx) || !Number.isFinite(dy)) throw Error('位移必须是有限数值')
  const next = structuredClone(operations); next[reference.index] = { ...next[reference.index]! }; const changed = next[reference.index]!
  Object.assign(changed, translateDrawingGeometry(changed, dx, dy))
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

/** Source DrawLayer corner resize preserves aspect ratio around the opposite corner.
 * Web names that fixed corner in unrotated PDF coordinates, not screen coordinates.
 */
export type PendingImageAnchor = 'bottom-left' | 'bottom-right' | 'top-left' | 'top-right'
export function resizePendingImage(pages: PdfPageIdentity[], operations: NativeOperation[], reference: PendingDrawingReference, scale: number, anchor: PendingImageAnchor): NativeOperation[] {
  const target = pendingDrawingTarget(pages, operations, reference)
  if (!target.resizable) throw Error('只有待保存图像可缩放')
  if (!Number.isFinite(scale) || scale <= 0 || !['bottom-left', 'bottom-right', 'top-left', 'top-right'].includes(anchor)) throw Error('缩放比例须为正的有限数值，固定角须有效')
  const [x1, y1, x2, y2] = target.operation.rect as [number, number, number, number]
  const width = (x2 - x1) * scale, height = (y2 - y1) * scale
  const x = anchor.endsWith('left') ? x1 : x2 - width
  const y = anchor.startsWith('bottom') ? y1 : y2 - height
  const next = structuredClone(operations); next[reference.index] = { ...next[reference.index]! }; const changed = next[reference.index]!
  changed.rect = [x, y, anchor.endsWith('left') ? x1 + width : x2, anchor.startsWith('bottom') ? y1 + height : y2]
  validatePdfDrawing(changed, target.page.cropBox)
  pdfPageState(pages, next)
  return next
}
