import { describe, expect, it } from 'vitest'
import { buildPdfStampsOperation, deletePdfPage, insertBlankPdfPage, pdfPageState, PDF_STAMPS_STRUCTURE_REASON, type PdfPageIdentity, type PdfStampBuilder } from './pdf-operations'
import { DEFAULT_HEADER_FOOTER, DEFAULT_WATERMARK } from './vendor/genoffice-pdf/renderer/stamps'

const box = (x: number, y: number, width: number, height: number) => ({ x, y, width, height })
const pages: PdfPageIdentity[] = [
  { pageId: 'p1', index: 0, mediaBox: box(0, 0, 400, 500), cropBox: box(10, 20, 380, 460), rotation: 0 },
  { pageId: 'p2', index: 1, mediaBox: box(0, 0, 300, 300), cropBox: box(0, 0, 300, 300), rotation: 90 },
]
// jsdom has no canvas: a deterministic stand-in with the pinned buildStamps contract.
const fake: PdfStampBuilder = (input, watermark, headerFooter) => input.flatMap(page => [
  ...(watermark ? [{ pageIndex: page.origIdx, image: `wm${page.pw}x${page.ph}`, rect: [0, 0, page.pw, page.ph] as [number, number, number, number], opacity: watermark.opacity }] : []),
  ...(headerFooter ? [{ pageIndex: page.origIdx, image: `footer${page.displayNo}`, rect: [0, 10, page.pw, 30] as [number, number, number, number] }] : []),
])
const watermark = { ...DEFAULT_WATERMARK, text: '机密' }

describe('PDF watermark / header-footer (pinned StampDialog → setStamps)', () => {
  it('renders in current page order, deduplicates bitmaps and offsets rects by the crop box', () => {
    const operation = buildPdfStampsOperation(pages, watermark, DEFAULT_HEADER_FOOTER, fake) as any
    expect(operation.kind).toBe('setStamps')
    expect(operation.images).toEqual(['wm380x460', 'footer1', 'wm300x300', 'footer2'])
    expect(operation.stamps[0]).toEqual({ pageId: 'p1', image: 0, rect: [10, 20, 390, 480], opacity: DEFAULT_WATERMARK.opacity })
    expect(operation.stamps[1]).toEqual({ pageId: 'p1', image: 1, rect: [10, 30, 390, 50] })
    expect(pdfPageState(pages, [operation])).toHaveLength(2)
    const shared = buildPdfStampsOperation([pages[0]!, { ...pages[0]!, pageId: 'p3', index: 2 }], watermark, null, fake) as any
    expect(shared.images).toEqual(['wm380x460'])
  })

  it('locks page structure after stamps and requires full coverage', () => {
    const stamps = buildPdfStampsOperation(pages, watermark, null, fake)
    expect(() => deletePdfPage(pages, [stamps], 'p2')).toThrow(PDF_STAMPS_STRUCTURE_REASON)
    expect(() => insertBlankPdfPage(pages, [stamps], 'p1', () => 'x')).toThrow(PDF_STAMPS_STRUCTURE_REASON)
    expect(() => pdfPageState(pages, [stamps, { kind: 'cropPage', pageId: 'p1', rect: [20, 30, 100, 100] }])).toThrow(PDF_STAMPS_STRUCTURE_REASON)
    expect(pdfPageState(pages, [stamps, { kind: 'rotatePage', pageId: 'p1', delta: 90 }])[0]!.rotation).toBe(90)
    const partial = { ...(stamps as any), stamps: (stamps as any).stamps.slice(0, 1) }
    expect(() => pdfPageState(pages, [partial])).toThrow('覆盖全部页面')
    expect(() => pdfPageState(pages, [stamps, stamps])).toThrow('只能设置一次')
    expect(() => buildPdfStampsOperation(pages, { ...watermark, text: ' ' }, null, fake)).toThrow('请填写')
    // 先插入空白页再设置时，空白页同样获得图章
    const withBlank = insertBlankPdfPage(pages, [], 'p1', () => 'b')
    const covered = buildPdfStampsOperation(pdfPageState(pages, withBlank), watermark, null, fake) as any
    expect(covered.stamps.map((stamp: any) => stamp.pageId)).toEqual(['p1', 'blank:b', 'p2'])
    expect(pdfPageState(pages, [...withBlank, covered])).toHaveLength(3)
  })
})
