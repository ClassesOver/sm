import { describe, expect, it } from 'vitest'
import { insertBlankPdfPage, pdfPageState, pdfRedactionOperation, validatePdfRedaction, type PdfPageIdentity } from './pdf-operations'

const box = { x: 10, y: 20, width: 300, height: 400 }
const pages: PdfPageIdentity[] = [{ pageId: 'p1', index: 0, mediaBox: box, cropBox: box, rotation: 0 }, { pageId: 'p2', index: 1, mediaBox: box, cropBox: box, rotation: 0 }]

describe('PDF secure redaction marks (pinned redaction.ts)', () => {
  it('builds source-space redaction rectangles rounded inward', () => {
    expect(pdfRedactionOperation('p1', [10.004, 20.001, 309.999, 419.996], box)).toEqual({ kind: 'redact', pageId: 'p1', rect: [10.01, 20.01, 309.99, 419.99] })
    const ops = [pdfRedactionOperation('p1', [50, 60, 150, 90], box), pdfRedactionOperation('p2', [50, 60, 150, 90], box)]
    expect(pdfPageState(pages, ops)).toHaveLength(2)
    expect(pdfPageState(pages, [{ kind: 'reorderPages', pageIds: ['p2', 'p1'] }, ...ops]).map(page => page.pageId)).toEqual(['p2', 'p1'])
  })

  it('rejects tiny, out-of-page, extra-field, deleted, blank-page and page-size combinations', () => {
    expect(() => pdfRedactionOperation('p1', [50, 60, 50.5, 90], box)).toThrow()
    expect(() => pdfRedactionOperation('p1', [0, 0, 50, 50], box)).toThrow()
    const valid = pdfRedactionOperation('p1', [50, 60, 150, 90], box)
    expect(() => validatePdfRedaction({ ...valid, color: [0, 0, 0] }, box)).toThrow('涂黑参数无效')
    expect(() => pdfPageState(pages, [{ kind: 'deletePage', pageId: 'p1' }, valid])).toThrow('涂黑不能引用已删除页面')
    expect(() => pdfPageState(pages, [{ kind: 'setPageSize', preset: 'A4' }, valid])).toThrow('页面尺寸')
    const withBlank = insertBlankPdfPage(pages, [], 'p1', () => 'b')
    expect(() => pdfPageState(pages, [...withBlank, { ...valid, pageId: 'blank:b' }])).toThrow('新插入的空白页')
    expect(() => pdfPageState(pages, [{ kind: 'cropPage', pageId: 'p1', rect: [10, 100, 310, 420] }, valid])).toThrow()
    expect(() => pdfPageState(pages, Array.from({ length: 501 }, () => valid))).toThrow('不能超过 500')
  })
})
