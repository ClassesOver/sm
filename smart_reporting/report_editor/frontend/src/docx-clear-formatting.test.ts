import { afterEach, expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import * as operations from './docx-operations'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeTableStructure } from './docx-tables'
import { createDocxRibbon } from './docx-ribbon'
import { flushSync } from 'react-dom'
import { Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { applyDocxClearFormatting, docxClearFormattingUnavailable } from './docx-clear-formatting'
import type { DocxPmNode } from './docx-operations'

const editors: Editor[] = []
afterEach(() => editors.splice(0).forEach(editor => editor.destroy()))
function fixture(node: DocxPmNode) {
  const editor = new Editor({ extensions: [...editorExtensions, NativeTableStructure], content: { type: 'doc', content: [node] } })
  editors.push(editor)
  return { schema: editor.schema, node: editor.getJSON().content![0] as DocxPmNode }
}
const project = (...args: unknown[]): DocxPmNode => {
  const fn = (operations as unknown as Record<string, unknown>).projectClearedDocxParagraph
  expect(fn, 'native clear-all projection must exist before enabling the command').toBeTypeOf('function')
  return (fn as (...args: unknown[]) => DocxPmNode)(...args)
}

it('clears selected marks, restores default paragraph style and sheds majority formatting like upstream', () => {
  const { node, schema } = fixture({ type: 'docHeading', attrs: { docxIndex: 0, styleId: 'Heading1', align: 'center', indentLeft: 720, spaceAfter: 240, pageBreakBefore: true }, content: [
    { type: 'text', text: 'abcd', marks: [{ type: 'bold' }, { type: 'italic' }, { type: 'docTextStyle', attrs: { color: '112233', highlight: 'yellow' } }] },
    { type: 'text', text: 'ef', marks: [{ type: 'italic' }] },
  ] })
  const cleared = project(node, [{ from: 0, to: 1 }], 'Normal', schema)
  expect(cleared.type).toBe('docParagraph')
  expect(cleared.attrs).toMatchObject({ docxIndex: 0, styleId: 'Normal', align: null, indentLeft: null, spaceAfter: null, pageBreakBefore: false })
  // After clearing a: bold/color cover exactly half (kept), italic covers >half (removed everywhere).
  expect(cleared.content).toEqual([
    { type: 'text', text: 'a' },
    { type: 'text', text: 'bcd', marks: [expect.objectContaining({ type: 'bold' }), expect.objectContaining({ type: 'docTextStyle', attrs: expect.objectContaining({ color: '112233', highlight: 'yellow' }) })] },
    { type: 'text', text: 'ef' },
  ])
})

it('keeps list numbering and supports an empty paragraph without manufacturing text', () => {
  const { node, schema } = fixture({ type: 'docListItem', attrs: { docxIndex: 2, kind: 'ordered', numId: '17', ilvl: 2, styleId: 'ListParagraph', indentFirstLine: -360 } })
  const cleared = project(node, [{ from: 0, to: 0 }], 'Normal', schema)
  expect(cleared.type).toBe('docListItem')
  expect(cleared.attrs).toMatchObject({ kind: 'ordered', numId: '17', ilvl: 2, indentFirstLine: null, styleId: 'Normal' })
  expect(cleared.content ?? []).toEqual([])
})

it('removes hyperlinks only in the selection and validates UTF-16 boundaries', () => {
  const { node, schema } = fixture({ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'A😀B', marks: [{ type: 'link', attrs: { href: 'https://example.com' } }] }] })
  const cleared = project(node, [{ from: 1, to: 3 }], null, schema)
  expect(cleared.content?.map(run => [run.text, run.marks?.some(mark => mark.type === 'link') ?? false])).toEqual([['A', true], ['😀', false], ['B', true]])
  expect(() => project(node, [{ from: 1, to: 2 }], null, schema)).toThrow(/范围/)
  expect(() => project(node, [{ from: 0, to: 0 }], null, schema)).toThrow(/范围/)
})

