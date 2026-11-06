import { describe, expect, it } from 'vitest'
import { NativeDraft } from './native-draft'
import { deletePdfPage, movePdfPage, pdfCanPrint, pdfPageState, pdfPrintPages, pdfRectFromClient, renderPdfPrintHost, reversePdfPages, rotateAllPdfPages, PdfPreviewReview, stickyNoteRect } from './pdf-operations'

const pages = [0, 1, 2].map(index => ({ pageId: `source:page:${index}`, index, mediaBox: { x: 0, y: 0, width: 300, height: 400 }, cropBox: { x: 20, y: 30, width: 200, height: 300 }, rotation: index * 90 }))

describe('PDF immutable source operations', () => {
  it('prints exactly the surviving source pages in saved order and rejects dirty or locked print state', () => {
    const operations = movePdfPage(pages, [], pages[2].pageId, -1)
    const withoutFirst = deletePdfPage(pages, operations, pages[0].pageId)
    expect(pdfPrintPages(pages, withoutFirst).map(page => page.index)).toEqual([2, 1])
    expect(pdfCanPrint({ loaded: true, locked: false, dirty: false, previewing: false, printing: false, previewDocument: false })).toBe(true)
    for (const patch of [{ dirty: true }, { locked: true }, { previewing: true }, { printing: true }, { previewDocument: true }, { loaded: false }]) {
      expect(pdfCanPrint({ loaded: true, locked: false, dirty: false, previewing: false, printing: false, previewDocument: false, ...patch })).toBe(false)
    }
  })
  it('renders every print page before invoking the print callback and removes the temporary host on failure', async () => {
    document.body.innerHTML = '<main></main>'
    const root = document.querySelector('main')!
    const requested: number[] = []
    const page = { getViewport: ({ rotation }: {rotation: number}) => ({ width: rotation % 180 ? 400 : 300, height: rotation % 180 ? 300 : 400 }), render: () => ({ promise: Promise.resolve() }) }
    const handle = await renderPdfPrintHost(root, pdfPrintPages(pages, []), async index => { requested.push(index); return page as never }, 2, 48_000_000)
    expect(requested).toEqual([0, 1, 2])
    expect(handle.host.querySelectorAll('.pdf-print-page')).toHaveLength(3)
    let printed = false
    handle.print(() => { expect(handle.host.querySelectorAll('canvas')).toHaveLength(3); printed = true })
    expect(printed).toBe(true)
    handle.cleanup()
    expect(root.querySelector('.pdf-print-document')).toBeNull()
    await expect(renderPdfPrintHost(root, pages, async index => { if (index === 1) throw new Error('page load failed'); return page as never }, 2, 48_000_000)).rejects.toThrow('page load failed')
    expect(root.querySelector('.pdf-print-document')).toBeNull()
  })
  it('keeps source page identities through reorder, rotation and deletion', () => {
    const first = [{ kind: 'rotatePage', pageId: pages[0].pageId, delta: 90 }]
    const moved = movePdfPage(pages, first, pages[2].pageId, -1)
    expect(pdfPageState(pages, moved).map(page => page.pageId)).toEqual([pages[0].pageId, pages[2].pageId, pages[1].pageId])
    expect(pdfPageState(pages, moved)[0].rotation).toBe(90)
    const deleted = deletePdfPage(pages, moved, pages[0].pageId)
    expect(deleted.some(op => op.kind === 'rotatePage')).toBe(false)
    expect(pdfPageState(pages, deleted).map(page => page.pageId)).toEqual([pages[2].pageId, pages[1].pageId])
    expect(deleted.filter(op => op.kind === 'reorderPages')).toHaveLength(1)
    expect(pages[0].rotation).toBe(0)
  })
  it('reverses the current visible page order while retaining source identities and edits', () => {
    const moved = movePdfPage(pages, [], pages[2].pageId, -1)
    const reversed = reversePdfPages(pages, moved)
    expect(pdfPageState(pages, reversed).map(page => page.pageId)).toEqual([pages[1].pageId, pages[2].pageId, pages[0].pageId])
    expect(reversed.filter(operation => operation.kind === 'reorderPages')).toHaveLength(1)
    expect(pdfPageState(pages, reversePdfPages(pages, reversed)).map(page => page.pageId)).toEqual([pages[0].pageId, pages[2].pageId, pages[1].pageId])
  })
  it('reverses only surviving pages and preserves their annotation, rotation and form edits', () => {
    const retained = [
      { kind: 'rotatePage', pageId: pages[2].pageId, delta: 90 },
      { kind: 'addTextAnnotation', pageId: pages[2].pageId, rect: [30, 40, 50, 58], text: '保留批注' },
      { kind: 'setFormValue', name: 'contact.name', fieldKind: 'text', value: 'Lin', fieldId: 'a'.repeat(64), expectedFieldSha256: 'b'.repeat(64) },
    ]
    const deleted = deletePdfPage(pages, retained, pages[1].pageId)
    const reversed = reversePdfPages(pages, deleted)
    expect(pdfPageState(pages, reversed).map(page => page.pageId)).toEqual([pages[2].pageId, pages[0].pageId])
    expect(pdfPageState(pages, reversed)[0].rotation).toBe(270)
    expect(reversed.filter(operation => operation.kind !== 'reorderPages')).toEqual([...retained, { kind: 'deletePage', pageId: pages[1].pageId }])
    expect(reversePdfPages([pages[0]], [])).toEqual([])
  })
  it('rejects deleting the last page and restored stale page identities', () => {
    expect(() => deletePdfPage([pages[0]], [], pages[0].pageId)).toThrow(/全部/)
    expect(() => pdfPageState(pages, [{ kind: 'rotatePage', pageId: 'foreign', delta: 90 }])).toThrow(/页面/)
    expect(() => pdfPageState(pages, [{ kind: 'reorderPages', pageIds: [pages[0].pageId, pages[0].pageId] }])).toThrow(/排序/)
  })
  it.each([0, 90, 180, 270])('converts client rectangles through the PDF.js viewport inverse at %i degrees', rotation => {
    // 非零 CropBox 与缩放：真实 PDF.js viewport 是唯一旋转转换来源。
    const scale = 2
    const point = (x: number, y: number): number[] => {
      const a = x / scale, b = y / scale
      if (rotation === 90) return [20 + b, 30 + a]
      if (rotation === 180) return [220 - a, 30 + b]
      if (rotation === 270) return [220 - b, 330 - a]
      return [20 + a, 330 - b]
    }
    const viewport = { width: rotation % 180 ? 600 : 400, height: rotation % 180 ? 400 : 600, convertToPdfPoint: point }
    const result = pdfRectFromClient(viewport, { left: 100, top: 50, width: viewport.width / 2, height: viewport.height / 2 }, [110, 60], [140, 90], pages[0].cropBox)
    const first = point(20, 20), second = point(80, 80)
    expect(result).toEqual([Math.min(first[0], second[0]), Math.min(first[1], second[1]), Math.max(first[0], second[0]), Math.max(first[1], second[1])])
  })
  it('clips to crop bounds and places the fixed sticky note wholly inside CropBox', () => {
    const box = pages[0].cropBox
    expect(stickyNoteRect([219, 31], box)).toEqual([200, 30, 220, 48])
    expect(() => stickyNoteRect([1, 1], { x: 0, y: 0, width: 10, height: 10 })).toThrow(/批注/)
    expect(() => pdfRectFromClient({ width: 200, height: 300, convertToPdfPoint: (x, y) => [x, y] }, { left: 0, top: 0, width: 200, height: 300 }, [0, 0], [0, 0], box)).toThrow(/范围/)
  })
})

