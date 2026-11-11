import { expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { normalizePlainDocxRuns, replayPlainDocxRuns } from './docx-plain-paragraph-runs'
import type { DocxPmNode } from './docx-operations'

it('无全局注释模型的纯来源改字和局部粗体复用最终run并可恢复', () => {
  const anchors = [{ docxIndex: 0, blockId: 'plain', expectedObjectSha256: 'sha', editable: true }]
  const editor = new Editor({ extensions: editorExtensions, editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'A😀BC' }] }] } })
  try {
    const baseline = editor.getJSON() as DocxPmNode
    editor.commands.insertContentAt(4, '新增'); editor.chain().setTextSelection({ from: 4, to: 6 }).setMark('bold').run()
    const result = normalizePlainDocxRuns(baseline, editor.getJSON(), anchors)
    expect(result.operations.map(op => op.kind)).toEqual(['patchParagraphRuns'])
    const restored = replayPlainDocxRuns(baseline, result.operations, anchors)
    expect(editor.schema.nodeFromJSON(restored).content.eq(editor.state.doc.content)).toBe(true)
    expect(() => normalizePlainDocxRuns(baseline, editor.getJSON(), [{ ...anchors[0], editable: false }])).toThrow()
    expect(() => replayPlainDocxRuns(baseline, result.operations.map(op => ({ ...op, expectedObjectSha256: 'foreign' })), anchors)).toThrow()
    expect(() => normalizePlainDocxRuns(baseline, { ...editor.getJSON(), attrs: { nativeNotesOperations: [{ kind: 'insertNote' }] } }, anchors)).toThrow(/未提供/)
    expect(() => replayPlainDocxRuns(baseline, [{ ...result.operations[0], runs: [{ noteOperationIndex: 0 }] }], anchors)).toThrow(/不能包含/)
  } finally { editor.destroy() }
})

it('纯run恢复不重编号未改动的未知来源注释引用，并拒绝未知内联对象改写', () => {
  const source: DocxPmNode = { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'docNoteRef', attrs: { kind: 'footnote', id: '999', num: 7, rawRPr: null } }] },
    { type: 'docParagraph', attrs: { docxIndex: 1 }, content: [{ type: 'text', text: 'plain' }] },
  ] }
  const anchors = [{ docxIndex: 0, blockId: 'unknown-note', expectedObjectSha256: 'note-sha', editable: false }, { docxIndex: 1, blockId: 'plain', expectedObjectSha256: 'plain-sha', editable: true }]
  const plans = [{ kind: 'patchParagraphRuns', blockId: 'plain', expectedObjectSha256: 'plain-sha', runs: [{ sourceFrom: 0, sourceTo: 5 }, { text: 'new', inheritFrom: 4, style: { bold: true } }] }]
  const restored = replayPlainDocxRuns(source, plans, anchors)
  expect(restored.content![0]).toEqual(source.content![0])
  const unknown = structuredClone(source); unknown.content![1].content!.push({ type: 'docInlineMath', attrs: { omml: 'unknown' } })
  expect(() => normalizePlainDocxRuns(source, unknown, anchors)).toThrow()
})
