import { afterEach, expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { applyParagraphBorders } from './docx-borders'
import { applyParagraphShading } from './docx-shading'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { normalizePlainDocxRuns, replayPlainDocxRuns } from './docx-plain-paragraph-runs'
import { normalizeDocxNotes, type DocxNotesModel } from './docx-notes'

const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha0', editable: true, paragraphShadingEditable: true, paragraphBordersEditable: true }]
const notes: DocxNotesModel = { footnotes: [], endnotes: [], referenceBlocks: anchors.map(anchor => ({ ...anchor })) }
const editors: Editor[] = []
function setup() {
  const editor = new Editor({ extensions: editorExtensions, editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'A😀BC', marks: [{ type: 'docTextStyle', attrs: { rawRPr: '<w:rPr><w:noProof/></w:rPr>' } }] }] },
  ] } })
  editors.push(editor); editor.commands.setTextSelection(2)
  return editor
}
function normalize(source: DocxPmNode, current: DocxPmNode, withNotes: boolean, targetAnchors = anchors) {
  return withNotes ? normalizeDocxNotes(source, current, targetAnchors, notes, true) : normalizePlainDocxRuns(source, current, targetAnchors)
}
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })

it.each([false, true].flatMap(withNotes => [false, true].map(bodyFirst => ({ withNotes, bodyFirst }))))('composes final body and both decorations in either direction %j', ({ withNotes, bodyFirst }) => {
  const editor = setup(), source = editor.getJSON() as DocxPmNode
  const body = () => { editor.commands.insertContentAt(4, '新增'); editor.chain().setTextSelection({ from: 4, to: 6 }).setMark('bold').run() }
  const decorate = () => { editor.commands.setTextSelection(2); expect(applyParagraphBorders(editor, anchors, { sides: 'b', color: 'FF0000', szPt: 1 })).toBe(true); expect(applyParagraphShading(editor, anchors, 'edf5fc')).toBe(true) }
  if (bodyFirst) { body(); decorate() } else { decorate(); body() }
  const current = editor.getJSON() as DocxPmNode, normalized = normalize(source, current, withNotes)
  expect(docxOperations(normalized.baseline, normalized.current, anchors)).toEqual([])
  expect(normalized.operations.map(op => op.kind)).toEqual(['setParagraphShading', 'setParagraphBorders', 'patchParagraphRuns'])
  const ordinary = normalized.operations.filter(op => op.kind !== 'patchParagraphRuns'), plans = normalized.operations.filter(op => op.kind === 'patchParagraphRuns')
  const restored = replayPlainDocxRuns(replayDocxOperations(source, ordinary, anchors), plans, anchors)
  expect(editor.schema.nodeFromJSON(restored).content.eq(editor.state.doc.content)).toBe(true)
  expect(JSON.stringify(plans)).toContain('bold')
  editor.commands.undo(); editor.commands.redo(); expect(editor.getJSON()).toEqual(current)
  for (const fill of ['auto', 'none']) {
    editor.commands.setTextSelection(2); applyParagraphShading(editor, anchors, fill); applyParagraphBorders(editor, anchors, null)
    const result = normalize(current, editor.getJSON() as DocxPmNode, withNotes)
    expect(result.operations.map(op => op.kind)).toEqual(['setParagraphShading', 'setParagraphBorders'])
  }
})

it('rejects readonly, forged capability, unknown inline and notes anchors while retaining identity guards', () => {
  const editor = setup(), source = editor.getJSON() as DocxPmNode
  editor.commands.insertContentAt(2, '新'); applyParagraphShading(editor, anchors, 'edf5fc'); applyParagraphBorders(editor, anchors, { sides: 't' })
  const current = editor.getJSON() as DocxPmNode
  for (const patch of [{ editable: false }, { paragraphShadingEditable: false }, { paragraphBordersEditable: false }]) expect(() => normalize(source, current, false, [{ ...anchors[0]!, ...patch }])).toThrow()
  for (const attrs of [{ pageBreakBefore: true }, { styleId: 'foreign' }, { align: 'center' }, { nativeClearFormatting: { ranges: [] } }]) {
    const bad = structuredClone(current); Object.assign(bad.content![0]!.attrs!, attrs)
    expect(() => normalize(source, bad, false)).toThrow()
  }
  const unknown = structuredClone(current); unknown.content![0]!.content!.push({ type: 'docInlineMath', attrs: { omml: 'opaque' } })
  expect(() => normalize(source, unknown, false)).toThrow()
  const noteSource = structuredClone(source), noteCurrent = structuredClone(current)
  const marker = { type: 'docNoteRef', attrs: { kind: 'footnote', id: '1', num: 1 } }
  noteSource.content![0]!.content!.push(marker); noteCurrent.content![0]!.content!.push(marker)
  expect(() => normalize(noteSource, noteCurrent, true)).toThrow()
})
