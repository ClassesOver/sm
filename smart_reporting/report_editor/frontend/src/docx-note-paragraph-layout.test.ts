import { expect, it } from 'vitest'
import { noteParagraphLayout } from './docx-note-paragraph-layout'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import type { DocxNotesModel } from './docx-notes'

const anchor: DocxAnchor = { docxIndex: 0, blockId: 'notes-only', expectedObjectSha256: 'source-sha', editable: false }
const model: DocxNotesModel = { footnotes: [], endnotes: [], referenceBlocks: [{ blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, editable: true }] }
const source: DocxPmNode = { type: 'docParagraph', attrs: { docxIndex: 0, keepNext: true, tabStops: [{ val: 'left', pos: 720 }] }, content: [
  { type: 'text', text: 'A😀', marks: [{ type: 'docTextStyle', attrs: { rawRPr: '<w:rPr><w:noProof/></w:rPr>' } }] },
  { type: 'docNoteRef', attrs: { kind: 'footnote', id: '1', num: 1, rawRPr: null } },
] }
it.each([
  [{ align: 'center' }, 'setParagraphAlignment'],
  [{ indentLeft: 720 }, 'setParagraphIndent'],
  [{ indentRight: -120 }, 'setParagraphRightIndent'],
  [{ spaceBefore: 240, spaceAfter: 120 }, 'setParagraphSpacing'],
  [{ lineSpacing: 1.5 }, 'setParagraphSpacing'],
] as const)('仅复用布局校验%s，不放开notes来源正文可编辑性', (attrs, kind) => {
  const live = { ...structuredClone(source), attrs: { ...source.attrs, ...attrs } }
  live.content!.unshift({ type: 'text', text: '新文字' })
  const result = noteParagraphLayout(source, live, anchor, model)
  expect(result.operations.map(op => op.kind)).toEqual([kind])
  expect(result.paragraph.content).toEqual(live.content)
  expect(result.paragraph.attrs).toEqual(source.attrs)
  expect(anchor.editable).toBe(false)
  expect(source.content![0].marks![0].attrs!.rawRPr).toContain('noProof')
})
it.each([
  { attrs: { ...source.attrs, docxIndex: 9 } },
  { attrs: { ...source.attrs, keepNext: false } },
  { attrs: { ...source.attrs, styleId: 'foreign' } },
  { attrs: { ...source.attrs, shadingFill: 'FF0000', shadingClear: false } },
  { attrs: { ...source.attrs, pageBreakBefore: true } },
  { type: 'docHeading' },
])('拒绝非布局或段落身份变化%s', patch => {
  expect(() => noteParagraphLayout(source, { ...structuredClone(source), ...patch }, anchor, model)).toThrow()
})
it('拒绝过期notes能力身份', () => {
  expect(() => noteParagraphLayout(source, source, anchor, { ...model, referenceBlocks: [{ ...model.referenceBlocks![0], expectedObjectSha256: 'foreign' }] })).toThrow()
})
it('注释可编辑时仍尊重单独的布局只读能力', () => {
  expect(() => noteParagraphLayout(source, { ...source, attrs: { ...source.attrs, align: 'center' } }, { ...anchor, paragraphLayoutEditable: false }, model)).toThrow()
  expect(noteParagraphLayout(source, source, { ...anchor, paragraphLayoutEditable: false }, model).operations).toEqual([])
})
