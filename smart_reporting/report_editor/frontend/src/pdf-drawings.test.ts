import { describe, expect, it } from 'vitest'
import { pdfDrawingOperation, pdfPageState, validatePdfDrawing, insertBlankPdfPage, type PdfPageIdentity } from './pdf-operations'

const box = { x: 10, y: 20, width: 300, height: 400 }
const pages: PdfPageIdentity[] = [{ pageId: 'p1', index: 0, mediaBox: box, cropBox: box, rotation: 0 }]
const red: [number, number, number] = [0.86, 0.15, 0.15]

describe('PDF draw tools (pinned DrawLayer rect/ellipse/arrow/ink)', () => {
  it('normalises drags into source-space drawing operations', () => {
    expect(pdfDrawingOperation('p1', 'rect', [[200, 300], [50, 60]], box, red)).toEqual({ kind: 'addDrawing', pageId: 'p1', shape: 'rect', color: red, width: 2, rect: [50, 60, 200, 300] })
    expect(pdfDrawingOperation('p1', 'ellipse', [[0, 0], [100, 100]], box, red)).toMatchObject({ shape: 'ellipse', rect: [10, 20, 100, 100] })
    expect(pdfDrawingOperation('p1', 'arrow', [[50, 60], [150, 160]], box, red)).toMatchObject({ shape: 'arrow', from: [50, 60], to: [150, 160] })
    expect(pdfDrawingOperation('p1', 'ink', [[50, 60], [60, 70], [999, 80]], box, red)).toMatchObject({ shape: 'ink', paths: [[50, 60, 60, 70, 310, 80]] })
    const ops = [pdfDrawingOperation('p1', 'rect', [[50, 60], [150, 160]], box, red)]
    expect(pdfPageState(pages, ops)).toHaveLength(1)
  })

  it('rejects degenerate shapes, bad colours/widths, extra fields, deleted and blank pages', () => {
    expect(() => pdfDrawingOperation('p1', 'rect', [[50, 60], [50.5, 60.5]], box, red)).toThrow('绘图范围必须在当前页面内')
    expect(() => pdfDrawingOperation('p1', 'arrow', [[50, 60], [50.5, 60.5]], box, red)).toThrow('箭头太短或超出页面')
    expect(() => pdfDrawingOperation('p1', 'ink', [[50, 60]], box, red)).toThrow('手绘路径无效')
    const valid = pdfDrawingOperation('p1', 'rect', [[50, 60], [150, 160]], box, red)
    expect(() => validatePdfDrawing({ ...valid, color: [2, 0, 0] }, box)).toThrow('绘图参数无效')
    expect(() => validatePdfDrawing({ ...valid, width: 0 }, box)).toThrow('绘图参数无效')
    expect(() => validatePdfDrawing({ ...valid, from: [0, 0] }, box)).toThrow('绘图参数无效')
    expect(() => validatePdfDrawing({ ...valid, shape: 'polygon' }, box)).toThrow()
    const two: PdfPageIdentity[] = [...pages, { ...pages[0]!, pageId: 'p2', index: 1 }]
    expect(() => pdfPageState(two, [{ kind: 'deletePage', pageId: 'p1' }, valid])).toThrow('绘图不能引用已删除页面')
    const withBlank = insertBlankPdfPage(pages, [], 'p1', () => 'b')
    expect(() => pdfPageState(pages, [...withBlank, { ...valid, pageId: 'blank:b' }])).toThrow('新插入的空白页')
  })
  it('builds polygon vertices (deduplicated, clamped) and caret points', () => {
    expect(pdfDrawingOperation('p1', 'polygon', [[50, 60], [50.5, 60.5], [150, 60], [100, 160]], box, red)).toMatchObject({ shape: 'polygon', vertices: [[50, 60], [150, 60], [100, 160]] })
    expect(() => pdfDrawingOperation('p1', 'polygon', [[50, 60], [150, 60]], box, red)).toThrow('多边形至少需要 3 个页面内的顶点')
    expect(pdfDrawingOperation('p1', 'caret', [[999, 30]], box, red)).toMatchObject({ shape: 'caret', point: [310, 30] })
    const caret = pdfDrawingOperation('p1', 'caret', [[50, 60]], box, red)
    expect(() => validatePdfDrawing({ ...caret, rect: [0, 0, 1, 1] }, box)).toThrow('绘图参数无效')
  })
  it('builds link operations for safe URLs or existing, non-deleted source pages', () => {
    const two: PdfPageIdentity[] = [...pages, { ...pages[0]!, pageId: 'p2', index: 1 }]
    const url = pdfDrawingOperation('p1', 'link', [[50, 60], [150, 90]], box, red, { url: 'https://example.com' })
    expect(url).toMatchObject({ shape: 'link', rect: [50, 60, 150, 90], url: 'https://example.com' })
    const page = pdfDrawingOperation('p1', 'link', [[50, 60], [150, 90]], box, red, { destPage: 2 })
    expect(pdfPageState(two, [page])).toHaveLength(2)
    expect(() => pdfDrawingOperation('p1', 'link', [[50, 60], [150, 90]], box, red, { url: 'javascript:alert(1)' })).toThrow('链接目标')
    expect(() => pdfDrawingOperation('p1', 'link', [[50, 60], [150, 90]], box, red)).toThrow('链接目标')
    expect(() => validatePdfDrawing({ ...url, destPage: 1 }, box)).toThrow('链接目标')
    expect(() => pdfPageState(two, [{ ...page, destPage: 3 }])).toThrow('链接目标页不存在或已删除')
    expect(() => pdfPageState(two, [{ kind: 'deletePage', pageId: 'p2' }, page])).toThrow('链接目标页不存在或已删除')
  })
})
