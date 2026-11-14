import { afterEach, expect, it, vi } from 'vitest'
import { Editor } from '@tiptap/core'
import { computeListValues } from '@genoffice/docx-engine'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import * as lists from './docx-custom-list'
import { docxOperations, replayDocxOperations } from './docx-operations'
import { createDocxRibbon } from './docx-ribbon'

const editors: Editor[] = []
afterEach(() => editors.splice(0).forEach(editor => editor.destroy()))
const anchors = Array.from({ length: 5 }, (_, i) => ({ docxIndex: i, blockId: `p${i}`, expectedObjectSha256: `h${i}`, editable: true }))
function fixture(ids = ['5', '5', '6', '6', '5']) {
  const editor = new Editor({ extensions: [...editorExtensions, lists.NativeDocxCustomList], content: { type: 'doc', content: ids.map((numId, i) => ({ type: 'docListItem', attrs: { docxIndex: i, numId, kind: 'ordered', ilvl: 0, align: i === 3 ? 'center' : null }, content: [{ type: 'text', text: `段${i}`, marks: i === 3 ? [{ type: 'bold' }] : [] }] })) } })
  editor.storage.listNumbering.defs = new Map(['5', '6'].map(numId => [numId, { numId, abstractNumId: numId, levels: { 0: { numFmt: 'decimal', lvlText: '%1.', start: 1 } }, startOverrides: {} }]))
  editor.commands.setTextSelection(13)
  editors.push(editor)
  return editor
}
const apply = (editor: Editor, mode: 'restart' | 'continue', value?: number) => {
  expect((lists as any).setDocxNumberingValue).toBeTypeOf('function')
  return (lists as any).setDocxNumberingValue(editor, anchors, { mode, ...(value !== undefined ? { value } : {}) })
}
const values = (editor: Editor) => computeListValues(editor.getJSON().content!.map(n => ({ numId: n.attrs!.numId, ilvl: n.attrs!.ilvl })), editor.storage.listNumbering.defs)

it('restart从当前项改写后续同numId，同一原生事务可撤销重做并恢复草稿', () => {
  const editor = fixture(['5', '5', '5', '5', '5']), baseline = editor.getJSON()
  apply(editor, 'restart', 7)
  expect(values(editor)).toEqual([1, 2, 3, 7, 8])
  const operations = docxOperations(baseline, editor.getJSON(), anchors)
  expect(operations.map(op => op.kind)).toEqual(['setParagraphNumberingValue', 'setParagraphNumberingValue'])
  expect(operations[0]!.binding).toMatchObject({ sourceNumId: '5', startOverrides: { 0: 7 } })
  const changed = editor.getJSON()
  expect(editor.commands.undo()).toBe(true); expect(editor.getJSON()).toEqual(baseline)
  expect(editor.commands.redo()).toBe(true); expect(editor.getJSON()).toEqual(changed)
  const restored = replayDocxOperations(baseline, operations, anchors)
  editor.commands.setContent(restored)
  expect(values(editor)).toEqual([1, 2, 3, 7, 8])
  expect(editor.getJSON().content![3]!.attrs!.align).toBe('center')
})

it('continue复用最近不同列表身份且不重新开始，advance覆盖当前级并改写后续合流列表', () => {
  const editor = fixture(), baseline = editor.getJSON()
  apply(editor, 'continue')
  expect(values(editor)).toEqual([1, 2, 1, 3, 4])
  expect(editor.getJSON().content![3]!.attrs!.numId).toBe('5')
  editor.commands.undo(); expect(editor.getJSON()).toEqual(baseline)
  apply(editor, 'continue', 9)
  expect(values(editor)).toEqual([1, 2, 1, 9, 10])
  expect(editor.getJSON().content![3]!.attrs!.numId).toBe(editor.getJSON().content![4]!.attrs!.numId)
})

it('新建自定义列表可restart/continue，定义与覆盖不脱离文档历史', () => {
  const editor = fixture(), baseline = editor.getJSON()
  editor.commands.setTextSelection({ from: 9, to: 15 })
  lists.applyDocxCustomList(editor, anchors, [{ numFmt: 'upperRoman', lvlText: '%1)', indentLeft: 720, hanging: 360 }])
  editor.commands.setTextSelection(13)
  apply(editor, 'restart', 4)
  expect(values(editor)[3]).toBe(4)
  const ops = docxOperations(baseline, editor.getJSON(), anchors)
  expect(ops.find(op => op.kind === 'setParagraphNumberingValue')!.binding).toHaveProperty('custom')
  expect(editor.schema.nodeFromJSON(replayDocxOperations(baseline, ops, anchors)).toJSON()).toEqual(editor.getJSON())
})

