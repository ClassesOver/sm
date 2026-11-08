import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { Plugin } from '@tiptap/pm/state'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { NativeDraft } from './native-draft'

const defaults = (values: Record<string, unknown>) => Object.fromEntries(Object.entries(values).map(([key, value]) => [key, { default: value }]))
const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => defaults({ docxIndex: null, spaceBefore: null, spaceAfter: null, spaceBeforeAuto: null, spaceAfterAuto: null, lineSpacing: null, lineRule: null, lineRawTwips: null }), renderHTML: () => ['p', 0] })
const Heading = Paragraph.extend({ name: 'docHeading' })
const List = Paragraph.extend({ name: 'docListItem' })
const Table = Node.create({ name: 'docTable', group: 'block', content: 'docParagraph+', addAttributes: () => defaults({ docxIndex: null }), renderHTML: () => ['table', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })

function setup(editable = true, types = ['docParagraph', 'docParagraph']) {
  const values = new Map<string, string>()
  const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
  const identity = { documentId: 'spacing', revision: 1, sourceSha256: 'source', scope: { database: 'd', companyId: 'c', userId: 'u', threadId: 't' } }
  const draft = new NativeDraft(identity, storage)
  const anchors: DocxAnchor[] = [0, 1].map(docxIndex => ({ docxIndex, blockId: `block-${docxIndex}`, expectedObjectSha256: `hash-${docxIndex}`, editable: true }))
  let original: DocxPmNode, ready = false
  const errors: string[] = []
  const Guard = Extension.create({ name: 'spacingGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) {
    if (!ready || !tr.docChanged || tr.getMeta('spacing-fixture')) return true
    try { docxOperations(original, tr.doc.toJSON(), anchors); return true } catch (error) { errors.push(String(error)); return false }
  } })] })
  const host = document.createElement('div'); document.body.append(host)
  const editor = new Editor({ element: host, editable, extensions: [Doc, Paragraph, Heading, List, Table, Text, UndoRedo, Guard], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: types.map((type, docxIndex) => ({ type, attrs: { docxIndex, spaceBefore: docxIndex ? 240 : null, spaceAfter: 0 }, content: [{ type: 'text', text: 'same' }] })) }, onUpdate: () => { if (ready) draft.setOperations(docxOperations(original, editor.getJSON(), anchors)) } })
  editors.push(editor); original = editor.getJSON(); ready = true
  const ribbon = createDocxRibbon(editor, editable, undefined, undefined, undefined, anchors)
  document.body.append(ribbon)
  ribbon.querySelector<HTMLButtonElement>('[data-tab-id="layout"]')!.click()
  const field = (side = 'before') => ribbon.querySelector<HTMLInputElement>(`[data-action="space-${side}-value"]`)!
  const commit = (value: string, side = 'before') => { const input = field(side); input.focus(); input.value = value; input.blur() }
  const selectAll = () => editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 })
  return { editor, original, draft, storage, identity, anchors, ribbon, field, commit, selectAll, errors }
}

it('edits arbitrary point values through original anchored operations with undo/redo and persisted refresh', () => {
  const f = setup()
  expect(f.field().disabled).toBe(false)
  expect(f.field().value).toBe('')
  expect(f.field().placeholder).toBe('继承')
  f.commit('7.35')
  const first = [{ kind: 'setParagraphSpacing', blockId: 'block-0', expectedObjectSha256: 'hash-0', spaceBefore: 147 }]
  expect(f.draft.operations).toEqual(first)
  f.commit('0', 'after') // Already explicit zero: no extra operation.
  expect(f.draft.operations).toEqual(first)
  f.commit('1.05', 'after')
  expect(f.draft.operations[0]).toMatchObject({ spaceBefore: 147, spaceAfter: 21 })
  expect(f.editor.commands.undo()).toBe(true)
  expect(f.draft.operations).toEqual(first)
  expect(f.editor.commands.undo()).toBe(true)
  expect(f.draft.operations).toEqual([])
  expect(f.editor.commands.redo()).toBe(true)
  expect(f.draft.operations).toEqual(first)
  const restored = new NativeDraft(f.identity, f.storage)
  expect(restored.operations).toEqual(first)
  const projected = replayDocxOperations(f.original, restored.operations, f.anchors)
  f.editor.commands.setContent(projected, { emitUpdate: false })
  f.editor.commands.setTextSelection(1)
  expect(f.field().value).toBe('7.35')
  expect(docxOperations(f.original, f.editor.getJSON(), f.anchors)).toEqual(first)
  expect(f.errors).toEqual([])
})

it.each(['', ' ', 'NaN', 'Infinity', '-1', '720.05', '0.001', '1e309'])('leaves draft unchanged for invalid or blank input %j', value => {
  const f = setup()
  f.commit(value)
  expect(f.editor.getJSON()).toEqual(f.original)
  expect(f.draft.operations).toEqual([])
  expect(f.field().value).toBe('')
})

it.each(['docParagraph', 'docHeading', 'docListItem'])('preserves inherited versus explicit zero on %s', type => {
  const f = setup(true, [type, 'docParagraph'])
  f.commit('0')
  expect(f.field().value).toBe('0')
  expect(f.field().dataset.spacingState).toBe('explicit')
  expect(f.draft.operations).toEqual([{ kind: 'setParagraphSpacing', blockId: 'block-0', expectedObjectSha256: 'hash-0', spaceBefore: 0 }])
})

