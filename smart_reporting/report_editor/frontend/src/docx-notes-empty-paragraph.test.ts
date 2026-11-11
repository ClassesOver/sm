import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { normalizeDocxNotes, replayDocxNotes, type DocxNotesModel } from './docx-notes'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import { parseDocx, readSections } from '@genoffice/docx-engine'
import { buildDocx } from '../../../reporting/doc_engine/packages/docx-engine/tests/helpers/build-docx'
import { blocksToPmDoc, pmDocOptions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import { sourceEmptyDocxParagraphs } from './docx-empty-paragraph'

const editors: Editor[] = []
const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'empty', expectedObjectSha256: 'empty-sha', editable: true }]
const model: DocxNotesModel = { footnotes: [], endnotes: [], referenceBlocks: [{ blockId: 'empty', expectedObjectSha256: 'empty-sha', editable: true }] }
const Intent = Extension.create({ name: 'emptyNoteIntent', addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeNotesOperations: { default: null, rendered: false } } }] })
afterEach(() => editors.splice(0).forEach(editor => editor.destroy()))
it.each([null, 'EmptyBody'])('空来源段落style=%s输入后插注，使用来源0默认run而非客户端rawPr', styleId => {
  const editor = new Editor({ extensions: [...editorExtensions, Intent], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, styleId } }] } })
  editors.push(editor)
  const baseline = editor.getJSON() as DocxPmNode
  editor.commands.insertContentAt(1, '新增😀')
  const operations = [{ kind: 'insertNote', noteKind: 'footnote', blockId: 'empty', expectedObjectSha256: 'empty-sha', offset: 4, text: '空来源脚注' }]
  const next = replayDocxNotes(editor.getJSON(), operations, anchors, model)
  editor.view.dispatch(editor.state.tr.replaceWith(0, editor.state.doc.content.size, editor.schema.nodeFromJSON(next).content).setDocAttribute('nativeNotesOperations', operations))
  expect(editor.getText()).toBe('新增😀')
  const normalized = normalizeDocxNotes(baseline, editor.getJSON(), anchors, model)
  expect(normalized.operations[0]).toMatchObject({ kind: 'patchParagraphRuns', blockId: 'empty', runs: [{ text: '新增😀', inheritFrom: 0 }, { noteOperationIndex: 0 }] })
  const notes = normalized.operations.filter(op => op.kind !== 'patchParagraphRuns'), plans = normalized.operations.filter(op => op.kind === 'patchParagraphRuns')
  const restored = replayDocxNotes(baseline, notes, anchors, model, plans)
  expect(editor.schema.nodeFromJSON(restored).content.eq(editor.state.doc.content)).toBe(true)
})

it('真实XML多个空run与段落标记逐属性继承，键入和刷新均保留opaque格式', async () => {
  const parsed = await parseDocx(await buildDocx({ bodyXml: '<w:p><w:pPr><w:rPr><w:sz w:val="18"/></w:rPr></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="44"/><w:i/><w:noProof/></w:rPr></w:r><w:r><w:rPr><w:b/></w:rPr></w:r></w:p>' }))
  expect(parsed.blocks[0].runs).toEqual([])
  expect(parsed.blocks[0].emptyRun).toMatchObject({ font: 'Arial', sizeHalfPoints: 18, italic: true, bold: true })
  expect(parsed.blocks[0].emptyRun?.rawRPr).toContain('<w:noProof/>')
  const content = sourceEmptyDocxParagraphs(blocksToPmDoc(parsed.blocks, readSections(parsed), pmDocOptions(parsed)) as DocxPmNode, parsed.blocks)
  const editor = new Editor({ extensions: [...editorExtensions, Intent], editorProps: { handleScrollToSelection: () => true }, content })
  editors.push(editor)
  const baseline = editor.getJSON() as DocxPmNode
  editor.commands.setTextSelection(1)
  editor.view.dispatch(editor.state.tr.insertText('新增😀'))
  const text = editor.getJSON().content![0].content![0] as DocxPmNode
  expect(text.marks?.some(mark => mark.type === 'italic')).toBe(true)
  expect(text.marks?.some(mark => mark.type === 'bold')).toBe(true)
  expect(text.marks?.find(mark => mark.type === 'docTextStyle')?.attrs).toMatchObject({ font: 'Arial', sizeHalfPoints: 18 })
  const operations = [{ kind: 'insertNote', noteKind: 'footnote', blockId: 'empty', expectedObjectSha256: 'empty-sha', offset: 4, text: '空段脚注' }]
  const changed = replayDocxNotes(editor.getJSON(), operations, anchors, model)
  const normalized = normalizeDocxNotes(baseline, changed, anchors, model)
  const notes = normalized.operations.filter(op => op.kind !== 'patchParagraphRuns'), plans = normalized.operations.filter(op => op.kind === 'patchParagraphRuns')
  expect(plans[0].runs[0]).toEqual({ text: '新增😀', inheritFrom: 0 })
  const restored = replayDocxNotes(baseline, notes, anchors, model, plans)
  expect(editor.schema.nodeFromJSON(restored).content.eq(editor.schema.nodeFromJSON(changed).content)).toBe(true)
})
