import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { applyDocxNotesIntent, normalizeDocxNotes, replayDocxNotes, type DocxNoteOperation, type DocxNotesModel } from './docx-notes'
import type { DocxAnchor, DocxPmNode } from './docx-operations'

// 独立 RED：真实 PM 事务产生同一段落的正文与注释混编，暂不接入生产 Guard。
const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'body', expectedObjectSha256: 'body-sha', editable: true }]
const NativeNotes = Extension.create({ name: 'inlineNoteTestIntent', addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeNotesOperations: { default: null, rendered: false } } }] })
const editors: Editor[] = []
afterEach(() => editors.splice(0).forEach(editor => editor.destroy()))
function setup(existing = false) {
  const model: DocxNotesModel = { footnotes: existing ? [{ id: '1', text: '来源脚注', expectedNoteSha256: 'note-sha', editable: true, references: [{ blockId: 'body', expectedObjectSha256: 'body-sha', referenceIndex: 0 }] }] : [], endnotes: [], referenceBlocks: [{ blockId: 'body', expectedObjectSha256: 'body-sha', editable: true }] }
  const editor = new Editor({ extensions: [...editorExtensions, NativeNotes], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [
    { type: 'text', text: 'A😀', marks: [{ type: 'bold' }, { type: 'docTextStyle', attrs: { rawRPr: '<w:rPr><w:noProof/></w:rPr>', font: 'Calibri' } }] },
    ...(existing ? [{ type: 'docNoteRef', attrs: { kind: 'footnote', id: '1', num: 1, rawRPr: null } }] : []),
    { type: 'text', text: 'BC尾', marks: [{ type: 'italic' }] },
  ] }] } })
  editors.push(editor)
  const baseline = editor.getJSON() as DocxPmNode
  const apply = (operations: DocxNoteOperation[]) => {
    const next = editor.schema.nodeFromJSON(replayDocxNotes(editor.getJSON(), operations, anchors, model))
    editor.view.dispatch(editor.state.tr.replaceWith(0, editor.state.doc.content.size, next.content).setDocAttribute('nativeNotesOperations', operations))
  }
  return { editor, baseline, model, apply }
}
const insertion = (offset: number): DocxNoteOperation => ({ kind: 'insertNote', noteKind: 'footnote', blockId: 'body', expectedObjectSha256: 'body-sha', offset, text: '新增脚注' })
function compile(f: ReturnType<typeof setup>) {
  const result = normalizeDocxNotes(f.baseline, f.editor.getJSON(), anchors, f.model)
  expect(result.current.content).toEqual(result.baseline.content)
  expect(result.operations.some(operation => operation.kind === 'patchParagraphRuns')).toBe(true)
  const plans = result.operations.filter(op => op.kind === 'patchParagraphRuns'), notes = result.operations.filter(op => op.kind !== 'patchParagraphRuns')
  const restored = replayDocxNotes(f.baseline, notes, anchors, f.model, plans)
  expect(f.editor.schema.nodeFromJSON(restored).content.eq(f.editor.state.doc.content)).toBe(true)
  expect(normalizeDocxNotes(f.baseline, restored, anchors, f.model).operations).toEqual(result.operations)
  return result.operations
}

