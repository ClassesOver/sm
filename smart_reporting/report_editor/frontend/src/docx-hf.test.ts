import { describe, expect, it } from 'vitest'
import { PAGE_MARK, TOTAL_PAGES_MARK } from '@genoffice/docx-engine'
import { docxHeaderFooterOperation, docxHfDisplayText, docxHfHasPageField, docxHfTextOf, docxHfValueOf, docxHfValueText, mergeDocxHeaderFooterOperation, restoredDocxHeaderFooterOperations, type DocxHeadersFootersModel, type DocxHfPartAnchor } from './docx-hf'

const anchor = { sectionId: 'section-1', expectedSectionSha256: 'sect-sha' }
const partAnchor: DocxHfPartAnchor = { rId: 'rId9', expectedPartSha256: 'part-sha', text: '原页眉', hasPageNumber: false, editable: true }
const model: DocxHeadersFootersModel = {
  titlePg: true, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null,
  parts: { 'header.default': partAnchor, 'footer.default': { ...partAnchor, expectedPartSha256: 'footer-sha', hasPageNumber: true } },
}

describe('header/footer part operations', () => {
  it('extracts editable text paragraphs only and keeps field marks', () => {
    const value = docxHfValueOf({ text: `第${PAGE_MARK}页`, paras: [
      { runs: [{ text: `页眉${PAGE_MARK}` }] },
      { cells: [{ paras: [[{ text: '表格内文本' }]] }], runs: [] },
      { boxAnchored: true, runs: [{ text: '浮动框' }] },
      { runs: [{ text: '第二行' }] },
    ], hasPageNumber: true })
    expect(docxHfTextOf(value)).toBe(`页眉${PAGE_MARK}\n第二行`)
    expect(docxHfHasPageField(value)).toBe(true)
  })

  it('emits a strict anchored operation and skips no-change commits', () => {
    const changed = docxHeaderFooterOperation(anchor, partAnchor, 'header', 'default', { text: '新页眉' })
    expect(changed).toEqual({ kind: 'setHeaderFooter', sectionId: 'section-1', expectedSectionSha256: 'sect-sha',
      part: 'header', variant: 'default', expectedPartSha256: 'part-sha', text: '新页眉', pageNumber: false })
    expect(docxHeaderFooterOperation(anchor, partAnchor, 'header', 'default', { text: '原页眉' })).toBeNull()
    const flagged = docxHeaderFooterOperation(anchor, partAnchor, 'header', 'default', { text: '原页眉' }, { titlePg: false })
    expect(flagged).toMatchObject({ titlePg: false })
  })

  it('persists a page-number position that differs from the source alignment', () => {
    const centered = [{ align: 'center' as const, runs: [{ text: PAGE_MARK }] }]
    const pageAnchor = { ...partAnchor, text: PAGE_MARK, hasPageNumber: true }
    const left = docxHeaderFooterOperation(anchor, pageAnchor, 'footer', 'default',
      { text: PAGE_MARK, pageNumber: true, paras: [{ align: 'left', runs: [{ text: PAGE_MARK }] }] }, undefined, centered)
    // 仅对齐变化也必须产生操作并携带 align，否则保存端沿用来源居中。
    expect(left).toMatchObject({ text: PAGE_MARK, pageNumber: true, align: 'left' })
    expect(docxHeaderFooterOperation(anchor, pageAnchor, 'footer', 'default',
      { text: PAGE_MARK, pageNumber: true, paras: [{ align: 'center', runs: [{ text: PAGE_MARK }] }] }, undefined, centered)).toBeNull()
    // 混合对齐不压平：未统一的段落不写 align。
    const mixed = docxHeaderFooterOperation(anchor, partAnchor, 'header', 'default',
      { text: '甲\n乙', paras: [{ align: 'left', runs: [{ text: '甲' }] }, { align: 'right', runs: [{ text: '乙' }] }] }, undefined, centered)
    expect(mixed).not.toHaveProperty('align')
  })

  it('merges edits per part+variant and preserves other draft operations', () => {
    const first = { kind: 'setHeaderFooter', sectionId: 'section-1', expectedSectionSha256: 'sect-sha', part: 'header', variant: 'default', expectedPartSha256: 'part-sha', text: '一版', pageNumber: false }
    const body = { kind: 'replaceParagraph', blockId: 'a', expectedObjectSha256: 'hash-a', text: '正文' }
    const second = { ...first, text: '二版' }
    const merged = mergeDocxHeaderFooterOperation([body, first], second)
    expect(merged).toEqual([body, second])
  })

  it('restores persisted header/footer drafts and collapses duplicates', () => {
    const first = { kind: 'setHeaderFooter', sectionId: 'section-1', expectedSectionSha256: 'sect-sha', part: 'header', variant: 'default', expectedPartSha256: 'part-sha', text: '一版', pageNumber: false }
    const footer = { kind: 'setHeaderFooter', sectionId: 'section-1', expectedSectionSha256: 'sect-sha', part: 'footer', variant: 'default', expectedPartSha256: 'footer-sha', text: '页脚', pageNumber: true }
    const second = { ...first, text: '二版' }
    expect(restoredDocxHeaderFooterOperations([first, footer, second], anchor, model)).toEqual([footer, second])
  })

  it('rejects restored drafts from a foreign source or forged part identity and preserves the draft', () => {
    const operation = { kind: 'setHeaderFooter', sectionId: 'foreign', expectedSectionSha256: 'sect-sha', part: 'header', variant: 'default', expectedPartSha256: 'part-sha', text: '页眉', pageNumber: false }
    expect(() => restoredDocxHeaderFooterOperations([operation], anchor, model)).toThrow(/节身份/)
    expect(() => restoredDocxHeaderFooterOperations([{ ...operation, sectionId: 'section-1', expectedPartSha256: 'stale' }], anchor, model)).toThrow(/部件身份/)
    expect(() => restoredDocxHeaderFooterOperations([{ ...operation, sectionId: 'section-1', part: 'sidebar', expectedPartSha256: 'part-sha' }], anchor, model)).toThrow(/部件无效/)
    expect(() => restoredDocxHeaderFooterOperations([{ ...operation, sectionId: 'section-1', unexpected: 1 }], anchor, model)).toThrow(/字段无效/)
  })

  it('maps field marks to readable placeholders and back', () => {
    const text = `第${PAGE_MARK}页，共${TOTAL_PAGES_MARK}页`
    const display = docxHfDisplayText(text)
    expect(display).not.toMatch(/[\uE000\uE001\uE002]/)
    expect(docxHfValueText(display)).toBe(text)
  })
})
