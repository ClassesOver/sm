import { afterEach, expect, it } from 'vitest'
import { Editor, Mark, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations, replayDocxOperations, type DocxAnchor } from './docx-operations'
import { paragraphVerticalAlign, toggleParagraphVerticalAlign, verticalAlignTarget, withoutVerticalAlign } from './docx-vertical'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => ({ docxIndex: { default: null } }), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const Bold = Mark.create({ name: 'bold', renderHTML: () => ['b', 0] })
const Italic = Mark.create({ name: 'italic', renderHTML: () => ['i', 0] })
const Style = Mark.create({ name: 'docTextStyle', addAttributes: () => ({ color: { default: null }, font: { default: null }, sizeHalfPoints: { default: null }, vertAlign: { default: null } }), renderHTML: () => ['span', 0] })
const Link = Mark.create({ name: 'link', addAttributes: () => ({ href: { default: '' }, rId: { default: null }, tooltip: { default: null }, plain: { default: false } }), renderHTML: () => ['a', 0] })
const anchor: DocxAnchor = { docxIndex: 0, blockId: 'body', expectedObjectSha256: 'source-sha', editable: true }
const anchors = [anchor]
const editors: Editor[] = []
function setup(mixed = true) {
  const editor = new Editor({ extensions: [Doc, Paragraph, Text, Style, Bold, Italic, Link, UndoRedo], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [
      { type: 'text', text: 'A😀', marks: [{ type: 'bold' }, { type: 'docTextStyle', attrs: { color: 'AABBCC', font: 'Calibri' } }] },
      { type: 'text', text: 'BC', marks: mixed ? [{ type: 'italic' }] : [{ type: 'bold' }, { type: 'docTextStyle', attrs: { color: 'AABBCC', font: 'Calibri' } }] },
      { type: 'text', text: 'keep', marks: [{ type: 'link', attrs: { href: 'https://keep.test', rId: 'rId4', tooltip: 'keep', plain: true } }] },
    ] }, { type: 'docParagraph', attrs: { docxIndex: null }, content: [{ type: 'text', text: 'new' }] },
  ] } })
  editors.push(editor); editor.commands.setTextSelection(2); return editor
}
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
const sourceOnly = (editor: Editor) => ({ ...editor.getJSON(), content: editor.getJSON().content!.slice(0, 1) })
const operations = (original: ReturnType<typeof sourceOnly>, editor: Editor) => docxOperations(original, sourceOnly(editor), anchors)

it.each(['superscript', 'subscript'] as const)('toggles %s on a full anchored paragraph while keeping mixed styles and source links', kind => {
  const editor = setup(), original = sourceOnly(editor)
  expect(toggleParagraphVerticalAlign(editor, anchors, kind)).toBe(true)
  expect(paragraphVerticalAlign(editor.getJSON().content![0])).toBe(kind)
  expect(withoutVerticalAlign(editor.getJSON().content![0])).toEqual(withoutVerticalAlign(original.content![0]))
  const ops = operations(original, editor)
  expect(ops).toEqual([{ kind: 'setParagraphVerticalAlign', blockId: 'body', expectedObjectSha256: 'source-sha', value: kind }])
  const restored = replayDocxOperations(original, ops, anchors)
  expect(docxOperations(original, restored, anchors)).toEqual(ops)
  editor.commands.undo(); expect(operations(original, editor)).toEqual([])
  editor.commands.redo(); expect(operations(original, editor)).toEqual(ops)
  toggleParagraphVerticalAlign(editor, anchors, kind)
  expect(operations(original, editor)).toEqual([])
})
it('emits explicit baseline when clearing a source superscript and preserves all unrelated marks', () => {
  const editor = setup(); toggleParagraphVerticalAlign(editor, anchors, 'superscript')
  const original = sourceOnly(editor)
  toggleParagraphVerticalAlign(editor, anchors, 'superscript')
  const ops = operations(original, editor)
  expect(ops).toEqual([{ kind: 'setParagraphVerticalAlign', blockId: 'body', expectedObjectSha256: 'source-sha', value: 'baseline' }])
  const restored = replayDocxOperations(original, ops, anchors)
  expect(paragraphVerticalAlign(restored.content![0])).toBe('baseline')
  expect(withoutVerticalAlign(restored.content![0])).toEqual(withoutVerticalAlign(original.content![0]))
})
it('rejects local or mixed-position changes instead of dropping a native text-style attribute', () => {
  const editor = setup(), original = sourceOnly(editor)
  editor.commands.setTextSelection({ from: 1, to: 2 }); editor.commands.setMark('docTextStyle', { vertAlign: 'superscript' })
  expect(() => operations(original, editor)).toThrow(/局部上下标/)
  const mixed = sourceOnly(editor), changed = structuredClone(mixed)
  changed.content![0].content![0].marks!.find(mark => mark.type === 'docTextStyle')!.attrs!.vertAlign = 'subscript'
  expect(() => docxOperations(mixed, changed, anchors)).toThrow(/局部上下标/)
})
it('keeps the source Ribbon toggles disabled for new, cross-paragraph, readonly or saving targets', () => {
  const editor = setup(), ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, anchors)
  document.body.append(ribbon)
  const sup = () => ribbon.querySelector<HTMLButtonElement>('[data-action="superscript"]')!
  expect(sup().disabled).toBe(false)
  sup().click(); expect(sup().getAttribute('aria-pressed')).toBe('true')
  editor.setEditable(false); editor.commands.setMeta('saving', true); expect(sup().disabled).toBe(true)
  editor.setEditable(true); editor.commands.setTextSelection(editor.state.doc.content.size - 1)
  expect(verticalAlignTarget(editor, anchors)).toBeUndefined(); expect(sup().disabled).toBe(true)
  editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 }); expect(sup().disabled).toBe(true)
  editor.commands.setTextSelection(2)
  expect(toggleParagraphVerticalAlign(editor, [{ ...anchor, editable: false }], 'subscript')).toBe(false)
})
it.each([{ value: 'sideways' }, { value: true }, { value: 'superscript', expectedObjectSha256: 'stale' }, { value: 'subscript', rawRPr: '<w:rPr/>' }])('rejects invalid restored protocol %j', patch => {
  const editor = setup(), original = sourceOnly(editor)
  expect(() => replayDocxOperations(original, [{ kind: 'setParagraphVerticalAlign', blockId: 'body', expectedObjectSha256: 'source-sha', ...patch }], anchors)).toThrow(/草稿上下标/)
  expect(sourceOnly(editor)).toEqual(original)
})
it('does not manufacture a baseline operation while typing or clearing plain paragraph text', () => {
  const original = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 } }] }
  const current = structuredClone(original) as any; current.content[0].content = [{ type: 'text', text: 'typed' }]
  expect(docxOperations(original, current, anchors)).toEqual([{ kind: 'replaceParagraph', blockId: 'body', expectedObjectSha256: 'source-sha', text: 'typed' }])
  expect(docxOperations(current, original, anchors)).toEqual([{ kind: 'replaceParagraph', blockId: 'body', expectedObjectSha256: 'source-sha', text: '' }])
})
it('keeps each quick vertical-align command as a separate undo step', () => {
  const editor = setup()
  toggleParagraphVerticalAlign(editor, anchors, 'superscript')
  toggleParagraphVerticalAlign(editor, anchors, 'subscript')
  editor.commands.undo()
  expect(paragraphVerticalAlign(editor.getJSON().content![0])).toBe('superscript')
  editor.commands.redo()
  expect(paragraphVerticalAlign(editor.getJSON().content![0])).toBe('subscript')
})