it('shows mixed ranges and edits the complete focus-time paragraph set as one undo step', () => {
  const f = setup()
  f.selectAll()
  expect(f.field().placeholder).toBe('混合')
  expect(f.field().value).toBe('')
  expect(f.field('after').value).toBe('0')
  f.commit('720')
  expect(f.draft.operations).toEqual(f.anchors.map(anchor => ({ kind: 'setParagraphSpacing', blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256, spaceBefore: 14400 })))
  expect(f.editor.commands.undo()).toBe(true)
  expect(f.draft.operations).toEqual([])
  expect(f.editor.commands.redo()).toBe(true)
  expect(f.draft.operations).toHaveLength(2)
})

it('never retargets a pending value after selection-only focus changes and keeps the next field connected', () => {
  const f = setup()
  const input = f.field(), next = f.field('after')
  input.focus(); input.value = '6.25'
  f.editor.commands.setTextSelection(f.editor.state.doc.child(0).nodeSize + 1)
  next.focus() // blur of first field must not replace the next DOM input.
  expect(next.isConnected).toBe(true)
  next.value = '2.5'; next.blur()
  expect(f.draft.operations).toEqual([
    { kind: 'setParagraphSpacing', blockId: 'block-0', expectedObjectSha256: 'hash-0', spaceBefore: 125 },
    { kind: 'setParagraphSpacing', blockId: 'block-1', expectedObjectSha256: 'hash-1', spaceAfter: 50 },
  ])
})

it('cancels pending input if the document changed while focused, even at the same position', () => {
  const f = setup()
  const input = f.field(); input.focus(); input.value = '5'
  f.editor.commands.insertContent('changed')
  const beforeBlur = f.editor.getJSON()
  input.blur()
  expect(f.editor.getJSON()).toEqual(beforeBlur)
  expect(f.draft.operations.some(operation => operation.kind === 'setParagraphSpacing')).toBe(false)
})

it('rechecks anchor identity and refuses protected/missing targets without partial cross-range edits', () => {
  const f = setup()
  const input = f.field(); input.focus(); input.value = '5'
  f.anchors[0].expectedObjectSha256 = 'changed'
  input.blur()
  expect(f.draft.operations).toEqual([])
  f.anchors[1].editable = false
  f.selectAll()
  expect(f.field().disabled).toBe(true)
  f.editor.commands.setTextSelection(1)
  f.anchors.splice(0, 1)
  f.editor.commands.setMeta('refresh', true)
  expect(f.field().disabled).toBe(true)
})

it('disables fields for read-only and saving states and rechecks lock at blur', () => {
  const f = setup()
  const input = f.field(); input.focus(); input.value = '5'
  f.editor.setEditable(false)
  f.editor.commands.setMeta('saving', true)
  expect(input.disabled).toBe(true)
  input.blur()
  expect(f.draft.operations).toEqual([])
  f.editor.setEditable(true); f.editor.commands.setMeta('saving', false)
  expect(f.field().disabled).toBe(false)
  const readonly = setup(false)
  expect(readonly.field().disabled).toBe(true)
})

it('displays automatic spacing and can clear automatic mode without changing its numeric value', () => {
  const f = setup()
  f.original.content![0].attrs = { ...f.original.content![0].attrs, spaceBefore: 240, spaceBeforeAuto: true }
  f.editor.commands.setContent(f.original, { emitUpdate: false })
  f.editor.commands.setTextSelection(1)
  expect(f.field().placeholder).toBe('自动')
  f.commit('12')
  expect(f.draft.operations).toEqual([{ kind: 'setParagraphSpacing', blockId: 'block-0', expectedObjectSha256: 'hash-0', spaceBefore: 240 }])
  expect(f.editor.getJSON().content![0].attrs?.spaceBeforeAuto).toBeNull()
})

it('excludes an untouched next paragraph at offset zero from the selection boundary', () => {
  const f = setup()
  f.editor.commands.setTextSelection({ from: 1, to: f.editor.state.doc.child(0).nodeSize + 1 })
  expect(f.field().placeholder).toBe('继承')
  f.commit('5')
  expect(f.draft.operations).toEqual([{ kind: 'setParagraphSpacing', blockId: 'block-0', expectedObjectSha256: 'hash-0', spaceBefore: 100 }])
})

it('rejects newly inserted paragraphs and table cells instead of matching an unrelated source anchor', () => {
  const f = setup()
  f.editor.commands.insertContentAt(f.editor.state.doc.content.size, { type: 'docParagraph', attrs: { docxIndex: null }, content: [{ type: 'text', text: 'new' }] })
  f.editor.commands.setTextSelection(f.editor.state.doc.content.size - 1)
  expect(f.field().disabled).toBe(true)
  f.selectAll(); expect(f.field().disabled).toBe(true)
  const table = setup()
  table.original.content![1] = { type: 'docTable', attrs: { docxIndex: 1 }, content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'cell' }] }] }
  table.editor.chain().setMeta('spacing-fixture', true).setContent(table.original, { emitUpdate: false }).run()
  table.editor.commands.setTextSelection(table.editor.state.doc.child(0).nodeSize + 2)
  expect(table.field().disabled).toBe(true)
  table.selectAll(); expect(table.field().disabled).toBe(true)
})

it('rejects duplicate top-level docxIndex values before enabling an input', () => {
  const f = setup()
  f.original.content![1].attrs!.docxIndex = 0
  f.editor.chain().setMeta('spacing-fixture', true).setContent(f.original, { emitUpdate: false }).run()
  f.editor.commands.setTextSelection(1)
  expect(f.field().disabled).toBe(true)
  f.selectAll(); expect(f.field().disabled).toBe(true)
})

it('Escape cancels pending input rather than converting an inherited value to zero', () => {
  const f = setup()
  const input = f.field(); input.focus(); input.value = '10'
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(f.draft.operations).toEqual([])
  expect(f.field().value).toBe('')
})