it('后续受影响段只读、锁定或非法value时整次不改写；无前序continue明确失败', () => {
  const editor = fixture(['5', '5', '5', '5', '5']), baseline = editor.getJSON()
  expect(() => (lists as any).setDocxNumberingValue(editor, anchors.map((a, i) => i === 4 ? { ...a, editable: false } : a), { mode: 'restart', value: 4 })).toThrow()
  for (const value of [-1, 32768, 1.5, NaN]) expect(() => apply(editor, 'restart', value)).toThrow()
  expect(() => apply(editor, 'continue')).toThrow()
  editor.setEditable(false); expect(() => apply(editor, 'restart', 1)).toThrow()
  expect(editor.getJSON()).toEqual(baseline)
})

it('真实Ribbon设置编号值打开原源对话框，取消不写；确认同历史保存操作', async () => {
  const editor = fixture(), baseline = editor.getJSON(), report = vi.fn()
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, anchors, undefined, undefined, undefined, report)
  document.body.append(ribbon)
  try {
    const button = ribbon.querySelector<HTMLButtonElement>('[data-action=list-numbering-set-value]')!
    expect(button.disabled).toBe(false); button.click()
    await vi.waitFor(() => expect(document.querySelector('.list-value-dialog')).not.toBeNull())
    const dialog = document.querySelector<HTMLElement>('.list-value-dialog')!
    expect(dialog.querySelector<HTMLInputElement>('[type=number]')!.value).toBe('2')
    expect(dialog.querySelectorAll<HTMLInputElement>('[type=radio]')[1]!.disabled).toBe(false)
    dialog.querySelector<HTMLButtonElement>('.modal-actions button:not(.primary)')!.click()
    expect(editor.getJSON()).toEqual(baseline)
    button.click(); await vi.waitFor(() => expect(document.querySelector('.list-value-dialog')).not.toBeNull())
    document.querySelector<HTMLButtonElement>('.list-value-dialog .primary')!.click()
    expect(docxOperations(baseline, editor.getJSON(), anchors).some(op => op.kind === 'setParagraphNumberingValue')).toBe(true)
    expect(report).not.toHaveBeenCalled()
  } finally { (ribbon as any).dispose?.(); ribbon.remove() }
})

it('设置编号值对话框提交时重新检查来源快照，外部编辑后不落旧值', async () => {
  const editor = fixture(), report = vi.fn()
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, anchors, undefined, undefined, undefined, report)
  document.body.append(ribbon)
  try {
    const button = ribbon.querySelector<HTMLButtonElement>('[data-action=list-numbering-set-value]')!
    expect(button.disabled).toBe(false); button.click()
    await vi.waitFor(() => expect(document.querySelector('.list-value-dialog')).not.toBeNull())
    editor.commands.insertContent('新')
    const changed = editor.getJSON()
    document.querySelector<HTMLButtonElement>('.list-value-dialog .primary')!.click()
    expect(editor.getJSON()).toEqual(changed); expect(report).toHaveBeenCalled()
    document.querySelector<HTMLButtonElement>('.list-value-dialog .modal-close')?.click()
  } finally { (ribbon as any).dispose?.(); ribbon.remove() }
})

it('拒绝同一编号值身份携带冲突定义的草稿生成与回放', () => {
  const editor = fixture(), baseline = editor.getJSON(), changed = structuredClone(baseline)
  const operations = [3, 4].map((index, n) => {
    const binding = { id: 'same-id', sourceNumId: '5', startOverrides: { 0: n + 7 } }
    changed.content![index]!.attrs = { ...changed.content![index]!.attrs, numId: 'native-value-same-id', nativeNumberingBinding: binding }
    return { kind: 'setParagraphNumberingValue', blockId: anchors[index]!.blockId, expectedObjectSha256: anchors[index]!.expectedObjectSha256, binding, ilvl: 0 }
  })
  expect(() => docxOperations(baseline, changed, anchors)).toThrow(/冲突/)
  expect(() => replayDocxOperations(baseline, operations, anchors)).toThrow(/冲突/)
})

it('普通列表切换清除编号绑定；销毁功能区关闭对话框', async () => {
  const editor = fixture(), ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, anchors)
  document.body.append(ribbon)
  try {
    apply(editor, 'restart', 7)
    ribbon.querySelector<HTMLButtonElement>('[data-action=bullets]')!.click()
    expect(editor.state.selection.$from.parent.attrs.nativeNumberingBinding).toHaveProperty('defaultNumbering.kind', 'bullet')
    editor.commands.undo()
    ribbon.querySelector<HTMLButtonElement>('[data-action=list-numbering-set-value]')!.click()
    await vi.waitFor(() => expect(document.querySelector('.list-value-dialog')).not.toBeNull())
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', isComposing: true, bubbles: true }))
    expect(document.querySelector('.list-value-dialog')).not.toBeNull()
    ;(ribbon as any).dispose()
    expect(document.querySelector('.list-value-dialog')).toBeNull()
  } finally { (ribbon as any).dispose?.(); ribbon.remove() }
})
