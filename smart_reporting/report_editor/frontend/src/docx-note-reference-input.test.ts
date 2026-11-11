import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { runsToInline } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import { normalizeDocxNotes, replayDocxNotes, type DocxNotesModel } from './docx-notes'
import type { DocxPmNode } from './docx-operations'

const editors: Editor[] = []
afterEach(() => editors.splice(0).forEach(editor => editor.destroy()))
it.each(['footnote', 'endnote'] as const)('accepts native typing after retained source %s with its exact marks, continuous typing, partial style and draft', kind => {
  const anchor = { docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha0', editable: false }, anchors = [anchor]
  const entry = { id: '1', text: '来源注释', expectedNoteSha256: 'note-sha', editable: true, references: [{ blockId: 'p0', expectedObjectSha256: 'sha0', referenceIndex: 0 }] }
  const model: DocxNotesModel = { footnotes: kind === 'footnote' ? [entry] : [], endnotes: kind === 'endnote' ? [entry] : [], referenceBlocks: [{ ...anchor, editable: true }] }
  let baseline: DocxPmNode | undefined, rejection = ''
  const Guard = Extension.create({ name: 'referenceInputGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(transaction) {
    if (!baseline || !transaction.docChanged) return true
    try { normalizeDocxNotes(baseline, transaction.doc.toJSON(), anchors, model); return true } catch (error) { rejection = String(error); return false }
  } })] })
  const editor = new Editor({ extensions: [...editorExtensions, Guard], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: runsToInline([
    { text: 'Body', bold: true, rawRPr: '<w:rPr><w:b/><w:noProof/></w:rPr>' },
    { text: '1', noteRef: { kind, id: '1' }, rawRPr: '<w:rPr><w:vertAlign w:val="superscript"/><w:noProof/></w:rPr>' },
  ]) }] } })
  editors.push(editor); baseline = editor.getJSON() as DocxPmNode
  editor.commands.setTextSelection(editor.state.doc.content.size - 1)
  editor.view.dispatch(editor.state.tr.insertText('新增'))
  expect(editor.state.doc.textContent, rejection).toBe('Body新增')
  editor.view.dispatch(editor.state.tr.insertText('续写'))
  editor.chain().setTextSelection({ from: 6, to: 8 }).setMark('bold').run()
  const current = editor.getJSON() as DocxPmNode, result = normalizeDocxNotes(baseline, current, anchors, model)
  const plan = result.operations.find(op => op.kind === 'patchParagraphRuns')!
  expect(plan.runs).toContainEqual({ text: '新增', inheritFrom: 4, style: { bold: true } })
  expect(plan.runs).toContainEqual({ text: '续写', inheritFrom: 4 })
  const restored = replayDocxNotes(baseline, [], anchors, model, [plan])
  expect(editor.schema.nodeFromJSON(restored).content.eq(editor.state.doc.content)).toBe(true)
  expect(current.content![0]!.content!.filter(node => node.type === 'docNoteRef')).toHaveLength(1)
  editor.commands.undo(); editor.commands.redo(); expect(editor.getJSON()).toEqual(current)
  for (const field of ['blockId', 'expectedObjectSha256', 'referenceIndex'] as const) {
    const forged = structuredClone(model)
    Object.assign(forged[`${kind}s`][0]!.references[0]!, { [field]: field === 'referenceIndex' ? 9 : 'foreign' })
    expect(() => normalizeDocxNotes(baseline!, current, anchors, forged)).toThrow()
  }
  const deletion = { kind: 'deleteNote', noteKind: kind, noteId: '1', expectedNoteSha256: entry.expectedNoteSha256, expectedReferences: entry.references }
  const withoutMarker = structuredClone(current)
  withoutMarker.attrs = { ...withoutMarker.attrs, nativeNotesOperations: [deletion] }
  withoutMarker.content![0]!.content = withoutMarker.content![0]!.content!.filter(node => node.type !== 'docNoteRef')
  const deletedPlan = normalizeDocxNotes(baseline!, withoutMarker, anchors, model).operations.find(op => op.kind === 'patchParagraphRuns')!
  const deletedDraft = replayDocxNotes(baseline!, [deletion], anchors, model, [deletedPlan])
  expect(editor.schema.nodeFromJSON(deletedDraft).content.eq(editor.schema.nodeFromJSON(withoutMarker).content)).toBe(true)
  expect(deletedDraft.content![0]!.content!.some(node => node.type === 'docNoteRef')).toBe(false)
})
