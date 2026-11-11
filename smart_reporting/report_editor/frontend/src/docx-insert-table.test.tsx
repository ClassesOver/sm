import { afterEach, expect, it, vi } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeTableStructure } from './docx-tables'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { DOCX_TABLE_NESTED, docxTableInsertUnavailable, insertDocxTable, newTableMatchesProjection, newTableSize, projectNewDocxTable } from './docx-new-table'
import { DocxInsertSource } from './docx-insert-source'

// 真实固定扩展（docx-main 同组：editorExtensions + NativeTableStructure + 原生保存守卫）。
const anchors: DocxAnchor[] = [
  { docxIndex: 0, blockId: 'body-0', expectedObjectSha256: 'sha-0', editable: true },
  { docxIndex: 1, blockId: 'body-1', expectedObjectSha256: 'sha-1', editable: true },
]
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren(); vi.unstubAllGlobals() })
function setup(second: string = '第二段') {
  let baseline: DocxPmNode | undefined
  const rejected: string[] = []
  const Guard = Extension.create({ name: 'testNativeGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) {
    if (!baseline || !tr.docChanged) return true
    try { docxOperations(baseline, tr.doc.toJSON() as DocxPmNode, anchors, undefined, editor.schema); return true } catch (error) { rejected.push((error as Error).message); return false }
  } })] })
  const editor = new Editor({ extensions: [...editorExtensions, NativeTableStructure, Guard], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '前半后半' }] },
    { type: 'docParagraph', attrs: { docxIndex: 1 }, ...(second ? { content: [{ type: 'text', text: second }] } : {}) },
  ] } })
  editors.push(editor)
  baseline = editor.getJSON() as DocxPmNode
  return { editor, baseline, rejected }
}
const kinds = (editor: Editor) => editor.getJSON().content!.map(node => node.type === 'docTable' ? `table${node.content!.length}x${(node.content![0] as { content?: unknown[] }).content!.length}` : `p:${node.attrs!.docxIndex ?? 'new'}:${(node.content?.[0] as { text?: string } | undefined)?.text ?? ''}`)

it('inserts a selected PNG through the ribbon, replays the save operations and undoes once', async () => {
  const { editor, baseline, rejected } = setup()
  vi.stubGlobal('Image', class {
    naturalWidth = 1240; naturalHeight = 960
    onload?: () => void
    set src(_value: string) { queueMicrotask(() => this.onload?.()) }
  })
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  editor.commands.setTextSelection(3)
  flushSync(() => root.render(<DocxInsertSource editor={editor} editable anchors={anchors} />))
  const button = host.querySelector<HTMLButtonElement>('[data-action="insert-picture"]')!
  expect(button.disabled).toBe(false)
  flushSync(() => button.click())
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!
  const bytes = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='), ch => ch.charCodeAt(0))
  Object.defineProperty(input, 'files', { configurable: true, value: [new File([bytes], 'photo.png', { type: 'image/png' })] })
  flushSync(() => input.dispatchEvent(new Event('change', { bubbles: true })))
  await vi.waitFor(() => expect(editor.getJSON().content![1].type).toBe('docProtected'))
  expect(rejected).toEqual([])
  expect(editor.getJSON().content![1].attrs).toMatchObject({ blockType: 'image', imageWidthPx: 620, imageHeightPx: 480 })
  const operations = docxOperations(baseline, editor.getJSON() as DocxPmNode, anchors, undefined, editor.schema)
  expect(operations.find(op => op.kind === 'insertParagraphImage')).toMatchObject({ image: { mime: 'image/png', widthPx: 620, heightPx: 480 } })
  const restored = replayDocxOperations(baseline, operations, anchors, undefined, editor.schema)
  expect(docxOperations(baseline, restored, anchors, undefined, editor.schema)).toEqual(operations)
  editor.commands.undo()
  expect(editor.getJSON()).toEqual(baseline)
  editor.commands.redo()
  expect(editor.getJSON().content![1].type).toBe('docProtected')
  root.unmount()
})

