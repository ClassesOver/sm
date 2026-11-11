import { afterEach, expect, it } from 'vitest'
import { Editor, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { applyParagraphBorders } from './docx-borders'
import { applyParagraphShading } from './docx-shading'
import { docxOperations, replayDocxOperations, type DocxAnchor } from './docx-operations'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => Object.fromEntries([
  'docxIndex', 'borders', 'borderLines', 'borderReset', 'borderPad', 'shadingFill', 'shadingClear', 'align', 'styleId', 'indentLeft', 'spaceBefore', 'pageBreakBefore',
].map(key => [key, { default: null }])), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha0', editable: true }]
const editors: Editor[] = []
function setup() {
  const editor = new Editor({ extensions: [Doc, Paragraph, Text, UndoRedo], editorProps: { handleScrollToSelection: () => true }, content: {
    type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '目标正文' }] }],
  } })
  editors.push(editor); editor.commands.setTextSelection(2)
  return editor
}
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })

it.each([false, true])('combines the two source attributes in either order, with separate undo and replay (%s)', borderFirst => {
  const editor = setup(), original = editor.getJSON()
  const border = () => expect(applyParagraphBorders(editor, anchors, { sides: 'b', color: 'FF0000', szPt: 1 })).toBe(true)
  const shade = () => expect(applyParagraphShading(editor, anchors, 'edf5fc')).toBe(true)
  const actions = borderFirst ? [border, shade] : [shade, border]
  actions[0]!(); const first = editor.getJSON(); actions[1]!(); const both = editor.getJSON()
  const operations = docxOperations(original, both, anchors)
  expect(operations.map(op => op.kind)).toEqual(['setParagraphShading', 'setParagraphBorders'])
  for (const ordered of [operations, [...operations].reverse()]) expect(replayDocxOperations(original, ordered, anchors)).toEqual(both)
  editor.commands.undo(); expect(editor.getJSON()).toEqual(first)
  editor.commands.undo(); expect(editor.getJSON()).toEqual(original)
  editor.commands.redo(); editor.commands.redo(); expect(editor.getJSON()).toEqual(both)
  for (const value of ['auto', 'none']) {
    applyParagraphShading(editor, anchors, value)
    const current = editor.getJSON(), ops = docxOperations(original, current, anchors)
    expect(replayDocxOperations(original, ops, anchors)).toEqual(current)
  }
  applyParagraphShading(editor, anchors, 'edf5fc'); applyParagraphBorders(editor, anchors, null)
  expect(docxOperations(original, editor.getJSON(), anchors).map(op => op.kind)).toEqual(['setParagraphShading'])
  applyParagraphBorders(editor, anchors, { sides: 't' })
  const cleared = editor.getJSON()
  applyParagraphShading(editor, anchors, 'none'); applyParagraphBorders(editor, anchors, null)
  const clearOps = docxOperations(cleared, editor.getJSON(), anchors)
  expect(clearOps.map(op => op.kind)).toEqual(['setParagraphShading', 'setParagraphBorders'])
  expect(replayDocxOperations(cleared, clearOps, anchors)).toEqual(editor.getJSON())
})

it('replays supported layout combinations while rejecting unsupported changes, duplicates, readonly and forged identities', () => {
  const editor = setup(), original = editor.getJSON()
  applyParagraphBorders(editor, anchors, { sides: 'b' }); applyParagraphShading(editor, anchors, 'edf5fc')
  const both = editor.getJSON(), ops = docxOperations(original, both, anchors)
  for (const [attrs, kind] of [
    [{ align: 'center' }, 'setParagraphAlignment'],
    [{ indentLeft: 720 }, 'setParagraphIndent'],
    [{ spaceBefore: 120, spaceBeforeAuto: null }, 'setParagraphSpacing'],
    [{ indentFirstLine: -480, indentFirstLineChars: null }, 'setParagraphSpecialIndent'],
  ] as const) {
    const changed = structuredClone(both); Object.assign(changed.content![0]!.attrs!, attrs)
    const combined = docxOperations(original, changed, anchors)
    expect(combined.map(op => op.kind)).toEqual([...ops.map(op => op.kind), kind])
    for (const ordered of [combined, [...combined].reverse()]) expect(replayDocxOperations(original, ordered, anchors)).toEqual(changed)
  }
  for (const attrs of [{ styleId: 'Heading1' }, { pageBreakBefore: true }, { keepLines: true }, { indentFirstLine: -480, indentFirstLineChars: 200 }]) {
    const changed = structuredClone(both); Object.assign(changed.content![0]!.attrs!, attrs)
    expect(() => docxOperations(original, changed, anchors)).toThrow()
  }
  const changed = structuredClone(both); changed.content![0]!.content![0] = { type: 'text', text: '目标正文!', marks: [] }
  expect(() => docxOperations(original, changed, anchors)).toThrow()
  for (const bad of [
    [...ops, { ...ops[0]! }], [...ops, { ...ops[1]! }],
    ops.map(op => ({ ...op, expectedObjectSha256: 'foreign' })),
    ops.map(op => ({ ...op, extra: 1 })),
    [...ops, { kind: 'insertNote', blockId: 'p0', expectedObjectSha256: 'sha0', noteKind: 'footnote', offset: 1, text: '注释' }],
  ]) expect(() => replayDocxOperations(original, bad, anchors)).toThrow()
  expect(() => replayDocxOperations(original, ops, [{ ...anchors[0]!, editable: false }])).toThrow()
  expect(() => docxOperations(original, both, [{ ...anchors[0]!, editable: false }])).toThrow()
  for (const key of ['borderReset', 'borderPad']) {
    const unsupported = structuredClone(original); unsupported.content![0]!.attrs![key] = true
    expect(() => replayDocxOperations(unsupported, ops, anchors)).toThrow()
  }
})

it('honors independent source capabilities for protected shading and borders', () => {
  const editor = setup(), original = editor.getJSON()
  const locked = [Object.assign({}, anchors[0], { paragraphShadingEditable: false, paragraphBordersEditable: false })]
  expect(applyParagraphShading(editor, locked, 'edf5fc')).toBe(false)
  expect(applyParagraphBorders(editor, locked, { sides: 'b' })).toBe(false)
  const ambiguous = [anchors[0]!, locked[0]!]
  expect(applyParagraphShading(editor, ambiguous, 'edf5fc')).toBe(false)
  expect(applyParagraphBorders(editor, ambiguous, { sides: 'b' })).toBe(false)
  applyParagraphShading(editor, anchors, 'edf5fc'); applyParagraphBorders(editor, anchors, { sides: 'b' })
  const current = editor.getJSON(), ops = docxOperations(original, current, anchors)
  expect(() => docxOperations(original, current, locked)).toThrow()
  for (const batch of [ops, [ops[0]!], [ops[1]!]]) expect(() => replayDocxOperations(original, batch, locked)).toThrow()
})