describe('PDF text draft and preview confirmation', () => {
  it('keeps source page operations usable when draft text replacement exists', () => {
    const operations = [{ kind: 'replaceText', pageId: pages[0].pageId, objectId: 'text-object', expectedTextSha256: 'a'.repeat(64), newText: '新金额' }]
    expect(pdfPageState(pages, operations).map(page => page.pageId)).toEqual(pages.map(page => page.pageId))
    expect(deletePdfPage(pages, operations, pages[0].pageId).some(op => op.kind === 'replaceText')).toBe(false)
  })
  it('allows form values that are bound to fields rather than pages', () => {
    const operations = [{ kind: 'setFormValue', fieldId: 'a'.repeat(64), expectedFieldSha256: 'b'.repeat(64), name: 'contact.name', fieldKind: 'text', value: 'Lin' }]
    expect(pdfPageState(pages, operations).map(page => page.pageId)).toEqual(pages.map(page => page.pageId))
  })
  it('requires explicit review and invalidates it across any draft change and undo', async () => {
    const { PdfPreviewReview } = await import('./pdf-operations')
    const review = new PdfPreviewReview()
    const original = [{ kind: 'replaceText', pageId: pages[0].pageId, newText: '已改' }]
    review.stage(original, 'a'.repeat(64))
    expect(review.confirmedDigest(original)).toBeUndefined()
    review.confirm(original, true)
    expect(review.confirmedDigest(original)).toBe('a'.repeat(64))
    const modified = [...original, { kind: 'rotatePage', pageId: pages[0].pageId, delta: 90 }]
    review.invalidate(modified)
    expect(review.confirmedDigest(modified)).toBeUndefined()
    expect(review.confirmedDigest(original)).toBeUndefined()
    expect(() => review.confirm(original, true)).toThrow(/预览/)
    review.stage(original, 'b'.repeat(64))
    review.confirm(original, true)
    review.confirm(original, false)
    expect(review.confirmedDigest(original)).toBeUndefined()
  })
})


