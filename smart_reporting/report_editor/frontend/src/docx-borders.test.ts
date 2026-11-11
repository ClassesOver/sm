import { afterEach, expect, it } from 'vitest'
import { Editor, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { applyParagraphBorders, docxBorderAttrs, paragraphBorders, safeDocxBorderSpec, safeDocxBorders } from './docx-borders'
import { docxOperations, replayDocxOperations, type DocxAnchor } from './docx-operations'

// The pinned editor schema (extensions.ts:357-362) carries borders/borderLines
// (plus the display-only borderReset/borderPad the bridge refuses to rewrite).
const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => ({
  docxIndex: { default: null }, borders: { default: null }, borderLines: { default: null }, borderReset: { default: null }, borderPad: { default: null },
}), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const anchor0: DocxAnchor = { docxIndex: 0, blockId: 'body-0', expectedObjectSha256: 'sha-0', editable: true }
const anchor1: DocxAnchor = { docxIndex: 1, blockId: 'body-1', expectedObjectSha256: 'sha-1', editable: true }
const anchors = [anchor0, anchor1]
const editors: Editor[] = []
function setup() {
  const editor = new Editor({ extensions: [Doc, Paragraph, Text, UndoRedo], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '边框目标' }] },
    { type: 'docParagraph', attrs: { docxIndex: 1, borders: 't', borderLines: '{"t":{"color":"FF0000","szPt":0.5}}' }, content: [{ type: 'text', text: '已有边框' }] },
  ] } })
  editors.push(editor)
  editor.commands.setTextSelection(2)
  return editor
}
const node = (editor: Editor, index: number) => editor.getJSON().content![index]!
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })

it('validates pen input into canonical per-side single lines', () => {
  expect(safeDocxBorders(null)).toBeNull()
  expect(safeDocxBorders({ sides: 'tblr', color: 'edf5fc', szPt: 0.5 })).toEqual([
    { side: 'top', val: 'single', color: 'EDF5FC', szPt: 0.5 },
    { side: 'bottom', val: 'single', color: 'EDF5FC', szPt: 0.5 },
    { side: 'left', val: 'single', color: 'EDF5FC', szPt: 0.5 },
    { side: 'right', val: 'single', color: 'EDF5FC', szPt: 0.5 },
  ])
  expect(safeDocxBorders({ sides: 'b' })).toEqual([{ side: 'bottom', val: 'single' }])
  for (const invalid of [{ sides: '' }, { sides: 'bt' }, { sides: 'x' }, { sides: 'tt' }, { sides: 7 }, { sides: 'b', color: '#fff' }, { sides: 'b', szPt: 0 }, { sides: 'b', szPt: 0.3 }, { sides: 'b', szPt: 13 }, { sides: 'b', spacePt: 32 }, { sides: 'b', extra: 1 }, 'b', []]) {
    expect(() => safeDocxBorders(invalid), JSON.stringify(invalid)).toThrow('段落边框')
  }
  expect(() => safeDocxBorderSpec([])).toThrow('段落边框无效')
  expect(() => safeDocxBorderSpec([{ side: 'bottom', val: 'double' }])).toThrow('段落边框线型无效')
  expect(() => safeDocxBorderSpec([{ side: 'bottom', val: 'single' }, { side: 'bottom', val: 'single' }])).toThrow('段落边框位置无效')
  expect(() => safeDocxBorderSpec([{ side: 'between', val: 'single' }])).toThrow('段落边框位置无效')
  expect(() => safeDocxBorderSpec([{ side: 'bottom', val: 'single', themeColor: 'accent1' }])).toThrow('段落边框字段无效')
})

it('applies direct borders to the anchored paragraph, diffs one op and replays it back', () => {
  const editor = setup(), original = editor.getJSON()
  expect(applyParagraphBorders(editor, anchors, { sides: 'b', color: 'ff0000', szPt: 1 })).toBe(true)
  const current = editor.getJSON()
  expect(node(editor, 0).attrs).toMatchObject({ borders: 'b', borderLines: '{"b":{"color":"FF0000","szPt":1}}' })
  expect(node(editor, 1).attrs).toEqual(original.content![1]!.attrs)
  expect(paragraphBorders(node(editor, 0))).toEqual([{ side: 'bottom', val: 'single', color: 'FF0000', szPt: 1 }])
  const operation = { kind: 'setParagraphBorders', blockId: 'body-0', expectedObjectSha256: 'sha-0', borders: [{ side: 'bottom', val: 'single', color: 'FF0000', szPt: 1 }] }
  expect(docxOperations(original, current, anchors)).toEqual([operation])
  const restored = replayDocxOperations(original, [operation], anchors)
  expect(docxOperations(original, restored, anchors)).toEqual([operation])
  expect(restored.content![1]).toEqual(original.content![1])
  editor.commands.undo()
  expect(node(editor, 0).attrs).toEqual(original.content![0]!.attrs)
  editor.commands.redo()
  expect(paragraphBorders(node(editor, 0))).toEqual([{ side: 'bottom', val: 'single', color: 'FF0000', szPt: 1 }])
})

