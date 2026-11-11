import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { setSelectionAlign } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/direction'
import { applyParagraphBorders } from './docx-borders'
import { applyParagraphShading } from './docx-shading'
import { normalizeDocxNotes, replayDocxNotes, applyDocxNotesIntent, type DocxNotesModel } from './docx-notes'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'

const Intent = Extension.create({ name: 'decorationNotesIntent', addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeNotesOperations: { default: null, rendered: false } } }] })
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha0', editable: false, paragraphLayoutEditable: true, paragraphShadingEditable: true, paragraphBordersEditable: true }]
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

it.each(['footnote', 'endnote'].flatMap(kind => ['existing', 'insert', 'update', 'delete'].flatMap(action => [false, true].map(bodyFirst => ({ kind: kind as 'footnote' | 'endnote', action, bodyFirst })))))('combines trusted notes source, final body, all layout fields and decorations %j', ({ kind, action, bodyFirst }) => {
  const { editor, model } = setup(kind), baseline = editor.getJSON() as DocxPmNode
  const decorate = () => { editor.commands.setTextSelection(2); expect(setSelectionAlign(editor, 'center')).toBe(true); editor.commands.updateAttributes('docParagraph', { indentLeft: 720, indentRight: 360, spaceBefore: 240, spaceAfter: 120, lineSpacing: 1.5 }); expect(applyParagraphShading(editor, anchors, 'edf5fc')).toBe(true); expect(applyParagraphBorders(editor, anchors, { sides: 'b', color: 'FF0000', szPt: 1 })).toBe(true) }
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
  expect(normalized.operations.map(op => op.kind)).toEqual(['setParagraphShading', 'setParagraphBorders', 'setParagraphSpacing', 'setParagraphIndent', 'setParagraphRightIndent', 'setParagraphAlignment', 'patchParagraphRuns', ...(action === 'existing' ? [] : [`${action}Note`])])
  const decorations = normalized.operations.filter(op => ['setParagraphShading', 'setParagraphBorders', 'setParagraphSpacing', 'setParagraphIndent', 'setParagraphRightIndent', 'setParagraphAlignment'].includes(op.kind)), plans = normalized.operations.filter(op => op.kind === 'patchParagraphRuns'), noteOps = normalized.operations.filter(op => !['setParagraphShading', 'setParagraphBorders', 'setParagraphSpacing', 'setParagraphIndent', 'setParagraphRightIndent', 'setParagraphAlignment', 'patchParagraphRuns'].includes(op.kind))
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


it.each([false, true])('composes plain source layout, decorations and body without notes model, bodyFirst=%s', bodyFirst => {
  const { editor } = setup('footnote')
  const source = editor.getJSON() as DocxPmNode
  source.content![0]!.content = source.content![0]!.content!.filter(node => node.type !== 'docNoteRef')
  editor.commands.setContent(source as never)
  const baseline = editor.getJSON() as DocxPmNode, plainAnchors = [{ ...anchors[0]!, editable: true }]
  const model = { footnotes: [], endnotes: [], referenceBlocks: [{ ...plainAnchors[0]! }] }
  const decorate = () => { editor.commands.setTextSelection(2); editor.commands.updateAttributes('docParagraph', { align: 'right', indentLeft: 720, indentRight: 360, spaceBefore: 240, spaceAfter: 120, lineSpacing: 2 }); expect(applyParagraphShading(editor, plainAnchors, 'edf5fc')).toBe(true); expect(applyParagraphBorders(editor, plainAnchors, { sides: 'b' })).toBe(true) }
  const body = () => editor.commands.insertContentAt(4, '新增')
  if (bodyFirst) { body(); decorate() } else { decorate(); body() }
  const current = editor.getJSON() as DocxPmNode, result = normalizeDocxNotes(baseline, current, plainAnchors, model, true)
  const ordinary = result.operations.filter(op => op.kind !== 'patchParagraphRuns'), plans = result.operations.filter(op => op.kind === 'patchParagraphRuns')
  const draft = replayDocxNotes(replayDocxOperations(baseline, ordinary, plainAnchors), [], plainAnchors, model, plans)
  expect(editor.schema.nodeFromJSON(draft).content.eq(editor.state.doc.content)).toBe(true)
})

it('keeps combined source capabilities, unknown paragraph attrs, hashes and fields strict', () => {
  const { editor, model } = setup('footnote'), baseline = editor.getJSON() as DocxPmNode
  editor.commands.setTextSelection(2); editor.commands.updateAttributes('docParagraph', { align: 'center' })
  expect(applyParagraphShading(editor, anchors, 'edf5fc')).toBe(true); expect(applyParagraphBorders(editor, anchors, { sides: 'b' })).toBe(true)
  const current = editor.getJSON() as DocxPmNode
  for (const key of ['paragraphLayoutEditable', 'paragraphShadingEditable', 'paragraphBordersEditable']) expect(() => normalizeDocxNotes(baseline, current, [{ ...anchors[0]!, [key]: false }], model)).toThrow()
  for (const attrs of [{ pageBreakBefore: true }, { bidi: true }, { styleId: 'foreign' }]) {
    const unknown = structuredClone(current); Object.assign(unknown.content![0]!.attrs!, attrs)
    expect(() => normalizeDocxNotes(baseline, unknown, anchors, model)).toThrow()
  }
  const operations = normalizeDocxNotes(baseline, current, anchors, model).operations
  for (const operation of operations) for (const extra of [{ expectedObjectSha256: 'foreign' }, { rawPPr: '<evil/>' }]) expect(() => replayDocxOperations(baseline, operations.map(op => op === operation ? { ...op, ...extra } : op), anchors)).toThrow()
})
