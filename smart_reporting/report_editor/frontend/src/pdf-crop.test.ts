import { expect, it } from 'vitest'
import { NativeDraft } from './native-draft'
import { cropPdfPage, deletePdfPage, pdfCropFromMargins, pdfPageState, reversePdfPages, validatedPdfCrop, PdfPreviewReview } from './pdf-operations'

const pages = [0, 1, 2].map(index => ({ pageId: `source:${index}`, index, rotation: index * 90, mediaBox: { x: 0, y: 0, width: 400, height: 500 }, cropBox: { x: 10, y: 20, width: 380, height: 460 } }))

it('retains source targets and ordered crop bounds across reorder, repeat crop, rotation and deletion', () => {
  const original = structuredClone(pages)
  const reversed = reversePdfPages(pages, [])
  const first = cropPdfPage(pages, reversed, 'source:0', [20, 30, 380, 470])
  const rotated = [...first, { kind: 'rotatePage', pageId: 'source:0', delta: 90 }]
  const twice = cropPdfPage(pages, rotated, 'source:0', [30, 40, 370, 460])
  const current = pdfPageState(pages, twice)
  expect(current.map(page => page.index)).toEqual([2, 1, 0])
  expect(current[2]).toMatchObject({ cropBox: { x: 30, y: 40, width: 340, height: 420 }, rotation: 90 })
  expect(() => cropPdfPage(pages, twice, 'source:0', [20, 30, 380, 470])).toThrow()
  const deleted = deletePdfPage(pages, twice, 'source:0')
  expect(deleted.some(op => op.kind === 'cropPage')).toBe(false)
  expect(() => cropPdfPage(pages, deleted, 'source:0', [30, 40, 370, 460])).toThrow()
  expect(pages).toEqual(original)
})

it('keeps crop as one NativeDraft history step with reload and review snapshot invalidation', () => {
  const values = new Map<string, string>()
  const store = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
  const identity = { documentId: 'crop-fixture', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' } }
  const draft = new NativeDraft(identity, store)
  const ops = cropPdfPage(pages, [], 'source:1', [20, 30, 380, 470])
  const review = new PdfPreviewReview(); review.stage([], 'b'.repeat(64)); review.confirm([], true)
  draft.setOperations(ops); expect(review.confirmedDigest(draft.operations)).toBeUndefined(); expect(draft.operations).toEqual(ops)
  draft.undo(); expect(draft.operations).toEqual([])
  draft.redo(); expect(draft.operations).toEqual(ops)
  expect(new NativeDraft(identity, store).operations).toEqual(ops)
  expect(cropPdfPage(pages, ops, 'source:1', [20, 30, 380, 470])).toEqual(ops)
})

it('avoids a no-op crop and rejects the operation budget before changing the input', () => {
  expect(cropPdfPage(pages, [], 'source:0', [10, 20, 390, 480])).toEqual([])
  const operations = Array.from({ length: 500 }, () => ({ kind: 'rotatePage', pageId: 'source:0', delta: 90 }))
  expect(() => cropPdfPage(pages, operations, 'source:0', [20, 30, 380, 470])).toThrow(/500/)
  expect(operations).toHaveLength(500)
  expect(() => pdfPageState(pages, [{ kind: 'deletePage', pageId: 'source:0' }, { kind: 'cropPage', pageId: 'source:0', rect: [20, 30, 380, 470] }])).toThrow(/已删除页面/)
  expect(() => pdfPageState(pages, [{ kind: 'cropPage', pageId: 'source:0', rect: [0, 0, 200, 200] }])).toThrow()
})

it.each([0, 90, 180, 270])('uses the supplied inverse viewport for displayed margins at %s degrees', rotation => {
  // Independent expected mapping of 10/20/30/40 percent margins on an offset box.
  const box = { x: 10, y: 20, width: 100, height: 200 }
  const viewport = { width: rotation % 180 ? 400 : 200, height: rotation % 180 ? 200 : 400, convertToPdfPoint(x: number, y: number) {
    const a = x / this.width, b = y / this.height
    if (rotation === 90) return [10 + b * 100, 20 + a * 200]
    if (rotation === 180) return [110 - a * 100, 20 + b * 200]
    if (rotation === 270) return [110 - b * 100, 220 - a * 200]
    return [10 + a * 100, 220 - b * 200]
  } }
  const expected = { 0: [20, 100, 80, 180], 90: [30, 40, 70, 160], 180: [40, 60, 100, 140], 270: [50, 80, 90, 200] }
  expect(pdfCropFromMargins(viewport, box, [10, 20, 30, 40])).toEqual(expected[rotation as keyof typeof expected])
})

it.each([[100, 0, 0, 0], [-1, 0, 0, 0], [60, 0, 40, 0], [0, 80, 0, 20], [0, NaN, 0, 0], [0, 0, 0]].map(margins => ({ margins })))('rejects invalid displayed margins $margins', ({ margins }) => {
  expect(() => pdfCropFromMargins({ width: 100, height: 100, convertToPdfPoint: (x, y) => [x, y] }, pages[0].cropBox, margins)).toThrow()
})

it.each([[10, 20, 30], [10, 20, 390, 481], [10, 20, 10.1, 60], [10, 20, Infinity, 40], ['10', 20, 30, 40]].map(rect => ({ rect })))('rejects malformed/stale stored crop bounds $rect', ({ rect }) => {
  expect(() => validatedPdfCrop(rect, pages[0].cropBox)).toThrow()
})
