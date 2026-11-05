import { afterEach, describe, expect, it } from 'vitest'
import { Editor, Mark, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { applyDocxLink, docxLinkSelection } from './docx-links'
import { docxOperations, replayDocxOperations, type DocxAnchor } from './docx-operations'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+', renderHTML: () => ['div', 0] })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => ({ docxIndex: { default: null } }), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const Bold = Mark.create({ name: 'bold', renderHTML: () => ['strong', 0] })
const Italic = Mark.create({ name: 'italic', renderHTML: () => ['em', 0] })
const Link = Mark.create({ name: 'link', inclusive: false, addAttributes: () => ({ href: { default: '' }, rId: { default: null }, tooltip: { default: null }, plain: { default: false } }), renderHTML: ({ HTMLAttributes }) => ['a', HTMLAttributes, 0] })
const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'source', expectedObjectSha256: 'sha', editable: true }]
const editors: Editor[] = []
const makeEditor = (includeNew = false) => {
  const host = document.createElement('div'); document.body.append(host)
  const editor = new Editor({ element: host, editorProps: { handleScrollToSelection: () => true }, extensions: [Doc, Paragraph, Text, Bold, Italic, Link, UndoRedo], content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [
      { type: 'text', text: 'A😀', marks: [{ type: 'bold' }] }, { type: 'text', text: 'BC', marks: [{ type: 'italic' }] },
      { type: 'text', text: 'keep', marks: [{ type: 'link', attrs: { href: 'https://keep.test', tooltip: 'keep title', plain: true, rId: 'rId4' } }] },
    ] }, ...(includeNew ? [{ type: 'docParagraph', content: [{ type: 'text', text: 'new paragraph' }] }] : []),
  ] } })
  editors.push(editor); return editor
}
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
describe('source-anchored link selections', () => {
  it('links real UTF16 selection across styles, supports undo/redo and replays draft', () => {
    const editor = makeEditor(), original = editor.getJSON()
    editor.commands.setTextSelection({ from: 2, to: 5 })
    const target = docxLinkSelection(editor, anchors)!
    expect(target).toMatchObject({ from: 2, to: 5, hasLink: false })
    expect(applyDocxLink(editor, target, 'https://new.test')).toBe(true)
    const operations = docxOperations(original, editor.getJSON(), anchors)
    expect(operations).toEqual([{ kind: 'setParagraphLink', blockId: 'source', expectedObjectSha256: 'sha', from: 1, to: 4, href: 'https://new.test' }])
    expect(editor.commands.undo()).toBe(true)
    expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([])
    expect(editor.commands.redo()).toBe(true)
    const restored = replayDocxOperations(original, operations, anchors)
    editor.commands.setContent(restored, { emitUpdate: false })
    expect(docxOperations(original, editor.getJSON(), anchors)).toEqual(operations)
    expect(editor.getJSON().content![0].content!.at(-1)).toEqual(original.content![0].content!.at(-1))
  })
  it('edits and removes caret link while preserving target tooltip/plain', () => {
    const editor = makeEditor(), original = editor.getJSON()
    editor.commands.setTextSelection(8)
    const target = docxLinkSelection(editor, anchors)!
    expect(target).toMatchObject({ from: 6, to: 10, href: 'https://keep.test' })
    applyDocxLink(editor, target, 'mailto:reader@example.test')
    const edited = editor.getJSON().content![0].content!.at(-1)!
    expect(edited.marks![0].attrs).toMatchObject({ tooltip: 'keep title', plain: true, href: 'mailto:reader@example.test', rId: null })
    editor.commands.setTextSelection(8)
    expect(applyDocxLink(editor, docxLinkSelection(editor, anchors)!, null)).toBe(true)
    expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([{ kind: 'setParagraphLink', blockId: 'source', expectedObjectSha256: 'sha', from: 5, to: 9, href: null }])
  })
  it('rejects new paragraphs, cross-paragraph selections, surrogate splits and stale dialogs', () => {
    const editor = makeEditor(true)
    editor.commands.setTextSelection({ from: 3, to: 4 })
    expect(docxLinkSelection(editor, anchors)).toBeUndefined()
    editor.commands.setTextSelection({ from: 12, to: 15 })
    expect(docxLinkSelection(editor, anchors)).toBeUndefined()
    editor.commands.setTextSelection({ from: 2, to: 13 })
    expect(docxLinkSelection(editor, anchors)).toBeUndefined()
    editor.commands.setTextSelection({ from: 2, to: 5 })
    const target = docxLinkSelection(editor, anchors)!
    editor.commands.insertContent('changed')
    expect(() => applyDocxLink(editor, target, 'https://new.test')).toThrow(/选区已改变/)
    editor.setEditable(false)
    expect(docxLinkSelection(editor, anchors)).toBeUndefined()
  })
})