it('enforces the shared size budget', () => {
  expect(newTableSize({ rows: 100, cols: 10 })).toEqual({ rows: 100, cols: 10 })
  for (const bad of [{ rows: 0, cols: 1 }, { rows: 101, cols: 1 }, { rows: 1, cols: 31 }, { rows: 40, cols: 30 }, { rows: 1.5, cols: 2 }, { rows: 2, cols: 2, style: 'x' }, null]) {
    expect(() => newTableSize(bad), JSON.stringify(bad)).toThrow()
  }
})

it('inserts after a paragraph end with a trailing empty paragraph at the document end, and saves as insertTable', () => {
  const { editor, baseline, rejected } = setup()
  editor.commands.setTextSelection(editor.state.doc.content.size - 1) // 第二段末尾 = 文档末尾
  insertDocxTable(editor, 2, 3)
  expect(rejected).toEqual([])
  expect(kinds(editor)).toEqual(['p:0:前半后半', 'p:1:第二段', 'table2x3', 'p:new:'])
  expect(editor.state.selection.$from.node(-1).type.name).toMatch(/docTable(Cell|Header)/) // 光标在首格
  const operations = docxOperations(baseline, editor.getJSON() as DocxPmNode, anchors, undefined, editor.schema)
  expect(operations).toEqual([
    { kind: 'insertTable', blockId: 'body-1', expectedObjectSha256: 'sha-1', position: 'after', rows: 2, cols: 3 },
    { kind: 'insertParagraph', blockId: 'body-1', expectedObjectSha256: 'sha-1', position: 'after', text: '' },
  ])
  const restored = replayDocxOperations(baseline, operations, anchors, undefined, editor.schema)
  expect(restored.content![2]).toEqual(projectNewDocxTable({ rows: 2, cols: 3 }, editor.schema))
  expect(docxOperations(baseline, restored, anchors, undefined, editor.schema)).toEqual(operations)
  editor.commands.undo()
  expect(editor.getJSON()).toEqual(baseline)
})

it('keeps an empty caret paragraph below the table and splits a paragraph around it', () => {
  const empty = setup('')
  empty.editor.commands.setTextSelection(empty.editor.state.doc.content.size - 1)
  insertDocxTable(empty.editor, 1, 2)
  expect(kinds(empty.editor)).toEqual(['p:0:前半后半', 'table1x2', 'p:1:'])
  expect(docxOperations(empty.baseline, empty.editor.getJSON() as DocxPmNode, anchors, undefined, empty.editor.schema))
    .toEqual([{ kind: 'insertTable', blockId: 'body-1', expectedObjectSha256: 'sha-1', position: 'before', rows: 1, cols: 2 }])
  const mid = setup()
  mid.editor.commands.setTextSelection(3) // "前半|后半"
  insertDocxTable(mid.editor, 2, 2)
  expect(kinds(mid.editor)).toEqual(['p:0:前半', 'table2x2', 'p:new:后半', 'p:1:第二段'])
  const operations = docxOperations(mid.baseline, mid.editor.getJSON() as DocxPmNode, anchors, undefined, mid.editor.schema)
  expect(operations.filter(op => op.kind !== 'replaceParagraph')).toEqual([
    { kind: 'insertTable', blockId: 'body-1', expectedObjectSha256: 'sha-1', position: 'before', rows: 2, cols: 2 },
    { kind: 'insertParagraph', blockId: 'body-1', expectedObjectSha256: 'sha-1', position: 'before', text: '后半' },
  ])
  expect(operations.find(op => op.kind === 'replaceParagraph')).toMatchObject({ blockId: 'body-0', text: '前半' })
})

