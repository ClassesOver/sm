import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { setSelectionAlign } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/direction'
import { normalizeDocxNotes, replayDocxNotes, type DocxNotesModel } from './docx-notes'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'

const editors: Editor[] = []
afterEach(() => editors.splice(0).forEach(editor => editor.destroy()))
const Intent = Extension.create({ name: 'layoutNoteIntent', addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeNotesOperations: { default: null, rendered: false } } }] })
it.each(['align', 'indentLeft', 'spaceBefore'].flatMap(key => [[key, false], [key, true]] as const))('同来源段正文+脚注与%s布局原子归一，既有note=%s', (key, existing) => {
  const anchor = { docxIndex: 0, blockId: 'source', expectedObjectSha256: 'source-sha', editable: !existing, paragraphLayoutEditable: true }
  const anchors: DocxAnchor[] = [anchor]
  const model: DocxNotesModel = { footnotes: existing ? [{ id: '1', text: '来源脚注', expectedNoteSha256: 'note-sha', editable: true, references: [{ blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, referenceIndex: 0 }] }] : [], endnotes: [], referenceBlocks: [{ blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, editable: true }] }
  const editor = new Editor({ extensions: [...editorExtensions, Intent], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [
    { type: 'text', text: 'A😀' }, ...(existing ? [{ type: 'docNoteRef', attrs: { kind: 'footnote', id: '1', num: 1, rawRPr: null } }] : []), { type: 'text', text: 'BC' },
  ] }] } })
  editors.push(editor)
  const baseline = editor.getJSON() as DocxPmNode
  editor.commands.insertContentAt(4, '新增')
  const notes = [{ kind: 'insertNote', blockId: 'source', expectedObjectSha256: 'source-sha', noteKind: 'footnote', offset: 5, text: '正文布局脚注' }]
  const current = replayDocxNotes(editor.getJSON(), notes, anchors, model)
  editor.view.dispatch(editor.state.tr.replaceWith(0, editor.state.doc.content.size, editor.schema.nodeFromJSON(current).content).setDocAttribute('nativeNotesOperations', notes))
  editor.commands.setTextSelection(2)
  if (key === 'align') expect(setSelectionAlign(editor, 'center')).toBe(true)
  else editor.commands.updateAttributes('docParagraph', { [key]: key === 'indentLeft' ? 720 : 240 })
  const live = editor.getJSON() as DocxPmNode
  expect(live.content![0].attrs![key]).toBe(key === 'align' ? 'center' : key === 'indentLeft' ? 720 : 240)
  const normalized = normalizeDocxNotes(baseline, live, anchors, model)
  const operations = [...docxOperations(normalized.baseline, normalized.current, anchors), ...normalized.operations]
  expect(operations.map(op => op.kind)).toContain(key === 'align' ? 'setParagraphAlignment' : key === 'indentLeft' ? 'setParagraphIndent' : 'setParagraphSpacing')
  expect(operations.map(op => op.kind)).toContain('patchParagraphRuns')
  expect(operations.map(op => op.kind)).toContain('insertNote')
  const noteOps = normalized.operations.filter(op => op.kind === 'insertNote'), plans = normalized.operations.filter(op => op.kind === 'patchParagraphRuns')
  const ordinary = replayDocxOperations(baseline, operations.filter(op => !['patchParagraphRuns', 'insertNote'].includes(op.kind)), anchors)
  const restored = replayDocxNotes(ordinary, noteOps, anchors, model, plans)
  expect(editor.schema.nodeFromJSON(restored).content.eq(editor.state.doc.content)).toBe(true)
})

it.each([
  { kind: 'setParagraphAlignment', alignment: 'center' },
  { kind: 'setParagraphIndent', twips: 720 },
  { kind: 'setParagraphRightIndent', twips: 360 },
  { kind: 'setParagraphSpacing', spaceBefore: 240 },
].flatMap(layout => ['hash', 'fields', 'readonly'].map(fault => ({ layout, fault }))))('布局草稿拒绝来源或字段损坏 $layout.kind $fault', ({ layout, fault }) => {
  const source: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'source' }] }] }
  const anchor = { docxIndex: 0, blockId: 'source', expectedObjectSha256: 'source-sha', editable: false, paragraphLayoutEditable: fault !== 'readonly' }
  const operation = { ...layout, blockId: anchor.blockId, expectedObjectSha256: fault === 'hash' ? 'foreign-sha' : anchor.expectedObjectSha256, ...(fault === 'fields' ? { rawPPr: '<w:pPr/>' } : {}) }
  expect(() => replayDocxOperations(source, [operation], [anchor])).toThrow()
})
