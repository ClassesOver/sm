import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeTableStructure } from './docx-tables'
import { createParagraphStyleControl, projectParagraphStyle, type DocxStyleInfo } from './docx-styles'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'

const styles = new Map<string, DocxStyleInfo>([
  ['Normal', { styleId: 'Normal', name: 'Normal', type: 'paragraph', isDefault: true }],
  ['Heading1', { styleId: 'Heading1', name: 'heading 1', type: 'paragraph', basedOn: 'Normal', headingLevel: 1 }],
  ['Heading2', { styleId: 'Heading2', name: 'heading 2', type: 'paragraph', basedOn: 'Normal', headingLevel: 2 }],
])
const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha-0', editable: true }]
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function setup(node: DocxPmNode) {
  let baseline: DocxPmNode | undefined
  const rejected: string[] = []
  const Guard = Extension.create({ name: 'testNativeGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) {
    if (!baseline || !tr.docChanged) return true
    try { docxOperations(baseline, tr.doc.toJSON() as DocxPmNode, anchors, undefined, editor.schema, styles); return true } catch (error) { rejected.push((error as Error).message); return false }
  } })] })
  const host = document.createElement('div'); document.body.append(host)
  const editor = new Editor({ element: host, extensions: [...editorExtensions, NativeTableStructure, Guard], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [node] } })
  editors.push(editor)
  ;(editor.storage as any).listNumbering.styles = styles
  baseline = editor.getJSON() as DocxPmNode
  const control = createParagraphStyleControl(editor, true, anchors); document.body.append(control)
  const choose = (value: string) => { editor.commands.setTextSelection(1); control.focus(); control.value = value; control.dispatchEvent(new Event('change')) }
  return { editor, baseline, rejected, choose }
}

it('turns a body paragraph into a heading of the style level and replays it', () => {
  const f = setup({ type: 'docParagraph', attrs: { docxIndex: 0, styleId: 'Normal' }, content: [{ type: 'text', text: '概述' }] })
  f.choose('Heading2')
  expect(f.rejected).toEqual([])
  const node = f.editor.getJSON().content![0]!
  expect([node.type, node.attrs!.level, node.attrs!.styleId, node.attrs!.docxIndex]).toEqual(['docHeading', 2, 'Heading2', 0])
  const ops = docxOperations(f.baseline, f.editor.getJSON() as DocxPmNode, anchors, undefined, f.editor.schema, styles)
  expect(ops).toEqual([{ kind: 'setParagraphStyle', blockId: 'p0', expectedObjectSha256: 'sha-0', styleId: 'Heading2' }])
  const restored = replayDocxOperations(f.baseline, ops, anchors, undefined, f.editor.schema, styles)
  expect(f.editor.schema.nodeFromJSON(restored).eq(f.editor.state.doc)).toBe(true)
})

it('turns a heading back into a body paragraph and refuses mixing it with a text edit', () => {
  const f = setup({ type: 'docHeading', attrs: { docxIndex: 0, styleId: 'Heading1', level: 1 }, content: [{ type: 'text', text: '标题' }] })
  f.choose('Normal')
  expect(f.editor.getJSON().content![0]!.type).toBe('docParagraph')
  expect(docxOperations(f.baseline, f.editor.getJSON() as DocxPmNode, anchors, undefined, f.editor.schema, styles)).toEqual([{ kind: 'setParagraphStyle', blockId: 'p0', expectedObjectSha256: 'sha-0', styleId: 'Normal' }])
  f.editor.chain().setTextSelection(2).insertContent('改').run()
  expect(f.rejected.some(message => /先保存/.test(message))).toBe(true)
  expect(() => projectParagraphStyle(f.baseline.content![0]!, 'Heading1', styles)).not.toThrow()
})
