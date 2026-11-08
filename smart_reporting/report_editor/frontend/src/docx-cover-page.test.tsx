import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeTableStructure } from './docx-tables'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { COVER_PRESETS, coverGroupMatchesProjection, coverParaSpecs, coverPresetParas, docxHasCoverPage, insertDocxCoverPage, projectCoverNodes, removeDocxCoverPage } from './docx-cover-page'
import { DocxInsertSource } from './docx-insert-source'

const anchors: DocxAnchor[] = [
  { docxIndex: 0, blockId: 'body-0', expectedObjectSha256: 'sha-0', editable: true },
  { docxIndex: 1, blockId: 'body-1', expectedObjectSha256: 'sha-1', editable: true },
]
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function setup() {
  let baseline: DocxPmNode | undefined
  const rejected: string[] = []
  const Guard = Extension.create({ name: 'testNativeGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) {
    if (!baseline || !tr.docChanged) return true
    try { docxOperations(baseline, tr.doc.toJSON() as DocxPmNode, anchors, undefined, editor.schema); return true } catch (error) { rejected.push((error as Error).message); return false }
  } })] })
  const editor = new Editor({ extensions: [...editorExtensions, NativeTableStructure, Guard], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '正文一' }] },
    { type: 'docParagraph', attrs: { docxIndex: 1 }, content: [{ type: 'text', text: '正文二' }] },
  ] } })
  editors.push(editor)
  baseline = editor.getJSON() as DocxPmNode
  return { editor, baseline, rejected }
}
const texts = (editor: Editor) => editor.getJSON().content!.map(node => (node.content?.[0] as { text?: string } | undefined)?.text ?? '')

it('resolves every vendored preset into the bounded spec the bridge accepts', () => {
  expect(COVER_PRESETS.length).toBeGreaterThanOrEqual(3)
  for (const preset of COVER_PRESETS) expect(() => coverPresetParas(preset.id), preset.id).not.toThrow()
  expect(() => coverPresetParas('nope')).toThrow('未知的封面样式')
  for (const bad of [[], [{ text: 'x', font: 'Arial' }], [{ color: '#fff' }], [{ borders: 'tt' }], [{ sizeHalfPoints: 1 }]]) expect(() => coverParaSpecs(bad), JSON.stringify(bad)).toThrow()
})

it('inserts a gallery cover at the document start, keeps edited placeholder text and replays it', () => {
  const { editor, baseline, rejected } = setup()
  editor.commands.setTextSelection(5)
  insertDocxCoverPage(editor, 'classic')
  expect(rejected).toEqual([])
  const paras = coverPresetParas('classic')
  expect(texts(editor).slice(-2)).toEqual(['正文一', '正文二'])
  expect(editor.getJSON().content!.length).toBe(paras.length + 1 + 2)
  // 修改标题占位文字（保留标记）。
  const titleIndex = paras.findIndex(para => para.bold)
  let pos = 0
  for (let i = 0; i < titleIndex; i++) pos += editor.state.doc.child(i).nodeSize
  const titleNode = editor.state.doc.child(titleIndex)
  // 键入替换（insertText 沿用光标处的粗体/字号标记，同真实输入）。
  editor.view.dispatch(editor.state.tr.insertText('2026 年度经营报告', pos + 1, pos + 1 + titleNode.content.size))
  expect(rejected).toEqual([])
  const operations = docxOperations(baseline, editor.getJSON() as DocxPmNode, anchors, undefined, editor.schema)
  expect(operations).toHaveLength(1)
  expect(operations[0]).toMatchObject({ kind: 'insertCoverPage', blockId: 'body-0', position: 'before' })
  expect((operations[0]!.paras as Array<{ text?: string; bold?: boolean }>)[titleIndex]).toMatchObject({ text: '2026 年度经营报告', bold: true })
  const restored = replayDocxOperations(baseline, operations, anchors, undefined, editor.schema)
  const live = editor.getJSON() as DocxPmNode
  expect(coverGroupMatchesProjection(restored.content!.slice(0, paras.length + 1), live.content!.slice(0, paras.length + 1))).toBe(true)
  expect(restored.content!.slice(paras.length + 1)).toEqual(live.content!.slice(paras.length + 1))
  expect(docxOperations(baseline, restored, anchors, undefined, editor.schema)).toEqual(operations)
})

it('replaces an existing cover, removes it, and refuses formatting before save', () => {
  const { editor, baseline, rejected } = setup()
  insertDocxCoverPage(editor, 'classic')
  insertDocxCoverPage(editor, 'banded')
  expect(editor.getJSON().content!.length).toBe(coverPresetParas('banded').length + 1 + 2)
  const operations = docxOperations(baseline, editor.getJSON() as DocxPmNode, anchors, undefined, editor.schema)
  expect(operations.map(op => op.kind)).toEqual(['insertCoverPage'])
  expect(operations[0]!.paras).toEqual((projectCoverNodes(coverPresetParas('banded'), editor.schema)[0]!.attrs!.nativeCoverPage as { paras: unknown }).paras)
  // 加粗非预设段落 → 拒绝。
  const before = editor.getJSON()
  editor.chain().setTextSelection({ from: 1, to: 2 }).run()
  const lastCover = coverPresetParas('banded').length - 1
  let pos = 0
  for (let i = 0; i < lastCover; i++) pos += editor.state.doc.child(i).nodeSize
  editor.chain().setTextSelection({ from: pos + 1, to: pos + 3 }).toggleMark('italic').run()
  expect(editor.getJSON()).toEqual(before)
  expect(rejected.at(-1)).toContain('封面保存前只能修改占位文字')
  expect(docxHasCoverPage(editor)).toBe(true)
  removeDocxCoverPage(editor)
  expect(texts(editor)).toEqual(['正文一', '正文二'])
  expect(docxOperations(baseline, editor.getJSON() as DocxPmNode, anchors, undefined, editor.schema)).toEqual([])
  expect(() => removeDocxCoverPage(editor)).toThrow('没有可删除的封面')
})

it('offers the preset gallery and remove action in the Insert tab', () => {
  const { editor } = setup()
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const render = () => flushSync(() => root.render(<DocxInsertSource editor={editor} editable anchors={anchors} />))
  render()
  const button = host.querySelector<HTMLButtonElement>('[data-action="insert-cover-page"]')!
  expect(button.disabled).toBe(false)
  flushSync(() => button.click())
  expect(host.querySelectorAll('[data-cover-preset]').length).toBe(COVER_PRESETS.length)
  expect(host.querySelector<HTMLButtonElement>('[data-action="remove-cover-page"]')!.disabled).toBe(true)
  flushSync(() => host.querySelector<HTMLButtonElement>('[data-cover-preset="boxed"]')!.click())
  expect(docxHasCoverPage(editor)).toBe(true)
  render(); flushSync(() => host.querySelector<HTMLButtonElement>('[data-action="insert-cover-page"]')!.click())
  flushSync(() => host.querySelector<HTMLButtonElement>('[data-action="remove-cover-page"]')!.click())
  expect(docxHasCoverPage(editor)).toBe(false)
  flushSync(() => root.render(<DocxInsertSource editor={editor} editable={false} anchors={anchors} />))
  expect(host.querySelector<HTMLButtonElement>('[data-action="insert-cover-page"]')!.disabled).toBe(true)
  root.unmount()
})
