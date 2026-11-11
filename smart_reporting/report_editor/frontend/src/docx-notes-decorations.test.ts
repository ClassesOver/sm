import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { applyParagraphBorders } from './docx-borders'
import { applyParagraphShading } from './docx-shading'
import { normalizeDocxNotes, replayDocxNotes, applyDocxNotesIntent, type DocxNotesModel } from './docx-notes'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'

const Intent = Extension.create({ name: 'decorationNotesIntent', addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeNotesOperations: { default: null, rendered: false } } }] })
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha0', editable: false, paragraphShadingEditable: true, paragraphBordersEditable: true }]
function setup(kind: 'footnote' | 'endnote') {
  const reference = { blockId: 'p0', expectedObjectSha256: 'sha0', referenceIndex: 0 }
  const entry = { id: '1', text: '来源注释', expectedNoteSha256: 'note-sha', editable: true, references: [reference] }
  const model: DocxNotesModel = { footnotes: kind === 'footnote' ? [entry] : [], endnotes: kind === 'endnote' ? [entry] : [], referenceBlocks: [{ ...reference, editable: true }] }
  const editor = new Editor({ extensions: [...editorExtensions, Intent], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [
    { type: 'text', text: 'A😀', marks: [{ type: 'docTextStyle', attrs: { rawRPr: '<w:rPr><w:noProof/></w:rPr>' } }] },
    { type: 'docNoteRef', attrs: { kind, id: '1', num: 1, rawRPr: null } }, { type: 'text', text: 'BC' },
  ] }] } })
  editors.push(editor); editor.commands.setTextSelection(2)
  return { editor, model }
}

it.each(['footnote', 'endnote'].flatMap(kind => ['existing', 'insert', 'update', 'delete'].flatMap(action => [false, true].map(bodyFirst => ({ kind: kind as 'footnote' | 'endnote', action, bodyFirst })))))('combines trusted notes source, final body and decorations %j', ({ kind, action, bodyFirst }) => {
  const { editor, model } = setup(kind), baseline = editor.getJSON() as DocxPmNode
  const decorate = () => { editor.commands.setTextSelection(2); expect(applyParagraphShading(editor, anchors, 'edf5fc')).toBe(true); expect(applyParagraphBorders(editor, anchors, { sides: 'b', color: 'FF0000', szPt: 1 })).toBe(true) }
  const body = () => {
    editor.commands.insertContentAt(4, '新增'); editor.chain().setTextSelection({ from: 4, to: 6 }).setMark('bold').run()
    const operations = action === 'existing' ? [] : action === 'insert' ? [{ kind: 'insertNote', blockId: 'p0', expectedObjectSha256: 'sha0', noteKind: kind, offset: 5, text: '新增注释' }]
      : [{ kind: `${action}Note`, noteKind: kind, noteId: '1', expectedNoteSha256: 'note-sha', ...(action === 'update' ? { text: '更正注释' } : { expectedReferences: model[`${kind}s`][0]!.references }) }]
    const next = applyDocxNotesIntent(editor.getJSON() as DocxPmNode, operations, anchors, model)
    editor.view.dispatch(editor.state.tr.replaceWith(0, editor.state.doc.content.size, editor.schema.nodeFromJSON(next).content).setDocAttribute('nativeNotesOperations', operations))
  }
  if (bodyFirst) { body(); decorate() } else { decorate(); body() }
  const current = editor.getJSON() as DocxPmNode
  const normalized = normalizeDocxNotes(baseline, current, anchors, model)
  expect(docxOperations(normalized.baseline, normalized.current, anchors)).toEqual([])
  expect(normalized.operations.map(op => op.kind)).toEqual(['setParagraphShading', 'setParagraphBorders', 'patchParagraphRuns', ...(action === 'existing' ? [] : [`${action}Note`])])
  const decorations = normalized.operations.filter(op => ['setParagraphShading', 'setParagraphBorders'].includes(op.kind)), plans = normalized.operations.filter(op => op.kind === 'patchParagraphRuns'), noteOps = normalized.operations.filter(op => !['setParagraphShading', 'setParagraphBorders', 'patchParagraphRuns'].includes(op.kind))
  const restored = replayDocxNotes(replayDocxOperations(baseline, decorations, anchors), noteOps, anchors, model, plans)
  expect(editor.schema.nodeFromJSON(restored).content.eq(editor.state.doc.content)).toBe(true)
  editor.commands.undo(); editor.commands.redo(); expect(editor.getJSON()).toEqual(current)
  for (const value of ['auto', 'none']) {
    editor.commands.setTextSelection(2); expect(applyParagraphShading(editor, anchors, value)).toBe(true); expect(applyParagraphBorders(editor, anchors, null)).toBe(true)
    const result = normalizeDocxNotes(baseline, editor.getJSON() as DocxPmNode, anchors, model)
    if (value === 'auto') expect(result.operations.find(op => op.kind === 'setParagraphShading')).toMatchObject({ fill: null, clear: true })
    else expect(result.operations.find(op => op.kind === 'setParagraphShading')).toBeUndefined()
  }
  expect(anchors[0]!.editable).toBe(false)
})

