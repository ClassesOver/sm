import { expect, it, vi } from 'vitest'
import { NativeDraft, type NativeOperation } from './native-draft'
import { cropAllPdfPages, cropPdfPage, deletePdfPage, pdfPageState, reversePdfPages, PdfPreviewReview, type PdfPageIdentity } from './pdf-operations'

const pages = [
  { pageId: 'source:0', index: 0, rotation: 0, mediaBox: { x: 0, y: 0, width: 400, height: 500 }, cropBox: { x: 10, y: 20, width: 380, height: 460 } },
  { pageId: 'source:1', index: 1, rotation: 90, mediaBox: { x: 0, y: 0, width: 400, height: 500 }, cropBox: { x: 10, y: 20, width: 380, height: 460 } },
  { pageId: 'source:2', index: 2, rotation: 180, mediaBox: { x: 0, y: 0, width: 600, height: 800 }, cropBox: { x: 30, y: 40, width: 540, height: 720 } },
  { pageId: 'source:3', index: 3, rotation: 270, mediaBox: { x: 0, y: 0, width: 250, height: 350 }, cropBox: { x: 5, y: 15, width: 240, height: 320 } },
]
function viewport(page: PdfPageIdentity) {
  const box = page.cropBox, rotation = page.rotation
  return { width: rotation % 180 ? box.height : box.width, height: rotation % 180 ? box.width : box.height, convertToPdfPoint(x: number, y: number) {
    const a = x / this.width, b = y / this.height
    if (rotation === 90) return [box.x + b * box.width, box.y + a * box.height]
    if (rotation === 180) return [box.x + (1 - a) * box.width, box.y + b * box.height]
    if (rotation === 270) return [box.x + (1 - b) * box.width, box.y + (1 - a) * box.height]
    return [box.x + a * box.width, box.y + (1 - b) * box.height]
  } }
}
const getViewport = async (page: PdfPageIdentity) => viewport(page)
const margins = [10, 20, 30, 10]

it('crops only surviving original targets after reorder, rotation and an earlier crop using each current box', async () => {
  const single = cropPdfPage(pages, [], 'source:0', [48, 20, 390, 480])
  const before = reversePdfPages(pages, deletePdfPage(pages, [...single, { kind: 'rotatePage', pageId: 'source:1', delta: 90 }], 'source:2'))
  const read = vi.fn(getViewport)
  const result = await cropAllPdfPages(pages, before, margins, read)
  expect(read.mock.calls.map(([page]) => page.index)).toEqual([3, 1, 0])
  const added = result.slice(before.length)
  expect(added.map(operation => [operation.kind, operation.pageId])).toEqual([['cropPage', 'source:3'], ['cropPage', 'source:1'], ['cropPage', 'source:0']])
  const expected = [[29, 111, 197, 303], [124, 112, 352, 434], [82.2, 66, 287.4, 388]]
  added.forEach((operation, i) => (operation.rect as number[]).forEach((value, j) => expect(value).toBeCloseTo(expected[i][j], 8)))
  expect(pdfPageState(pages, before).map(page => page.cropBox)).toEqual([pages[3].cropBox, pages[1].cropBox, { x: 48, y: 20, width: 342, height: 460 }])
})

it('keeps all input operations intact if a later page fails to load or becomes too small', async () => {
  const before: NativeOperation[] = [{ kind: 'rotatePage', pageId: 'source:0', delta: 90 }]
  const original = structuredClone(before)
  await expect(cropAllPdfPages(pages, before, margins, async page => {
    if (page.index === 3) throw new Error('page unavailable')
    return viewport(page)
  })).rejects.toThrow(/unavailable/)
  const tiny = [...pages.slice(0, 3), { ...pages[3], cropBox: { x: 0, y: 0, width: .6, height: .6 } }]
  await expect(cropAllPdfPages(tiny, before, margins, getViewport)).rejects.toThrow(/有效范围|0.5/)
  expect(before).toEqual(original)
})

it('enforces the complete operation budget without committing the first pages', async () => {
  const before = Array.from({ length: 497 }, () => ({ kind: 'rotatePage', pageId: 'source:0', delta: 90 }))
  await expect(cropAllPdfPages(pages, before, margins, getViewport)).rejects.toThrow(/500/)
  expect(before).toHaveLength(497)
  expect(await cropAllPdfPages(pages, before.slice(1), margins, getViewport)).toHaveLength(500)
})

it('treats full-frame bulk cropping as a no-op even at the operation budget', async () => {
  const before = Array.from({ length: 500 }, () => ({ kind: 'rotatePage', pageId: 'source:0', delta: 90 }))
  expect(await cropAllPdfPages(pages, before, [0, 0, 0, 0], getViewport)).toEqual(before)
})

it('commits one batch history step, reloads and invalidates earlier text preview approval', async () => {
  const values = new Map<string, string>()
  const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
  const identity = { documentId: 'crop-all', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' } }
  const draft = new NativeDraft(identity, storage)
  const review = new PdfPreviewReview(); review.stage([], 'b'.repeat(64)); review.confirm([], true)
  const next = await cropAllPdfPages(pages, [], margins, getViewport)
  draft.setOperations(next); expect(review.confirmedDigest(draft.operations)).toBeUndefined()
  draft.undo(); expect(draft.operations).toEqual([])
  draft.redo(); expect(draft.operations).toEqual(next)
  expect(new NativeDraft(identity, storage).operations).toEqual(next)
})

it('captures operations and margins before asynchronous viewport loading', async () => {
  const operations: NativeOperation[] = [], selection = [...margins]
  const expected = await cropAllPdfPages(pages, [], margins, getViewport)
  const result = cropAllPdfPages(pages, operations, selection, async page => {
    operations.push({ kind: 'rotatePage', pageId: 'source:0', delta: 90 }); selection[0] = 99
    return viewport(page)
  })
  expect(await result).toEqual(expected)
})

it('rejects invalid restored order before loading any viewport', async () => {
  const read = vi.fn(getViewport)
  await expect(cropAllPdfPages(pages, [{ kind: 'reorderPages', pageIds: ['foreign'] }], margins, read)).rejects.toThrow()
  expect(read).not.toHaveBeenCalled()
})

it.each([{ margins: [60, 0, 40, 0] }, { margins: [0, NaN, 0, 0] }, { margins: [-1, 0, 0, 0] }])('rejects invalid bulk margins $margins without changing the draft', async ({ margins }) => {
  const before: NativeOperation[] = []
  await expect(cropAllPdfPages(pages, before, margins, getViewport)).rejects.toThrow()
  expect(before).toEqual([])
})