describe('fixed-source rotate all surviving pages', () => {
  it('rotates each surviving source identity clockwise once after reorder, deletion and existing rotations', () => {
    const operations = reversePdfPages(pages, [{ kind: 'rotatePage', pageId: pages[1].pageId, delta: 270 }, { kind: 'setFormValue', name: 'field', fieldKind: 'text', value: 'kept', fieldId: 'a'.repeat(64), expectedFieldSha256: 'b'.repeat(64) }])
    const before = deletePdfPage(pages, operations, pages[0].pageId)
    const rotated = rotateAllPdfPages(pages, before)
    expect(rotated.slice(0, before.length)).toEqual(before)
    expect(rotated.slice(before.length)).toEqual([
      { kind: 'rotatePage', pageId: pages[2].pageId, delta: 90 },
      { kind: 'rotatePage', pageId: pages[1].pageId, delta: 90 },
    ])
    expect(pdfPageState(pages, rotated).map(page => [page.index, page.rotation])).toEqual([[2, 270], [1, 90]])
    expect(pdfPageState(pages, before).map(page => [page.index, page.rotation])).toEqual([[2, 180], [1, 0]])
    expect(pages.map(page => page.rotation)).toEqual([0, 90, 180])
  })
  it('retains an atomic operation budget and refuses stale or empty source projections', () => {
    const existing = Array.from({ length: 498 }, () => ({ kind: 'rotatePage', pageId: pages[0].pageId, delta: 90 }))
    expect(() => rotateAllPdfPages(pages, existing)).toThrow(/500/)
    expect(existing).toHaveLength(498)
    expect(rotateAllPdfPages(pages, existing.slice(1))).toHaveLength(500)
    expect(() => rotateAllPdfPages(pages, [{ kind: 'reorderPages', pageIds: ['stale'] }])).toThrow()
    expect(() => rotateAllPdfPages(pages, pages.map(page => ({ kind: 'deletePage', pageId: page.pageId })))).toThrow(/全部页面/)
  })
})

it('commits rotate-all as one NativeDraft history step and invalidates prior text-preview approval', () => {
  const store = new Map<string, string>()
  const storage = { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => { store.set(key, value) }, removeItem: (key: string) => { store.delete(key) } }
  const identity = { documentId: 'rotate-all', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' } }
  const draft = new NativeDraft(identity, storage)
  const before = [{ kind: 'rotatePage', pageId: pages[0].pageId, delta: 270 }]
  draft.setOperations(before)
  const review = new PdfPreviewReview(); review.stage(before, 'b'.repeat(64)); review.confirm(before, true)
  const rotated = rotateAllPdfPages(pages, draft.operations)
  draft.setOperations(rotated)
  expect(review.confirmedDigest(draft.operations)).toBeUndefined()
  draft.undo(); expect(draft.operations).toEqual(before); expect(review.confirmedDigest(draft.operations)).toBeUndefined()
  draft.redo(); expect(draft.operations).toEqual(rotated)
  const restored = new NativeDraft(identity, storage)
  expect(restored.operations).toEqual(rotated)
  expect(pdfPageState(pages, restored.operations).map(page => page.rotation)).toEqual([0, 180, 270])
  draft.setOperations(Array.from({ length: 498 }, () => ({ kind: 'rotatePage', pageId: pages[0].pageId, delta: 90 })))
  const persisted = [...store.entries()]
  expect(() => draft.setOperations(rotateAllPdfPages(pages, draft.operations))).toThrow(/500/)
  expect([...store.entries()]).toEqual(persisted)
})
