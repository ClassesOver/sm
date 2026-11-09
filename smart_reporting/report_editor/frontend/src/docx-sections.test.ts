import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeTableStructure } from './docx-tables'
import { docxOperations, replayDocxOperations, restoredDocxSectionOperations, sectionBreakNode, type DocxAnchor, type DocxPmNode, type DocxSectionAnchor } from './docx-operations'
import type { SectionSettings } from '@genoffice/docx-engine'

const anchors: DocxAnchor[] = [
  { docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha-0', editable: true },
  { docxIndex: 1, blockId: 'p1', expectedObjectSha256: 'sha-1', editable: true },
]
const settings = { pageWidth: 12240, pageHeight: 15840, marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, orientation: 'portrait', columns: 1 } as SectionSettings
const sections: DocxSectionAnchor[] = [
  { sectionId: 's0', expectedSectionSha256: 'x0', settings, firstBlockIndex: 0, lastBlockIndex: 0 },
  { sectionId: 's1', expectedSectionSha256: 'x1', settings, firstBlockIndex: 1, lastBlockIndex: 1 },
]
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()) })
function setup() {
  let baseline: DocxPmNode | undefined
  const rejected: string[] = []
  const Guard = Extension.create({ name: 'testNativeGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) {
    if (!baseline || !tr.docChanged) return true
    try { docxOperations(baseline, tr.doc.toJSON() as DocxPmNode, anchors, undefined, editor.schema); return true } catch (error) { rejected.push((error as Error).message); return false }
  } })] })
  const editor = new Editor({ extensions: [...editorExtensions, NativeTableStructure, Guard], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '第一节' }] },
    { type: 'docParagraph', attrs: { docxIndex: 1 }, content: [{ type: 'text', text: '第二节' }] },
  ] } })
  editors.push(editor)
  baseline = editor.getJSON() as DocxPmNode
  return { editor, baseline, rejected }
}

it('keeps one merged layout operation per section and rejects foreign section ids', () => {
  const ops = restoredDocxSectionOperations([
    { kind: 'setSectionLayout', sectionId: 's1', expectedSectionSha256: 'x1', values: { columns: 2 } },
    { kind: 'setSectionLayout', sectionId: 's0', expectedSectionSha256: 'x0', values: { marginLeft: 720 } },
    { kind: 'setSectionLayout', sectionId: 's1', expectedSectionSha256: 'x1', values: { orientation: 'landscape' } },
  ], sections)
  expect(ops).toEqual([
    { kind: 'setSectionLayout', sectionId: 's0', expectedSectionSha256: 'x0', values: { marginLeft: 720 } },
    { kind: 'setSectionLayout', sectionId: 's1', expectedSectionSha256: 'x1', values: { columns: 2, orientation: 'landscape' } },
  ])
  expect(() => restoredDocxSectionOperations([{ kind: 'setSectionLayout', sectionId: 'other', expectedSectionSha256: 'x', values: { columns: 2 } }], sections)).toThrow(/节身份/)
  expect(() => restoredDocxSectionOperations([{ kind: 'setSectionLayout', sectionId: 's0', expectedSectionSha256: 'stale', values: { columns: 2 } }], sections)).toThrow(/节身份/)
})

it('diffs and replays a section break right after its anchor, then paragraphs typed after it', () => {
  const { editor, baseline, rejected } = setup()
  editor.chain().insertContentAt(editor.state.doc.child(0).nodeSize, sectionBreakNode('continuous') as never).run()
  expect(rejected).toEqual([])
  const ops = docxOperations(baseline, editor.getJSON() as DocxPmNode, anchors, undefined, editor.schema)
  expect(ops).toEqual([{ kind: 'insertSectionBreak', blockId: 'p0', expectedObjectSha256: 'sha-0', type: 'continuous' }])
  const restored = replayDocxOperations(baseline, ops, anchors, sections, editor.schema)
  expect(restored.content!.map(node => node.type)).toEqual(['docParagraph', 'docProtected', 'docParagraph'])
  expect(editor.schema.nodeFromJSON(restored).eq(editor.state.doc)).toBe(true)
  expect(docxOperations(baseline, restored, anchors, undefined, editor.schema)).toEqual(ops)
})

it('refuses a section break that does not directly follow an original block, and forged drafts', () => {
  const { editor, baseline } = setup()
  const forged = (node: DocxPmNode, at = 1) => { const doc = structuredClone(baseline); doc.content!.splice(at, 0, node); return doc }
  expect(() => docxOperations(baseline, forged(sectionBreakNode('nextPage'), 0), anchors, undefined, editor.schema)).toThrow(/紧跟在原有/)
  const bad = sectionBreakNode('nextPage'); bad.attrs!.nativeSectionBreak = 'nextColumn'
  expect(() => docxOperations(baseline, forged(bad), anchors, undefined, editor.schema)).toThrow(/意图无效/)
  const op = { kind: 'insertSectionBreak', blockId: 'p0', expectedObjectSha256: 'sha-0', type: 'nextPage' }
  for (const draft of [{ ...op, type: 'nextColumn' }, { ...op, expectedObjectSha256: 'old' }, { ...op, xml: '<w:sectPr/>' }])
    expect(() => replayDocxOperations(baseline, [draft], anchors, sections, editor.schema)).toThrow()
})