it('先改同段文字再在当前UTF16位置插注，不能将当前offset误当来源offset', () => {
  const f = setup()
  f.editor.commands.insertContentAt(4, '新增')
  f.apply([insertion(5)])
  const content = f.editor.getJSON().content![0].content!
  expect(content.map(node => node.type === 'text' && 'text' in node ? node.text : '[注]').join('')).toBe('A😀新增[注]BC尾')
  const operations = compile(f)
  expect(operations.find(operation => operation.kind === 'insertNote')).toMatchObject({ offset: 5 })
})
it('先插注再在同段注后输入，保留注前粗体和注后原有斜体', () => {
  const f = setup()
  f.apply([insertion(3)])
  f.editor.commands.insertContentAt(5, '追加')
  expect(f.editor.getJSON().content![0].content!.map(node => node.type === 'text' && 'text' in node ? node.text : '[注]').join('')).toBe('A😀[注]追加BC尾')
  expect(f.editor.getJSON().content![0].content!.at(-1)!.marks!.some(mark => mark.type === 'italic')).toBe(true)
  compile(f)
})
it('删除既有脚注后真正替换同段文字，不能依靠相邻新段落绕过', () => {
  const f = setup(true), note = f.model.footnotes[0]
  f.apply([{ kind: 'deleteNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: note.expectedNoteSha256, expectedReferences: note.references }])
  f.editor.commands.insertContentAt({ from: 4, to: 5 }, '改')
  expect(f.editor.getText()).toBe('A😀改C尾')
  compile(f)
})
it('emoji前后文字与格式混编后仍保留区外run及原始不透明属性', () => {
  const f = setup()
  f.editor.commands.insertContentAt({ from: 4, to: 5 }, '字😀')
  f.apply([insertion(6)])
  f.editor.chain().setTextSelection({ from: 4, to: 7 }).setMark('docTextStyle', { color: '112233' }).run()
  const content = f.editor.getJSON().content![0].content!
  expect(content[0]).toMatchObject({ type: 'text', text: 'A😀' })
  expect(content[0].marks!.find(mark => mark.type === 'docTextStyle')!.attrs!.rawRPr).toBe('<w:rPr><w:noProof/></w:rPr>')
  expect(content.at(-1)).toMatchObject({ type: 'text', text: 'C尾' })
  expect(content.at(-1)!.marks!.some(mark => mark.type === 'italic')).toBe(true)
  compile(f)
})

it('取消首个pending注释后保留已输入文字并重分配后续id和当前offset', () => {
  const f = setup()
  f.apply([insertion(3), { ...insertion(6), text: '第二注释' }])
  f.editor.commands.insertContentAt(5, '追加')
  const remaining = [{ ...insertion(6), text: '第二注释' }]
  const next = applyDocxNotesIntent(f.editor.getJSON(), remaining, anchors, f.model, { kind: 'footnote', id: '1' })
  f.editor.view.dispatch(f.editor.state.tr.replaceWith(0, f.editor.state.doc.content.size, f.editor.schema.nodeFromJSON(next).content).setDocAttribute('nativeNotesOperations', remaining))
  expect(f.editor.getText()).toBe('A😀追加BC尾')
  const markers = f.editor.getJSON().content![0].content!.filter(node => node.type === 'docNoteRef')
  expect(markers.map(node => 'attrs' in node ? node.attrs!.id : undefined)).toEqual(['1'])
  const operations = compile(f)
  expect(operations.find(operation => operation.kind === 'insertNote')).toMatchObject({ offset: 7 })
})
it.each(['copy-marker', 'remove-marker', 'rawRPr', 'move-marker'])('拒绝未授权marker或opaque格式修改：%s', fault => {
  const f = setup(true), changed = structuredClone(f.baseline)
  const paragraph = changed.content![0], marker = paragraph.content![1]
  if (fault === 'copy-marker') paragraph.content!.push(structuredClone(marker))
  else if (fault === 'remove-marker') paragraph.content!.splice(1, 1)
  else if (fault === 'move-marker') { paragraph.content!.splice(1, 1); paragraph.content!.unshift(marker) }
  else paragraph.content![0].marks!.find(mark => mark.type === 'docTextStyle')!.attrs!.rawRPr = '<w:rPr><w:vanish/></w:rPr>'
  expect(() => normalizeDocxNotes(f.baseline, changed, anchors, f.model)).toThrow()
})

it('保留来源软换行与格式，同时在换行后改字并插注', () => {
  const f = setup()
  const paragraph = structuredClone(f.baseline.content![0])
  paragraph.content!.splice(1, 0, { type: 'hardBreak', marks: structuredClone(paragraph.content![0].marks) })
  const base = f.editor.schema.nodeFromJSON({ ...f.baseline, content: [paragraph] })
  f.editor.view.dispatch(f.editor.state.tr.replaceWith(0, f.editor.state.doc.content.size, base.content))
  f.baseline = f.editor.getJSON() as DocxPmNode
  f.editor.commands.insertContentAt(5, '新增')
  f.apply([insertion(6)])
  expect(f.editor.getJSON().content![0].content!.filter(node => node.type === 'hardBreak')).toHaveLength(1)
  compile(f)
})

it('引用段中选中文字的高亮及上下标保持marker原样且可回放', async () => {
  const { applyParagraphHighlight } = await import('./docx-highlight')
  const { toggleParagraphVerticalAlign } = await import('./docx-vertical')
  const f = setup(true), marker = structuredClone(f.editor.getJSON().content![0].content![1])
  f.editor.commands.setTextSelection({ from: 5, to: 7 })
  expect(applyParagraphHighlight(f.editor, anchors, 'cyan', true)).toBe(true)
  expect(toggleParagraphVerticalAlign(f.editor, anchors, 'superscript', true)).toBe(true)
  expect(f.editor.getJSON().content![0].content!.find(node => node.type === 'docNoteRef')).toEqual(marker)
  compile(f)
})

it('拒绝把孤立UTF16代理项保存为静默替换字符', () => {
  const f = setup(true), changed = structuredClone(f.baseline)
  changed.content![0].content![0].text = '\ud800'
  expect(() => normalizeDocxNotes(f.baseline, changed, anchors, f.model)).toThrow(/Unicode/)
})
