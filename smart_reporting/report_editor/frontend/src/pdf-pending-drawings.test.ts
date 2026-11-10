import { describe, expect, it } from 'vitest'
import { NativeDraft, type NativeOperation } from './native-draft'
import { pdfDrawingOperation, pdfPageState, type PdfPageIdentity } from './pdf-operations'
import { movePendingDrawing, pendingDrawingTarget, resizePendingImage, removePendingDrawing } from './pdf-pending-drawings'
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

const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
const image = () => pdfDrawingOperation(page.pageId, 'image', [[40, 60], [100, 140]], box, red, { image: png })
describe('pending image aspect-preserving resize', () => {
  it('resizes only the exact twin record and preserves PNG, style and unrelated operations', () => {
    const operations = [image(), image(), rect()], original = structuredClone(operations)
    const result = resizePendingImage(pages, operations, reference(operations, 1), 1.5, 'bottom-left')
    expect(result).toEqual([original[0], { ...original[1], rect: [40, 60, 130, 180] }, original[2]])
    expect(operations).toEqual(original)
    expect(pendingDrawingTarget(pages, operations, reference(operations, 1)).resizable).toBe(true)
    expect(pendingDrawingTarget(pages, operations, reference(operations, 2)).resizable).toBe(false)
  })
  it('keeps each PDF-space opposite corner fixed and preserves aspect ratio', () => {
    const operations = [image()]
    const expected = { 'bottom-left': [40, 60, 70, 100], 'bottom-right': [70, 60, 100, 100], 'top-left': [40, 100, 70, 140], 'top-right': [70, 100, 100, 140] }
    for (const anchor of ['bottom-left', 'bottom-right', 'top-left', 'top-right'] as const) {
      const resized = resizePendingImage(pages, operations, reference(operations), .5, anchor)[0]!
      expect(resized.rect).toEqual(expected[anchor])
      const [x1,y1,x2,y2] = resized.rect as number[]
      expect((x2!-x1!)/(y2!-y1!)).toBe(.75)
    }
  })
  it('refuses non-images, invalid scales/anchors, small/overflow bounds and stale identities without mutation', () => {
    const operations = [image()], original = structuredClone(operations), ref = reference(operations)
    for (const scale of [0, -1, NaN, Infinity, 1e300, .001, 10]) expect(() => resizePendingImage(pages, operations, ref, scale, 'bottom-left')).toThrow()
    expect(() => resizePendingImage(pages, operations, ref, .5, 'invalid' as 'top-left')).toThrow()
    for (const operation of [rect(), pdfDrawingOperation('p1', 'link', [[40,60],[100,140]], box, red, { destPage: 2 })]) expect(() => resizePendingImage(pages, [operation], reference([operation]), .5, 'top-left')).toThrow('只有待保存图像')
    expect(() => resizePendingImage(pages, [...operations, rect()], ref, .5, 'top-left')).toThrow('列表已变化')
    expect(() => resizePendingImage(pages, operations, { ...ref, pageId: 'p2' }, .5, 'top-left')).toThrow()
    expect(operations).toEqual(original)
    const edgeImage = { ...image(), rect: [350.33, 440.11, 410, 520] }
    const edge = resizePendingImage(pages, [edgeImage], reference([edgeImage]), .37, 'top-right')[0]!.rect as number[]
    expect(edge.slice(2)).toEqual([410, 520])
  })
  it('preserves source identity on rotated/reordered pages and ordinary history/reload', () => {
    const values = new Map<string, string>(), storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key,value) }, removeItem: (key: string) => { values.delete(key) } }
    const draft = new NativeDraft(identity, storage)
    draft.setOperations([image(), { kind: 'rotatePage', pageId: 'p1', delta: 90 }, { kind: 'reorderPages', pageIds: ['p2','p1'] }])
    const before = draft.operations
    draft.setOperations(resizePendingImage(pages, before, reference(before), .5, 'top-right')); const resized = draft.operations
    expect(resized[0].rect).toEqual([70,100,100,140]); expect(resized.slice(1)).toEqual(before.slice(1))
    draft.undo(); expect(draft.operations).toEqual(before); draft.redo(); expect(draft.operations).toEqual(resized)
    expect(new NativeDraft(identity,storage).operations).toEqual(resized)
    expect(resized.every(operation => ['addDrawing','rotatePage','reorderPages'].includes(operation.kind))).toBe(true)
  })
})
