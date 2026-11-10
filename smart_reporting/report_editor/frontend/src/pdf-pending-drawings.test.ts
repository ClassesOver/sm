import { describe, expect, it } from 'vitest'
import { NativeDraft, type NativeOperation } from './native-draft'
import { pdfDrawingOperation, pdfPageState, type PdfPageIdentity } from './pdf-operations'
import { movePendingDrawing, pendingDrawingTarget, removePendingDrawing } from './pdf-pending-drawings'
const box = { x: 10, y: 20, width: 400, height: 500 }
const page: PdfPageIdentity = { pageId: 'p1', index: 0, mediaBox: box, cropBox: box, rotation: 0 }
const second = { ...page, pageId: 'p2', index: 1 }, pages = [page, second]
const red: [number, number, number] = [.86, .22, .18]
const rect = () => pdfDrawingOperation(page.pageId, 'rect', [[40, 60], [100, 140]], box, red)
const reference = (operations: NativeOperation[], index = 0, pageId = page.pageId) => ({ index, pageId, snapshot: JSON.stringify(operations) })
const identity = { documentId: 'doc', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'db', companyId: 'co', userId: 'u', threadId: 't' } }
describe('pending drawing exact-record edits', () => {
  it('moves only one identical record, preserves unrelated operations and rejects stale shifted indices', () => {
    const operations = [rect(), rect(), { kind: 'rotatePage', pageId: 'p2', delta: 90 }]
    const original = structuredClone(operations), ref = reference(operations, 1)
    const changed = movePendingDrawing(pages, operations, ref, 15, -10)
    expect(changed[0]).toEqual(original[0]); expect(changed[2]).toEqual(original[2])
    expect(changed[1]).toEqual({ ...original[1], rect: [55, 50, 115, 130] })
    expect(operations).toEqual(original)
    const removed = removePendingDrawing(pages, operations, ref)
    expect(removed).toEqual([original[0], original[2]])
    expect(() => movePendingDrawing(pages, removed, ref, 1, 1)).toThrow('列表已变化')
  })
  it('translates every path/vertex/endpoint without changing styles, image payload or measurement label', () => {
    const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
    const shapes: NativeOperation[] = [
      rect(), pdfDrawingOperation('p1', 'ellipse', [[40, 60], [100, 140]], box, red),
      pdfDrawingOperation('p1', 'arrow', [[40, 60], [100, 140]], box, red),
      pdfDrawingOperation('p1', 'measure', [[40, 60], [100, 140]], box, red, { label: '10 cm' }),
      { kind: 'addDrawing', pageId: 'p1', shape: 'ink', paths: [[40, 60, 100, 140], [50, 70, 110, 150]], color: red, width: 1.6 },
      pdfDrawingOperation('p1', 'polygon', [[40, 60], [100, 60], [100, 140]], box, red),
      pdfDrawingOperation('p1', 'caret', [[40, 60]], box, red),
      pdfDrawingOperation('p1', 'image', [[40, 60], [100, 140]], box, red, { image: png }),
    ]
    for (const original of shapes) {
      const moved = movePendingDrawing(pages, [original], reference([original]), 10, 20)[0]!
      expect(moved.color).toEqual(original.color); expect(moved.width).toEqual(original.width)
      if (original.rect) expect(moved.rect).toEqual([50, 80, 110, 160])
      if (original.from) { expect(moved.from).toEqual([50, 80]); expect(moved.to).toEqual([110, 160]) }
      if (original.paths) expect(moved.paths).toEqual([[50, 80, 110, 160], [60, 90, 120, 170]])
      if (original.vertices) expect(moved.vertices).toEqual([[50, 80], [110, 80], [110, 160]])
      if (original.point) expect(moved.point).toEqual([50, 80])
      expect(moved.label).toEqual(original.label); expect(moved.image).toEqual(original.image)
    }
  })
  it('keeps PDF-space coordinates through rotation/reorder and permits deletion but not movement of links', () => {
    const operations = [{ kind: 'rotatePage', pageId: 'p1', delta: 90 }, rect(), { kind: 'reorderPages', pageIds: ['p2', 'p1'] }]
    const changed = movePendingDrawing(pages, operations, reference(operations, 1), 10, 20)
    expect(changed[1].rect).toEqual([50, 80, 110, 160]); expect(pdfPageState(pages, changed).map(page => [page.pageId, page.rotation])).toEqual([['p2', 0], ['p1', 90]])
    const link = pdfDrawingOperation('p1', 'link', [[40, 60], [100, 140]], box, red, { destPage: 2 })
    expect(pendingDrawingTarget(pages, [link], reference([link])).movable).toBe(false)
    expect(() => movePendingDrawing(pages, [link], reference([link]), 10, 20)).toThrow('暂不支持移动')
    expect(removePendingDrawing(pages, [link], reference([link]))).toEqual([])
  })
  it('rejects nonfinite/out-of-page moves, foreign/saved/blank/deleted records and malformed references without mutation', () => {
    const operations = [rect()], original = structuredClone(operations)
    for (const [dx, dy] of [[Infinity, 0], [0, NaN], [1e300, 0], [-31, 0], [0, -41]]) expect(() => movePendingDrawing(pages, operations, reference(operations), dx!, dy!)).toThrow()
    for (const ref of [{ ...reference(operations), index: -1 }, { ...reference(operations), index: .5 }, { ...reference(operations), index: 2 }, reference(operations, 0, 'p2'), reference(operations, 0, 'foreign')]) expect(() => removePendingDrawing(pages, operations, ref)).toThrow()
    const saved = [{ kind: 'removeDrawing', pageId: 'p1' }]
    expect(() => removePendingDrawing(pages, saved, reference(saved))).toThrow()
    const deleted = [{ kind: 'deletePage', pageId: 'p1' }, rect()]
    expect(() => removePendingDrawing(pages, deleted, reference(deleted, 1))).toThrow()
    expect(() => movePendingDrawing([{ ...page, blank: true }], operations, reference(operations), 1, 1)).toThrow()
    expect(operations).toEqual(original)
  })
  it('uses ordinary draft history and scoped restoration without adding engine operations', () => {
    const values = new Map<string, string>(), storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
    const draft = new NativeDraft(identity, storage); draft.setOperations([rect(), rect()])
    const original = draft.operations
    draft.setOperations(movePendingDrawing(pages, original, reference(original, 1), 10, 20)); const moved = draft.operations
    draft.undo(); expect(draft.operations).toEqual(original); draft.redo(); expect(draft.operations).toEqual(moved)
    const restored = new NativeDraft(identity, storage); expect(restored.operations).toEqual(moved)
    restored.setOperations(removePendingDrawing(pages, restored.operations, reference(restored.operations, 0)))
    expect(restored.operations).toEqual([moved[1]]); restored.undo(); expect(restored.operations).toEqual(moved)
    expect(restored.operations.every(operation => operation.kind === 'addDrawing')).toBe(true)
  })
})