it('keeps missing independent capability, foreign notes identity and unknown inline readonly', () => {
  const { editor, model } = setup('footnote'), baseline = editor.getJSON() as DocxPmNode
  for (const patch of [{ paragraphShadingEditable: false }, { paragraphShadingEditable: undefined }]) expect(applyParagraphShading(editor, [{ ...anchors[0]!, ...patch }], 'edf5fc')).toBe(false)
  for (const patch of [{ paragraphBordersEditable: false }, { paragraphBordersEditable: undefined }]) expect(applyParagraphBorders(editor, [{ ...anchors[0]!, ...patch }], { sides: 't' })).toBe(false)
  expect(applyParagraphShading(editor, [anchors[0]!, anchors[0]!], 'edf5fc')).toBe(false)
  const unknown = structuredClone(baseline); unknown.content![0]!.content!.push({ type: 'docInlineMath', attrs: { omml: 'opaque' } })
  editor.commands.setContent(unknown as never); editor.commands.setTextSelection(2)
  expect(applyParagraphShading(editor, anchors, 'edf5fc')).toBe(false)
  expect(applyParagraphBorders(editor, anchors, { sides: 'b' })).toBe(false)
  const current = structuredClone(baseline); current.content![0]!.attrs!.shadingFill = 'edf5fc'
  expect(() => normalizeDocxNotes(baseline, current, anchors, { ...model, referenceBlocks: [{ blockId: 'p0', expectedObjectSha256: 'foreign', editable: true }] })).toThrow()
  const operation = { kind: 'setParagraphShading', blockId: 'p0', expectedObjectSha256: 'sha0', fill: 'edf5fc', clear: false }
  for (const bad of [{ ...operation, expectedObjectSha256: 'foreign' }, { ...operation, rawPPr: '<evil/>' }]) expect(() => replayDocxOperations(baseline, [bad], anchors)).toThrow()
})

it('checks every source reference ordinal when one note has multiple markers in a paragraph', () => {
  const { editor, model } = setup('footnote')
  const baseline = editor.getJSON() as DocxPmNode
  baseline.content![0]!.content!.push(structuredClone(baseline.content![0]!.content![1]!))
  model.footnotes[0]!.references.push({ blockId: 'p0', expectedObjectSha256: 'sha0', referenceIndex: 1 })
  const current = structuredClone(baseline); current.content![0]!.attrs!.shadingFill = 'edf5fc'
  expect(normalizeDocxNotes(baseline, current, anchors, model).operations.map(op => op.kind)).toEqual(['setParagraphShading'])
  const foreign = structuredClone(model); foreign.footnotes[0]!.references[1]!.expectedObjectSha256 = 'foreign'
  expect(() => normalizeDocxNotes(baseline, current, anchors, foreign)).toThrow('注释来源身份无效')
})
