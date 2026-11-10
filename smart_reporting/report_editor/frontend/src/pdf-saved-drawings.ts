import type { NativeOperation } from './native-draft'
export interface SavedPdfDrawing {
  annotationId: string; expectedAnnotationSha256: string; annotationIndex: number
  subtype: 'Square' | 'Circle' | 'Line' | 'Ink' | 'Polygon' | 'Caret'
  rect: [number, number, number, number]; removable: boolean; removalReason: string | null
}
export interface DrawingPage { pageId: string; drawings?: SavedPdfDrawing[]; drawingsReadSafe?: boolean }
export function validateSavedDrawing(operation: NativeOperation, page: DrawingPage) {
  const drawing = page.drawings?.find(item => item.annotationId === operation.annotationId)
  if (operation.kind !== 'removeDrawing' || operation.pageId !== page.pageId || Object.keys(operation).some(key => !['kind', 'pageId', 'annotationId', 'expectedAnnotationSha256', 'sourceSha256'].includes(key)) || !page.drawingsReadSafe || !drawing?.removable || !/^[a-f0-9]{64}$/.test(String(operation.annotationId)) || drawing.expectedAnnotationSha256 !== operation.expectedAnnotationSha256) throw new Error('绘图身份已过期或暂不支持删除；原草稿已保留')
  return drawing
}
export function toggleSavedDrawing(operations: NativeOperation[], page: DrawingPage, annotationId: string): NativeOperation[] {
  const drawing = page.drawings?.find(item => item.annotationId === annotationId)
  const operation = { kind: 'removeDrawing', pageId: page.pageId, annotationId, expectedAnnotationSha256: drawing?.expectedAnnotationSha256 }
  validateSavedDrawing(operation, page)
  const pending = operations.some(op => op.kind === 'removeDrawing' && op.pageId === page.pageId && op.annotationId === annotationId)
  const next = pending ? operations.filter(op => !(op.kind === 'removeDrawing' && op.pageId === page.pageId && op.annotationId === annotationId)) : [...operations, operation]
  if (next.length > 500) throw new Error('超过 500 条修改，请先保存')
  return structuredClone(next)
}
