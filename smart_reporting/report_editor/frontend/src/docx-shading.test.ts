import { afterEach, expect, it } from 'vitest'
import { Editor, Mark, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { applyParagraphShading, DOCX_SHADING_COLORS, paragraphShading, safeDocxShading } from './docx-shading'
import { docxOperations, replayDocxOperations, type DocxAnchor } from './docx-operations'

// The pinned editor schema (extensions.ts:342-346) carries shadingFill/shadingClear.
const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => ({
  docxIndex: { default: null }, shadingFill: { default: null }, shadingClear: { default: null }, shadingDisplay: { default: null },
}), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const Style = Mark.create({ name: 'docTextStyle', addAttributes: () => ({ rawRPr: { default: null } }), renderHTML: () => ['span', 0] })
const anchor0: DocxAnchor = { docxIndex: 0, blockId: 'body-0', expectedObjectSha256: 'sha-0', editable: true }
const anchor1: DocxAnchor = { docxIndex: 1, blockId: 'body-1', expectedObjectSha256: 'sha-1', editable: true }
const anchors = [anchor0, anchor1]
const editors: Editor[] = []
function setup() {
  const editor = new Editor({ extensions: [Doc, Paragraph, Text, Style, UndoRedo], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '底纹目标', marks: [{ type: 'docTextStyle', attrs: { rawRPr: '<w:rPr><w:noProof/></w:rPr>' } }] }] },
    { type: 'docParagraph', attrs: { docxIndex: 1, shadingFill: 'fff2cc' }, content: [{ type: 'text', text: '已有底纹' }] },
  ] } })
  editors.push(editor)
  editor.commands.setTextSelection(2)
  return editor
}
const node = (editor: Editor, index: number) => editor.getJSON().content![index]!
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })

it('validates fill, explicit auto and removal values from the source palette', () => {
  expect(safeDocxShading('EDF5FC')).toEqual({ fill: 'edf5fc', clear: false })
  expect(safeDocxShading(DOCX_SHADING_COLORS[9])).toEqual({ fill: DOCX_SHADING_COLORS[9]!.toLowerCase(), clear: false })
  expect(safeDocxShading('auto')).toEqual({ fill: null, clear: true })
  expect(safeDocxShading('none')).toEqual({ fill: null, clear: false })
  for (const invalid of ['#edf5fc', 'edf5f', 'edf5fcc', 'xyz123', 'auto2', 42, null, undefined]) expect(() => safeDocxShading(invalid)).toThrow('段落底纹颜色无效')
})

it('applies direct shading to the anchored paragraph, diffs one op and replays it back', () => {
  const editor = setup(), original = editor.getJSON()
  expect(applyParagraphShading(editor, anchors, 'edf5fc')).toBe(true)
  const current = editor.getJSON()
  expect(node(editor, 0).attrs).toMatchObject({ shadingFill: 'edf5fc', shadingClear: null })
  expect(node(editor, 1).attrs).toEqual(original.content![1]!.attrs)
  expect(paragraphShading(node(editor, 0))).toBe('edf5fc')
  const operation = { kind: 'setParagraphShading', blockId: 'body-0', expectedObjectSha256: 'sha-0', fill: 'edf5fc', clear: false }
  expect(docxOperations(original, current, anchors)).toEqual([operation])
  const restored = replayDocxOperations(original, [operation], anchors)
  expect(docxOperations(original, restored, anchors)).toEqual([operation])
  expect(restored.content![1]).toEqual(original.content![1])
  editor.commands.undo()
  expect(node(editor, 0).attrs).toEqual(original.content![0]!.attrs)
  editor.commands.redo()
  expect(paragraphShading(node(editor, 0))).toBe('edf5fc')
})

it('writes explicit auto and removal for an existing direct fill, each as its own undo step', () => {
  const editor = setup(), original = editor.getJSON()
  editor.commands.setTextSelection(8)
  expect(applyParagraphShading(editor, anchors, 'auto')).toBe(true)
  expect(node(editor, 1).attrs).toMatchObject({ shadingFill: null, shadingClear: true })
  expect(paragraphShading(node(editor, 1))).toBe('auto')
  const autoOp = { kind: 'setParagraphShading', blockId: 'body-1', expectedObjectSha256: 'sha-1', fill: null, clear: true }
  expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([autoOp])
  expect(applyParagraphShading(editor, anchors, 'none')).toBe(true)
  expect(node(editor, 1).attrs).toMatchObject({ shadingFill: null, shadingClear: null })
  expect(paragraphShading(node(editor, 1))).toBe('none')
  const noneOp = { kind: 'setParagraphShading', blockId: 'body-1', expectedObjectSha256: 'sha-1', fill: null, clear: false }
  expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([noneOp])
  editor.commands.undo()
  expect(paragraphShading(node(editor, 1))).toBe('auto')
})

it('refuses shading edits mixed with text or foreign ops and validates replay fields', () => {
  const editor = setup(), original = editor.getJSON()
  applyParagraphShading(editor, anchors, 'edf5fc')
  editor.commands.insertContentAt(3, '!')
  expect(() => docxOperations(original, editor.getJSON(), anchors)).toThrow('段落底纹修改请先保存')
  const valid = { kind: 'setParagraphShading', blockId: 'body-0', expectedObjectSha256: 'sha-0', fill: 'edf5fc', clear: false }
  expect(() => replayDocxOperations(original, [{ ...valid, fill: '#edf5fc' }], anchors)).toThrow('草稿段落底纹字段或来源身份无效')
  expect(() => replayDocxOperations(original, [{ ...valid, clear: 'yes' }], anchors)).toThrow('草稿段落底纹字段或来源身份无效')
  expect(() => replayDocxOperations(original, [{ ...valid, extra: 1 }], anchors)).toThrow('草稿段落底纹字段或来源身份无效')
  expect(() => replayDocxOperations(original, [valid, { kind: 'formatParagraph', blockId: 'body-0', expectedObjectSha256: 'sha-0', style: { bold: true } }], anchors)).toThrow('草稿段落底纹字段或来源身份无效')
  expect(() => replayDocxOperations(original, [valid, { ...valid }], anchors)).toThrow('草稿段落底纹字段或来源身份无效')
})
