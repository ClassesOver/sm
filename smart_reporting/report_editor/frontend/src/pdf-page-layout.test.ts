import { describe, expect, it } from 'vitest'
import { pdfMergePagesOperation, pdfPageState, pdfSplitPagesOperation, validatePdfPageLayout, type PdfPageIdentity } from './pdf-operations'
import { PDF_PAGE_RIBBON_GROUPS } from './pdf-page-ribbon'

const box = { x: 0, y: 0, width: 300, height: 400 }
const pages: PdfPageIdentity[] = [{ pageId: 'p1', index: 0, mediaBox: box, cropBox: box, rotation: 0 }, { pageId: 'p2', index: 1, mediaBox: box, cropBox: box, rotation: 0 }]

describe('PDF merge pages / split pages (pinned mergePagesBytes / splitPagesBytes)', () => {
  it('builds whole-document layout operations and keeps the source page list until previewed', () => {
    expect(pdfMergePagesOperation(4, 'horizontal', true)).toEqual({ kind: 'mergePages', perSheet: 4, direction: 'horizontal', separator: true })
    expect(pdfSplitPagesOperation(9)).toEqual({ kind: 'splitPages', perPage: 9 })
    expect(pdfPageState(pages, [pdfSplitPagesOperation(2)]).map(page => page.pageId)).toEqual(['p1', 'p2'])
    const commands = PDF_PAGE_RIBBON_GROUPS.flatMap(group => group.commands).filter(command => /mergePages|splitPages/.test(command.id))
    expect(commands.every(command => command.enabled)).toBe(true)
  })

  it('rejects invalid options and any other operation in the same save', () => {
    expect(() => pdfMergePagesOperation(1, 'vertical', false)).toThrow('2–16')
    expect(() => pdfMergePagesOperation(17, 'vertical', false)).toThrow('2–16')
    expect(() => pdfMergePagesOperation(2.5, 'vertical', false)).toThrow('2–16')
    expect(() => validatePdfPageLayout({ kind: 'mergePages', perSheet: 2, direction: 'diagonal', separator: false })).toThrow()
    expect(() => pdfSplitPagesOperation(3)).toThrow('2、4 或 9')
    expect(() => validatePdfPageLayout({ kind: 'splitPages', perPage: 2, pageId: 'p1' })).toThrow()
    expect(() => pdfPageState(pages, [pdfSplitPagesOperation(2), { kind: 'rotatePage', pageId: 'p1', delta: 90 }])).toThrow('单独保存')
    expect(() => pdfPageState(pages, [{ kind: 'deletePage', pageId: 'p2' }, pdfMergePagesOperation(2, 'vertical', false)])).toThrow('单独保存')
  })
})