it('carries plain text typed into the unsaved table and replays it', () => {
  const { editor, baseline, rejected } = setup()
  editor.commands.setTextSelection(5)
  insertDocxTable(editor, 2, 2)
  editor.commands.insertContent('甲') // 光标在新表首格
  editor.commands.splitBlock()
  editor.commands.insertContent('乙')
  expect(rejected).toEqual([])
  const operations = docxOperations(baseline, editor.getJSON() as DocxPmNode, anchors, undefined, editor.schema)
  const insert = operations.find(op => op.kind === 'insertTable')!
  expect(insert.cells).toEqual([['甲\n乙', ''], ['', '']])
  const restored = replayDocxOperations(baseline, operations, anchors, undefined, editor.schema)
  expect(newTableMatchesProjection(restored.content![1]!, editor.getJSON().content![1] as DocxPmNode)).toBe(true)
  expect(docxOperations(baseline, restored, anchors, undefined, editor.schema)).toEqual(operations)
})

it('refuses formatting the unsaved table, nested insertion and pasted tables', () => {
  const { editor, baseline, rejected } = setup()
  editor.commands.setTextSelection(5)
  insertDocxTable(editor, 2, 2)
  editor.commands.insertContent('x')
  const before = editor.getJSON()
  editor.commands.selectParentNode()
  editor.commands.toggleMark('bold')
  expect(editor.getJSON()).toEqual(before)
  expect(rejected.at(-1)).toContain('只能输入纯文字')
  editor.commands.setTextSelection(editor.state.selection.from)
  expect(docxTableInsertUnavailable(editor, true)).toBe(DOCX_TABLE_NESTED)
  expect(() => insertDocxTable(editor, 1, 1)).toThrow('表格或嵌套内容')
  const pasted = structuredClone(before) as DocxPmNode
  pasted.content!.splice(1, 1, { ...pasted.content![1]!, attrs: { ...pasted.content![1]!.attrs, nativeTableInsert: null } })
  expect(() => docxOperations(baseline, pasted, anchors, undefined, editor.schema)).toThrow('粘贴或复制的表格')
  expect(() => replayDocxOperations(baseline, [{ kind: 'insertTable', blockId: 'body-1', expectedObjectSha256: 'stale', position: 'before', rows: 2, cols: 2 }], anchors, undefined, editor.schema)).toThrow('草稿新增表格')
})

it('inserts from the source picker grid and the custom size form', () => {
  const { editor } = setup()
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const render = () => flushSync(() => root.render(<DocxInsertSource editor={editor} editable anchors={anchors} />))
  editor.commands.setTextSelection(5); render()
  const tableButton = () => host.querySelector<HTMLButtonElement>('[data-action="insert-table"]')!
  expect(tableButton().disabled).toBe(false)
  flushSync(() => tableButton().click())
  flushSync(() => host.querySelector<HTMLButtonElement>('[data-table-size="3x4"]')!.click())
  expect(kinds(editor)).toContain('table3x4')
  // 光标进入新表格后按钮以原因禁用。
  render()
  expect(tableButton().disabled).toBe(true)
  expect(tableButton().title).toBe(DOCX_TABLE_NESTED)
  editor.commands.undo(); editor.commands.setTextSelection(5); render()
  flushSync(() => tableButton().click())
  flushSync(() => host.querySelector<HTMLButtonElement>('[data-action="insert-table-custom"]')!.click())
  const cols = host.querySelector<HTMLInputElement>('[data-field="table-cols"]')!
  const setValue = (input: HTMLInputElement, value: string) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })) }
  // 超出预算：原生约束校验（max）阻止提交，文档不变。
  const beforeOverflow = editor.getJSON()
  flushSync(() => setValue(cols, '31'))
  expect(cols.validity.rangeOverflow).toBe(true)
  flushSync(() => host.querySelector<HTMLButtonElement>('[data-command="insertTable"]')!.click())
  expect(editor.getJSON()).toEqual(beforeOverflow)
  flushSync(() => setValue(host.querySelector<HTMLInputElement>('[data-field="table-cols"]')!, '6'))
  flushSync(() => host.querySelector<HTMLButtonElement>('[data-command="insertTable"]')!.click())
  expect(kinds(editor)).toContain('table2x6')
  root.unmount()
})