it('writes box borders and clears them again, each as its own undo step', () => {
  const editor = setup(), original = editor.getJSON()
  editor.commands.setTextSelection(12)
  expect(applyParagraphBorders(editor, anchors, { sides: 'tblr', color: '000000', szPt: 0.5 })).toBe(true)
  expect(node(editor, 1).attrs!.borders).toBe('tblr')
  const boxOp = { kind: 'setParagraphBorders', blockId: 'body-1', expectedObjectSha256: 'sha-1', borders: safeDocxBorderSpec(paragraphBorders(node(editor, 1))) }
  expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([boxOp])
  expect(boxOp.borders).toHaveLength(4)
  expect(applyParagraphBorders(editor, anchors, null)).toBe(true)
  expect(node(editor, 1).attrs).toMatchObject({ borders: null, borderLines: null })
  const clearOp = { kind: 'setParagraphBorders', blockId: 'body-1', expectedObjectSha256: 'sha-1', borders: null }
  expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([clearOp])
  editor.commands.undo()
  expect(node(editor, 1).attrs!.borders).toBe('tblr')
})

it('refuses border edits mixed with text or foreign ops and validates replay fields', () => {
  const editor = setup(), original = editor.getJSON()
  applyParagraphBorders(editor, anchors, { sides: 'b', color: '000000' })
  editor.commands.insertContentAt(3, '!')
  expect(() => docxOperations(original, editor.getJSON(), anchors)).toThrow('段落边框修改请先保存')
  const valid = { kind: 'setParagraphBorders', blockId: 'body-0', expectedObjectSha256: 'sha-0', borders: [{ side: 'bottom', val: 'single', color: '000000', szPt: 0.5 }] }
  expect(() => replayDocxOperations(original, [{ ...valid, borders: [{ side: 'bottom', val: 'double' }] }], anchors)).toThrow('草稿段落边框字段或来源身份无效')
  expect(() => replayDocxOperations(original, [{ ...valid, borders: [{ side: 'bottom', val: 'single', szPt: 0.3 }] }], anchors)).toThrow('草稿段落边框字段或来源身份无效')
  expect(() => replayDocxOperations(original, [{ ...valid, borders: [{ side: 'bottom', val: 'single' }], extra: 1 }], anchors)).toThrow('草稿段落边框字段或来源身份无效')
  expect(() => replayDocxOperations(original, [valid, { kind: 'formatParagraph', blockId: 'body-0', expectedObjectSha256: 'sha-0', style: { bold: true } }], anchors)).toThrow('草稿段落边框字段或来源身份无效')
  expect(() => replayDocxOperations(original, [valid, { ...valid }], anchors)).toThrow('草稿段落边框字段或来源身份无效')
  expect(() => replayDocxOperations(original, [{ ...valid, expectedObjectSha256: 'foreign' }], anchors)).toThrow('草稿段落边框字段或来源身份无效')
})

it('keeps border commands locked while saving or viewing readonly documents', () => {
  const editor = setup()
  editor.setEditable(false)
  expect(applyParagraphBorders(editor, anchors, { sides: 'b' })).toBe(false)
  expect(node(editor, 0).attrs!.borders).toBeNull()
  const foreign = [{ docxIndex: 0, blockId: 'body-0', expectedObjectSha256: 'sha-0', editable: false }]
  expect(applyParagraphBorders(editor, foreign, { sides: 'b' })).toBe(false)
})

it('round-trips attrs through the strict bridge protocol form', () => {
  const spec = safeDocxBorders({ sides: 'tb', color: '00B050', szPt: 1.5, spacePt: 1 })
  expect(docxBorderAttrs(spec)).toEqual({ borders: 'tb', borderLines: '{"t":{"color":"00B050","szPt":1.5,"spacePt":1},"b":{"color":"00B050","szPt":1.5,"spacePt":1}}' })
  expect(docxBorderAttrs(null)).toEqual({ borders: null, borderLines: null })
  expect(() => docxBorderAttrs([{ side: 'bottom', val: 'thick' } as never])).toThrow('段落边框无效')
})
