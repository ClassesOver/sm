import { afterEach, expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { DocxInsertSource } from './docx-insert-source'
import { docxOperations, replayDocxOperations } from './docx-operations'
import { NativeDocxParagraphProperties, projectDocxParagraphProperties } from './docx-paragraph-properties'
import { applyParagraphShading } from './docx-shading'

const editors: Editor[] = [], roots: ReturnType<typeof createRoot>[] = []
const anchors = [0, 1].map(docxIndex => ({ docxIndex, blockId: `p${docxIndex}`, expectedObjectSha256: `sha${docxIndex}`, editable: true, dropCapEditable: true }))
function setup() {
  const editor = new Editor({ extensions: [...editorExtensions, NativeDocxParagraphProperties], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: ['甲段保留正文', '乙段保留粗体'].map((text, docxIndex) => ({ type: 'docParagraph', attrs: { docxIndex }, content: [{ type: 'text', text, marks: [{ type: 'bold' }] }] })) } })
  editors.push(editor)
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host); roots.push(root)
  const render = () => flushSync(() => root.render(createElement(DocxInsertSource, { editor, editable: editor.isEditable, anchors })))
  render(); editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 })
  const click = (selector: string) => flushSync(() => host.querySelector<HTMLButtonElement>(selector)!.click())
  return { editor, host, click, render, baseline: editor.getJSON() }
}
afterEach(() => { roots.splice(0).forEach(root => root.unmount()); editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })

it('首字下沉源菜单修改多段后可撤销重做、草稿回放和取消菜单不改正文', () => {
  const { editor, host, click, baseline } = setup()
  expect(host.querySelector<HTMLButtonElement>('[data-action="insert-drop-cap"]')!.disabled).toBe(false)
  click('[data-action="insert-drop-cap"]')
  expect(host.querySelectorAll('[data-drop-cap-option]')).toHaveLength(3)
  click('[data-drop-cap-option="drop"]')
  const edited = editor.getJSON()
  expect(edited.content!.map(n => n.attrs!.dropCap)).toEqual(['{"type":"drop","lines":3}', '{"type":"drop","lines":3}'])
  expect(edited.content!.map(n => n.content)).toEqual(baseline.content!.map(n => n.content))
  const ops = docxOperations(baseline, edited, anchors)
  expect(ops).toEqual(anchors.map(a => ({ kind: 'setParagraphDropCap', blockId: a.blockId, expectedObjectSha256: a.expectedObjectSha256, value: { type: 'drop', lines: 3 } })))
  expect(editor.schema.nodeFromJSON(replayDocxOperations(baseline, ops, anchors)).toJSON()).toEqual(edited)
  expect(editor.commands.undo()).toBe(true); expect(editor.getJSON()).toEqual(baseline)
  expect(editor.commands.redo()).toBe(true); expect(editor.getJSON()).toEqual(edited)
  click('[data-action="insert-drop-cap"]'); click('[data-action="insert-drop-cap"]')
  expect(editor.getJSON()).toEqual(edited)
})

it('首字悬挂可清除且与同段文字编辑共同收集，不丢人工修改', () => {
  const { editor, click, baseline } = setup()
  editor.commands.setTextSelection(2); editor.commands.insertContent('新增')
  click('[data-action="insert-drop-cap"]'); click('[data-drop-cap-option="margin"]')
  const edited = editor.getJSON(), ops = docxOperations(baseline, edited, anchors)
  expect(ops.some(op => op.kind === 'setParagraphDropCap' && (op.value as any).type === 'margin')).toBe(true)
  expect(ops.some(op => op.kind === 'replaceParagraph' && String(op.text).includes('新增'))).toBe(true)
  expect(editor.schema.nodeFromJSON(replayDocxOperations(baseline, ops, anchors)).toJSON()).toEqual(edited)
  click('[data-action="insert-drop-cap"]'); click('[data-drop-cap-option="none"]')
  expect(editor.getJSON().content![0]!.attrs!.dropCap).toBeNull()
  expect(docxOperations(baseline, editor.getJSON(), anchors).some(op => op.kind === 'setParagraphDropCap')).toBe(false)
})

it('新的普通段落保存首字下沉意图且回放不继承锚点的首字下沉', () => {
  const { editor, baseline } = setup()
  const current = structuredClone(baseline)
  current.content!.push(editor.schema.nodeFromJSON({ type: 'docParagraph', attrs: { dropCap: '{"type":"drop","lines":3}' }, content: [{ type: 'text', text: '新增段落' }] }).toJSON())
  const ops = docxOperations(baseline, current, anchors)
  expect(ops).toHaveLength(1)
  expect(ops[0]).toMatchObject({ kind: 'insertParagraph', dropCap: { type: 'drop', lines: 3 }, text: '新增段落' })
  expect(editor.schema.nodeFromJSON(replayDocxOperations(baseline, ops, anchors)).toJSON()).toEqual(current)
})

it('只读或过期来源不写回，也不接受伪造首字下沉字段', () => {
  const { editor, baseline, render, host } = setup()
  editor.setEditable(false); render()
  expect(host.querySelector<HTMLButtonElement>('[data-action="insert-drop-cap"]')!.disabled).toBe(true)
  const op = { kind: 'setParagraphDropCap', blockId: 'p0', expectedObjectSha256: 'sha0', value: { type: 'drop', lines: 3 } }
  for (const bad of [{ ...op, expectedObjectSha256: 'stale' }, { ...op, value: { type: 'other', lines: 3 } }, { ...op, value: { type: 'drop', lines: true } }, { ...op, value: { type: 'drop', lines: 3, rawXml: '<x/>' } }]) expect(() => replayDocxOperations(baseline, [bad], anchors)).toThrow()
  expect(() => replayDocxOperations(baseline, [op, op], anchors)).toThrow()
  expect(() => replayDocxOperations(baseline, [op], [{ ...anchors[0]!, dropCapEditable: false }, anchors[1]!])).toThrow()
})

it('首字下沉与同段底纹及完整段落设置共同恢复，保持各自原生意图', () => {
  const { editor, baseline, click } = setup()
  editor.commands.setTextSelection(2)
  applyParagraphShading(editor, anchors, 'edf5fc')
  click('[data-action="insert-drop-cap"]'); click('[data-drop-cap-option="drop"]')
  let current = editor.getJSON(), ops = docxOperations(baseline, current, anchors)
  expect(ops.map(op => op.kind)).toEqual(['setParagraphDropCap', 'setParagraphShading'])
  expect(editor.schema.nodeFromJSON(replayDocxOperations(baseline, ops, anchors)).toJSON()).toEqual(current)
  current = structuredClone(baseline)
  current.content![0] = projectDocxParagraphProperties(baseline.content![0]!, anchors[0]!, { align: 'center', spaceBefore: 0 }, editor.schema) as NonNullable<typeof current.content>[number]
  current.content![0]!.attrs!.dropCap = '{"type":"margin","lines":3}'
  ops = docxOperations(baseline, current, anchors, undefined, editor.schema)
  expect(ops.map(op => op.kind)).toEqual(['setParagraphDropCap', 'setParagraphProperties'])
  expect(editor.schema.nodeFromJSON(replayDocxOperations(baseline, ops, anchors, undefined, editor.schema)).toJSON()).toEqual(current)
})