it('records one atomic clear operation and replays it with source identity and projection checks', () => {
  const { node, schema } = fixture({ type: 'docHeading', attrs: { docxIndex: 0, styleId: 'Heading1', align: 'right' }, content: [{ type: 'text', text: 'abcd', marks: [{ type: 'bold' }] }] })
  const baseline: DocxPmNode = { type: 'doc', content: [node] }
  const anchor = { docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha0', editable: true }
  const ranges = [{ from: 0, to: 4 }]
  const cleared = project(node, ranges, null, schema)
  cleared.attrs = { ...cleared.attrs, nativeClearFormatting: { ranges } }
  const after: DocxPmNode = { type: 'doc', content: [cleared] }
  const op = { kind: 'clearParagraphFormatting', blockId: 'p0', expectedObjectSha256: 'sha0', ranges }
  expect(operations.docxOperations(baseline, after, [anchor], undefined, schema)).toEqual([op])
  const restored = operations.replayDocxOperations(baseline, [op], [anchor], undefined, schema)
  expect(schema.nodeFromJSON(restored).eq(schema.nodeFromJSON(after))).toBe(true)
  const forged = structuredClone(after); forged.content![0].content![0].text = 'forged'
  expect(() => operations.docxOperations(baseline, forged, [anchor], undefined, schema)).toThrow(/清除格式/)
  expect(() => operations.replayDocxOperations(baseline, [{ ...op, expectedObjectSha256: 'stale' }], [anchor], undefined, schema)).toThrow()
  expect(() => operations.replayDocxOperations(baseline, [op, { kind: 'replaceParagraph', blockId: 'p0', expectedObjectSha256: 'sha0', text: 'forged' }], [anchor], undefined, schema)).toThrow()
})

it('clears a collapsed caret paragraph through the ribbon in one guarded undo step', () => {
  let baseline: DocxPmNode | undefined
  const anchors = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha0', editable: true }]
  const rejected: string[] = []
  const Guard = Extension.create({ name: 'clearGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) {
    if (!baseline || !tr.docChanged) return true
    try { operations.docxOperations(baseline, tr.doc.toJSON() as DocxPmNode, anchors, undefined, editor.schema); return true } catch (error) { rejected.push((error as Error).message); return false }
  } })] })
  const editor = new Editor({ extensions: [...editorExtensions, NativeTableStructure, Guard], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, align: 'center' }, content: [{ type: 'text', text: 'abcd', marks: [{ type: 'bold' }] }] }] } })
  editors.push(editor); baseline = editor.getJSON() as DocxPmNode
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, anchors)
  const button = () => ribbon.querySelector<HTMLButtonElement>('[data-action="clear-formatting"]')!
  editor.commands.setTextSelection(3)
  expect(button().disabled).toBe(false)
  flushSync(() => button().click())
  expect(rejected).toEqual([])
  expect(editor.state.selection.from).toBe(3)
  expect(editor.getJSON().content![0].attrs!.align).toBeNull()
  expect(editor.getJSON().content![0].content![0].marks).toBeUndefined()
  editor.commands.undo(); expect(editor.getJSON()).toEqual(baseline)
  editor.commands.redo(); expect(editor.getJSON().content![0].content![0].marks).toBeUndefined()
  editor.setEditable(false); expect(button().disabled).toBe(true)
})

it('supports select-all across headings and lists, and sequential clear selections replay identically', () => {
  const editor = new Editor({ extensions: [...editorExtensions, NativeTableStructure], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docHeading', attrs: { docxIndex: 0, styleId: 'Heading1' }, content: [{ type: 'text', text: 'abcdef', marks: [{ type: 'bold' }] }] },
    { type: 'docListItem', attrs: { docxIndex: 1, numId: '7', kind: 'ordered' }, content: [{ type: 'text', text: 'list', marks: [{ type: 'italic' }] }] },
  ] } })
  editors.push(editor)
  const anchors = [0, 1].map(i => ({ docxIndex: i, blockId: `p${i}`, expectedObjectSha256: `sha${i}`, editable: true }))
  const baseline = editor.getJSON() as DocxPmNode
  editor.commands.setTextSelection({ from: 1, to: 2 }); applyDocxClearFormatting(editor, true, anchors)
  editor.commands.setTextSelection({ from: 4, to: 5 }); applyDocxClearFormatting(editor, true, anchors)
  let ops = operations.docxOperations(baseline, editor.getJSON() as DocxPmNode, anchors, undefined, editor.schema)
  expect(ops[0].ranges).toEqual([{ from: 0, to: 1 }, { from: 3, to: 4 }])
  expect(editor.schema.nodeFromJSON(operations.replayDocxOperations(baseline, ops, anchors, undefined, editor.schema)).eq(editor.state.doc)).toBe(true)
  editor.commands.selectAll()
  expect(docxClearFormattingUnavailable(editor, true, anchors)).toBeNull()
  applyDocxClearFormatting(editor, true, anchors)
  ops = operations.docxOperations(baseline, editor.getJSON() as DocxPmNode, anchors, undefined, editor.schema)
  expect(ops).toHaveLength(2)
  expect(editor.getJSON().content![0].type).toBe('docParagraph')
  expect(editor.getJSON().content![1].attrs!.numId).toBe('7')
  expect(editor.schema.nodeFromJSON(operations.replayDocxOperations(baseline, ops, anchors, undefined, editor.schema)).eq(editor.state.doc)).toBe(true)
})
