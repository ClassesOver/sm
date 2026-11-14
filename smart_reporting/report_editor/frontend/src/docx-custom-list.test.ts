import { afterEach, expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeDocxCustomList, applyDocxCustomList, clearDocxCustomList, docxCustomListReason, changeDocxCustomListLevel } from './docx-custom-list'
import { docxOperations, replayDocxOperations } from './docx-operations'

const editors: Editor[] = []
afterEach(() => editors.splice(0).forEach(editor => editor.destroy()))
const anchors = [0, 1].map(i => ({ docxIndex: i, blockId: `p${i}`, expectedObjectSha256: `hash${i}`, editable: true }))
const levels = Array.from({ length: 9 }, (_, i) => ({ numFmt: i === 1 ? 'bullet' : 'decimal', lvlText: i === 1 ? '•' : `%${i + 1}.`, indentLeft: 720 * (i + 1), hanging: 360 }))
function fixture() {
  const editor = new Editor({ extensions: [...editorExtensions, NativeDocxCustomList], content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0, align: 'center' }, content: [{ type: 'text', text: '甲', marks: [{ type: 'bold' }] }] },
    { type: 'docParagraph', attrs: { docxIndex: 1 }, content: [{ type: 'text', text: '乙' }] },
  ] } })
  editors.push(editor); return editor
}

it('同一事务为多段绑定一份九级定义，撤销重做和草稿恢复同步编号覆盖层', () => {
  const editor = fixture(), baseline = editor.getJSON()
  editor.commands.setTextSelection({ from: 1, to: 5 })
  applyDocxCustomList(editor, anchors, levels)
  const nodes = editor.getJSON().content!, first = nodes[0]!
  expect(nodes.map(n => n.type)).toEqual(['docListItem', 'docListItem'])
  expect(nodes[1]!.attrs!.numId).toBe(first.attrs!.numId)
  expect(first.attrs).toMatchObject({ align: 'center', ilvl: 0 })
  const operations = docxOperations(baseline, editor.getJSON(), anchors)
  expect(operations).toHaveLength(2)
  expect(editor.storage.listNumbering.defs.get(first.attrs!.numId)!.levels[8]!.lvlText).toBe('%9.')
  expect(editor.commands.undo()).toBe(true)
  expect(docxOperations(baseline, editor.getJSON(), anchors)).toEqual([])
  expect(editor.storage.listNumbering.defs.has(first.attrs!.numId)).toBe(false)
  expect(editor.commands.redo()).toBe(true)
  const restored = replayDocxOperations(baseline, operations, anchors)
  editor.commands.setContent(restored)
  expect(editor.storage.listNumbering.defs.has(first.attrs!.numId)).toBe(true)
})

it('混合编号/符号预设可以切换级别并保留同段文字修改', () => {
  const editor = fixture(), baseline = editor.getJSON()
  editor.commands.setTextSelection(1)
  applyDocxCustomList(editor, anchors, levels)
  changeDocxCustomListLevel(editor, 1)
  expect(editor.state.doc.firstChild!.attrs.kind).toBe('bullet')
  editor.commands.insertContent('新')
  expect(docxOperations(baseline, editor.getJSON(), anchors).map(op => op.kind)).toEqual(['setParagraphCustomList', 'replaceParagraph'])
})

it('锁定、失去来源身份及包含只读段落时不写入任何段落', () => {
  const editor = fixture(), baseline = editor.getJSON()
  editor.commands.setTextSelection({ from: 1, to: 5 })
  expect(docxCustomListReason(editor, [anchors[0]!, { ...anchors[1]!, editable: false }])).toBeTruthy()
  expect(() => applyDocxCustomList(editor, [anchors[0]!], levels)).toThrow()
  editor.setEditable(false)
  expect(() => applyDocxCustomList(editor, anchors, levels)).toThrow()
  expect(editor.getJSON()).toEqual(baseline)
})

it('原有标题可应用多级列表，保留样式和正文；可清除未保存的定义', () => {
  const editor = fixture()
  editor.commands.setContent({ type: 'doc', content: [{ type: 'docHeading', attrs: { docxIndex: 0, styleId: 'Heading1', level: 1 }, content: [{ type: 'text', text: '标题' }] }] })
  const baseline = editor.getJSON()
  editor.storage.nativeDocxCustomList.sourceDoc = editor.state.doc
  editor.commands.setTextSelection(1)
  applyDocxCustomList(editor, anchors, levels)
  const ops = docxOperations(baseline, editor.getJSON(), anchors)
  expect(ops).toHaveLength(1)
  const restored = replayDocxOperations(baseline, ops, anchors)
  editor.commands.setContent(restored)
  expect(docxOperations(baseline, editor.getJSON(), anchors)).toEqual(ops)
  expect(editor.state.doc.firstChild!.attrs.styleId).toBe('Heading1')
  clearDocxCustomList(editor, anchors)
  expect(editor.state.doc.firstChild!.type.name).toBe('docHeading')
  expect(docxOperations(baseline, editor.getJSON(), anchors)).toEqual([])
})
