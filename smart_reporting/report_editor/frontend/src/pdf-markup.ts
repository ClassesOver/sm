import type { NativeOperation } from './native-draft'
import { quadSetsMatch } from './genoffice-pdf-annotations'
export type MarkupType = 'highlight' | 'underline' | 'squiggly' | 'strikeout'
export interface MarkupInput { pageIndex: number; type: MarkupType; quads: number[][]; color: [number, number, number] }
export const PDF_MARKUP_TYPES: MarkupType[] = ['highlight', 'underline', 'squiggly', 'strikeout']
export interface SavedPdfMarkup { markupType: MarkupType; quads: number[][]; color: number[]; annotationId?: string; expectedAnnotationSha256?: string; removable?: boolean; removalReason?: string | null }
export interface PdfMarkupSelection { pageId: string; quads: number[][]; saved: SavedPdfMarkup[] }
export function validatePdfMarkup(operation: NativeOperation) {
  if (!PDF_MARKUP_TYPES.includes(operation.markupType as MarkupType) || typeof operation.pageId !== 'string' || !operation.pageId || Object.keys(operation).some(key => !['kind', 'pageId', 'markupType', 'quads', 'color', 'sourceSha256'].includes(key))) throw new Error('文字标注记录无效')
  const quads = operation.quads, color = operation.color
  if (!Array.isArray(color) || color.length !== 3 || !color.every(value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1)) throw new Error('文字标注颜色无效')
  if (!Array.isArray(quads) || !quads.length || quads.length > 200) throw new Error('每页选区最多支持 200 段文字范围')
  for (const q of quads) {
    if (!Array.isArray(q) || q.length !== 8 || !q.every(value => typeof value === 'number' && Number.isFinite(value))) throw new Error('文字标注范围无效')
    const [x1, y2, x2, , , y1] = q
    if (x2 - x1 < .5 || y2 - y1 < .5 || q[3] !== y2 || q[4] !== x1 || q[6] !== x2 || q[7] !== y1) throw new Error('文字标注范围过小或形状暂不支持')
  }
}
export function markupSelectionState(selection: PdfMarkupSelection[], operations: NativeOperation[], type: MarkupType) {
  const matches = selection.map(page => ({ page, pending: operations.findIndex(op => op.pageId === page.pageId && ((op.kind === 'addMarkup' && op.markupType === type && quadSetsMatch(op.quads as number[][], page.quads)) || (type === 'highlight' && op.kind === 'highlight' && Array.isArray(op.rect) && op.rect.length === 4 && quadSetsMatch([[op.rect[0], op.rect[3], op.rect[2], op.rect[3], op.rect[0], op.rect[1], op.rect[2], op.rect[1]]], page.quads)))), saved: page.saved.find(mark => mark.markupType === type && !operations.some(op => op.kind === 'removeMarkup' && op.pageId === page.pageId && op.annotationId === mark.annotationId) && quadSetsMatch(mark.quads, page.quads)) }))
  return { matches, active: matches.length > 0 && matches.every(match => match.pending >= 0 || match.saved), savedOnly: matches.length > 0 && matches.every(match => match.saved && match.pending < 0) }
}
export function togglePdfMarkup(selection: PdfMarkupSelection[], operations: NativeOperation[], type: MarkupType, color: number[]): NativeOperation[] {
  if (!selection.length || !PDF_MARKUP_TYPES.includes(type)) throw new Error('请先选择页面文字')
  for (const page of selection) validatePdfMarkup({ kind: 'addMarkup', pageId: page.pageId, markupType: type, quads: page.quads, color })
  const state = markupSelectionState(selection, operations, type)
  if (state.active) for (const match of state.matches) if (match.pending < 0 && match.saved && (!match.saved.removable || !match.saved.annotationId || !match.saved.expectedAnnotationSha256)) throw new Error(match.saved.removalReason || '已保存的同类标注尚不能移除；原草稿已保留')
  const remove = new Set(state.active ? state.matches.map(match => match.pending) : [])
  const next = structuredClone(operations).filter((_, index) => !remove.has(index))
  if (state.active) for (const match of state.matches) if (match.pending < 0 && match.saved) next.push({ kind: 'removeMarkup', pageId: match.page.pageId, annotationId: match.saved.annotationId, expectedAnnotationSha256: match.saved.expectedAnnotationSha256 })
  if (!state.active) for (const match of state.matches) if (match.pending < 0 && !match.saved) next.push({ kind: 'addMarkup', pageId: match.page.pageId, markupType: type, quads: structuredClone(match.page.quads), color: [...color] })
  if (next.length > 500) throw new Error('文字标注将超过 500 条修改，请先保存')
  return next
}
