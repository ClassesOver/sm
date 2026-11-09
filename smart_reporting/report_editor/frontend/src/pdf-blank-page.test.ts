import { describe, expect, it } from 'vitest'
import { blankPdfBytes, cropAllPdfPages, deletePdfPage, insertBlankPdfPage, movePdfPage, pdfPageState, reversePdfPages, rotateAllPdfPages, PDF_A4_POINTS, PDF_BLANK_PAGE_EDIT_REASON, type PdfPageIdentity } from './pdf-operations'

const page = (pageId: string, index: number, width: number, height: number, rotation = 0): PdfPageIdentity => ({ pageId, index, mediaBox: { x: 0, y: 0, width, height }, cropBox: { x: 0, y: 0, width, height }, rotation })
const pages = [page('p1', 0, 300, 400), page('p2', 1, 500, 250, 90)]
let counter = 0
const id = () => `id-${++counter}`

describe('PDF insert blank page (pinned source insertBlankPage)', () => {
  it('inserts after the current page with that page displayed size and one draft order', () => {
    const next = insertBlankPdfPage(pages, [], 'p1', () => 'one')
    expect(next).toEqual([{ kind: 'insertBlankPage', pageId: 'blank:one', width: 300, height: 400 }, { kind: 'reorderPages', pageIds: ['p1', 'blank:one', 'p2'] }])
    const state = pdfPageState(pages, next)
    expect(state.map(item => [item.pageId, item.index, item.blank ?? false])).toEqual([['p1', 0, false], ['blank:one', 2, true], ['p2', 1, false]])
    // 旋转 90° 的页面按显示尺寸（宽高交换）生成空白页
    const rotated = insertBlankPdfPage(pages, [], 'p2', () => 'two')
    expect(rotated[0]).toMatchObject({ width: 250, height: 500 })
    // 无当前页时插在首页之前，取首页尺寸
    expect(pdfPageState(pages, insertBlankPdfPage(pages, [], null, () => 'head')).map(item => item.pageId)).toEqual(['blank:head', 'p1', 'p2'])
    expect(PDF_A4_POINTS).toEqual({ width: 595.28, height: 841.89 })
  })

  it('indexes blanks after the source pages in insertion order, like engine blankPages', () => {
    let ops = insertBlankPdfPage(pages, [], 'p2', id)
    ops = insertBlankPdfPage(pages, ops, 'p1', id)
    const state = pdfPageState(pages, ops)
    expect(state.filter(item => item.blank).map(item => item.index).sort()).toEqual([2, 3])
    expect(ops.filter(op => op.kind === 'reorderPages')).toHaveLength(1)
  })

  it('moves, reverses, rotates and removes blanks without source deletion', () => {
    let ops = insertBlankPdfPage(pages, [], 'p1', () => 'm')
    ops = movePdfPage(pages, ops, 'blank:m', -1)
    expect(pdfPageState(pages, ops).map(item => item.pageId)).toEqual(['blank:m', 'p1', 'p2'])
    ops = reversePdfPages(pages, ops)
    expect(pdfPageState(pages, ops).map(item => item.pageId)).toEqual(['p2', 'p1', 'blank:m'])
    ops = rotateAllPdfPages(pages, ops)
    expect(pdfPageState(pages, ops).find(item => item.pageId === 'blank:m')!.rotation).toBe(90)
    ops = deletePdfPage(pages, ops, 'blank:m')
    expect(ops.some(op => op.pageId === 'blank:m' || op.kind === 'deletePage')).toBe(false)
    expect(pdfPageState(pages, ops).map(item => item.pageId)).toEqual(['p2', 'p1'])
  })

  it('rejects source-bound edits on unsaved blanks and invalid insertions', async () => {
    const ops = insertBlankPdfPage(pages, [], 'p1', () => 'b')
    expect(() => pdfPageState(pages, [...ops, { kind: 'cropPage', pageId: 'blank:b', rect: [0, 0, 10, 10] }])).toThrow(PDF_BLANK_PAGE_EDIT_REASON)
    expect(() => pdfPageState(pages, [...ops, { kind: 'addTextAnnotation', pageId: 'blank:b', rect: [0, 0, 20, 18], text: 'x' }])).toThrow(PDF_BLANK_PAGE_EDIT_REASON)
    expect(() => pdfPageState(pages, [{ kind: 'insertBlankPage', pageId: 'blank:x', width: 0, height: 10 }])).toThrow('空白页尺寸或身份无效')
    expect(() => pdfPageState(pages, [{ kind: 'insertBlankPage', pageId: 'p9', width: 10, height: 10 }])).toThrow('空白页尺寸或身份无效')
    expect(() => pdfPageState(pages, [ops[0], ops[0]])).toThrow('空白页身份重复')
    expect(() => insertBlankPdfPage(pages, [], 'missing')).toThrow('页面不存在')
    // 全部裁切只作用于来源页
    const cropped = await cropAllPdfPages(pages, ops, [10, 10, 10, 10], async target => ({ width: target.cropBox.width, height: target.cropBox.height, convertToPdfPoint: (x: number, y: number) => [x, target.cropBox.height - y] }))
    expect(cropped.filter(op => op.kind === 'cropPage').map(op => op.pageId)).toEqual(['p1', 'p2'])
  })

  it('renders a draft blank from a minimal valid single-page PDF', () => {
    const text = new TextDecoder().decode(blankPdfBytes(612, 792))
    expect(text.startsWith('%PDF-1.4')).toBe(true)
    expect(text).toContain('/MediaBox [0 0 612 792]')
    const xref = Number(text.match(/startxref\n(\d+)/)![1])
    expect(text.slice(xref, xref + 4)).toBe('xref')
    for (const [index, offset] of [...text.matchAll(/(\d{10}) 00000 n/g)].entries()) expect(text.slice(Number(offset[1])).startsWith(`${index + 1} 0 obj`)).toBe(true)
  })
})
