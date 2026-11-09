import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeTableStructure } from './docx-tables'
import { docxOperations, formatRangeChanges, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'

const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha-0', editable: true }]
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()) })
function setup(content: DocxPmNode[] = [{ type: 'text', text: '前半部分后半部分' }]) {
  let baseline: DocxPmNode | undefined
  const rejected: string[] = []
  const Guard = Extension.create({ name: 'testNativeGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) {
    if (!baseline || !tr.docChanged) return true
    try { docxOperations(baseline, tr.doc.toJSON() as DocxPmNode, anchors, undefined, editor.schema); return true } catch (error) { rejected.push((error as Error).message); return false }
  } })] })
  const editor = new Editor({ extensions: [...editorExtensions, NativeTableStructure, Guard], editorProps: { handleScrollToSelection: () => true },
    content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content }] } })
  editors.push(editor)
  baseline = editor.getJSON() as DocxPmNode
  return { editor, baseline, rejected }
}
const ops = (f: ReturnType<typeof setup>) => docxOperations(f.baseline, f.editor.getJSON() as DocxPmNode, anchors, undefined, f.editor.schema)

it('saves bold and color on part of a paragraph as minimal ranges and replays them', () => {
  const f = setup()
  f.editor.chain().setTextSelection({ from: 3, to: 5 }).toggleMark('bold').run()
  f.editor.chain().setTextSelection({ from: 7, to: 9 }).setMark('docTextStyle', { color: 'C00000' }).run()
  expect(f.rejected).toEqual([])
  const result = ops(f)
  expect(result).toEqual([
    { kind: 'formatRange', blockId: 'p0', expectedObjectSha256: 'sha-0', from: 2, to: 4, style: { bold: true } },
    { kind: 'formatRange', blockId: 'p0', expectedObjectSha256: 'sha-0', from: 6, to: 8, style: { color: 'C00000' } },
  ])
  const restored = replayDocxOperations(f.baseline, result, anchors, undefined, f.editor.schema)
  expect(f.editor.schema.nodeFromJSON(restored).eq(f.editor.state.doc)).toBe(true)
  expect(docxOperations(f.baseline, restored, anchors, undefined, f.editor.schema)).toEqual(result)
})

it('unbolds part of a mixed paragraph and keeps whole-paragraph changes as formatParagraph', () => {
  const f = setup([{ type: 'text', text: '粗体', marks: [{ type: 'bold' }] }, { type: 'text', text: '普通' }])
  f.editor.chain().setTextSelection({ from: 1, to: 2 }).toggleMark('bold').run()
  expect(ops(f)).toEqual([{ kind: 'formatRange', blockId: 'p0', expectedObjectSha256: 'sha-0', from: 0, to: 1, style: { bold: false } }])
  const g = setup()
  g.editor.chain().selectAll().toggleMark('italic').run()
  expect(ops(g)).toEqual([{ kind: 'formatParagraph', blockId: 'p0', expectedObjectSha256: 'sha-0', style: { italic: true } }])
})

it('refuses clearing a local color, and local formatting together with a text edit in the same paragraph', () => {
  const colored = { type: 'docParagraph', content: [{ type: 'text', text: 'ab', marks: [{ type: 'docTextStyle', attrs: { color: '#112233' } }] }, { type: 'text', text: 'cd' }] }
  expect(() => formatRangeChanges(colored, { type: 'docParagraph', content: [{ type: 'text', text: 'abcd' }] })).toThrow(/清除/)
  const f = setup()
  f.editor.chain().setTextSelection(9).insertContent('尾').run()
  f.editor.chain().setTextSelection({ from: 1, to: 3 }).toggleMark('bold').run()
  expect(f.rejected.some(message => /先保存/.test(message))).toBe(true)
})
