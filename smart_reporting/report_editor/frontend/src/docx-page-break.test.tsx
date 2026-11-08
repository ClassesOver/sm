import { afterEach, expect, it } from 'vitest'
import { Editor, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { docxOperations, replayDocxOperations, type DocxAnchor } from './docx-operations'
import { DOCX_PAGE_BREAK_AT_START, DocxInsertSource, docxPageBreakUnavailable, insertDocxPageBreak } from './docx-insert-source'

// 固定 schema（extensions.ts:280,325）：docxIndex 锚点；pageBreakBefore keepOnSplit:false。
const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => ({
  docxIndex: { default: null }, pageBreakBefore: { default: false, keepOnSplit: false },
}), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const anchors: DocxAnchor[] = [
  { docxIndex: 0, blockId: 'body-0', expectedObjectSha256: 'sha-0', editable: true },
  { docxIndex: 1, blockId: 'body-1', expectedObjectSha256: 'sha-1', editable: true },
]
const editors: Editor[] = []
function setup() {
  const editor = new Editor({ extensions: [Doc, Paragraph, Text, UndoRedo], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '前半后半' }] },
    { type: 'docParagraph', attrs: { docxIndex: 1 }, content: [{ type: 'text', text: '第二段' }] },
  ] } })
  editors.push(editor)
  return editor
}
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })

it('marks the caret paragraph at a paragraph start and replays the single page-break operation', () => {
  const editor = setup(), original = editor.getJSON()
  editor.commands.setTextSelection(7) // 第二段段首
  expect(docxPageBreakUnavailable(editor, true)).toBeUndefined()
  insertDocxPageBreak(editor)
  const current = editor.getJSON()
  expect(current.content!.map(node => node.attrs!.pageBreakBefore)).toEqual([false, true])
  const operation = { kind: 'setParagraphPageBreakBefore', blockId: 'body-1', expectedObjectSha256: 'sha-1', value: true }
  expect(docxOperations(original, current, anchors)).toEqual([operation])
  const restored = replayDocxOperations(original, [operation], anchors)
  expect(restored.content![1]!.attrs!.pageBreakBefore).toBe(true)
  expect(docxOperations(original, restored, anchors)).toEqual([operation])
  // 关闭同样是单一操作；单次撤销恢复。
  expect(docxOperations(current, original, anchors.map(anchor => anchor)).map(op => op.value)).toEqual([false])
  editor.commands.undo()
  expect(editor.getJSON()).toEqual(original)
})

it('splits mid-paragraph so the second half starts the page as a new paragraph without a duplicated anchor', () => {
  const editor = setup(), original = editor.getJSON()
  editor.commands.setTextSelection(3) // "前半|后半"
  insertDocxPageBreak(editor)
  const current = editor.getJSON()
  expect(current.content!.map(node => [node.attrs!.docxIndex, node.attrs!.pageBreakBefore, (node.content?.[0] as { text?: string } | undefined)?.text])).toEqual([
    [0, false, '前半'], [null, true, '后半'], [1, false, '第二段'],
  ])
  const operations = docxOperations(original, current, anchors)
  expect(operations).toContainEqual({ kind: 'insertParagraph', blockId: 'body-1', expectedObjectSha256: 'sha-1', position: 'before', text: '后半', pageBreakBefore: true })
  expect(operations.find(op => op.kind === 'replaceParagraph')).toMatchObject({ blockId: 'body-0', text: '前半' })
  const restored = replayDocxOperations(original, operations, anchors)
  expect(restored.content!.map(node => [node.attrs!.pageBreakBefore, (node.content?.[0] as { text?: string } | undefined)?.text])).toEqual([[false, '前半'], [true, '后半'], [false, '第二段']])
  editor.commands.undo()
  expect(editor.getJSON()).toEqual(original)
})

it('refuses the document start, nested contexts and same-paragraph mixing with a stated reason', () => {
  const editor = setup(), original = editor.getJSON()
  editor.commands.setTextSelection(1)
  expect(docxPageBreakUnavailable(editor, true)).toBe(DOCX_PAGE_BREAK_AT_START)
  expect(() => insertDocxPageBreak(editor)).toThrow('文档开头')
  expect(editor.getJSON()).toEqual(original)
  expect(docxPageBreakUnavailable(editor, false)).toContain('不可编辑')
  const mixed = structuredClone(original)
  mixed.content![1]!.attrs!.pageBreakBefore = true
  const mixedText = mixed.content![1]!.content![0] as { text: string }
  mixedText.text = '第二段改'
  expect(() => docxOperations(original, mixed, anchors)).toThrow('分页符修改请先保存')
  expect(() => replayDocxOperations(original, [{ kind: 'setParagraphPageBreakBefore', blockId: 'body-1', expectedObjectSha256: 'sha-1', value: 'yes' }], anchors)).toThrow('草稿分页符字段')
  expect(() => replayDocxOperations(original, [{ kind: 'setParagraphPageBreakBefore', blockId: 'body-1', expectedObjectSha256: 'stale', value: true }], anchors)).toThrow('草稿分页符字段')
})

it('enables the Insert page-break button only where the break can be saved', () => {
  const editor = setup()
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const render = () => flushSync(() => root.render(<DocxInsertSource editor={editor} editable anchors={anchors} />))
  editor.commands.setTextSelection(1); render()
  const button = () => host.querySelector<HTMLButtonElement>('[data-action="insert-page-break"]')!
  expect(button().disabled).toBe(true)
  expect(button().title).toBe(DOCX_PAGE_BREAK_AT_START)
  editor.commands.setTextSelection(7); render()
  expect(button().disabled).toBe(false)
  button().click()
  expect(editor.getJSON().content![1]!.attrs!.pageBreakBefore).toBe(true)
  flushSync(() => root.render(<DocxInsertSource editor={editor} editable={false} anchors={anchors} />))
  expect(button().disabled).toBe(true)
  root.unmount()
})
