import { afterEach, expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { computeListValues } from '@genoffice/docx-engine'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeDocxCustomList, setDocxNumberingValue } from './docx-custom-list'
import { docxOperations, replayDocxOperations } from './docx-operations'
import { createDocxRibbon } from './docx-ribbon'
const editors: Editor[] = []
const ribbons: HTMLElement[] = []
afterEach(() => { ribbons.splice(0).forEach(r => { (r as any).dispose?.(); r.remove() }); editors.splice(0).forEach(e => e.destroy()) })
const anchors = [0, 1].map(docxIndex => ({ docxIndex, blockId: `p${docxIndex}`, expectedObjectSha256: `h${docxIndex}`, editable: true }))
function fixture(defs = new Map<any, any>()) {
  const editor = new Editor({ extensions: [...editorExtensions, NativeDocxCustomList], content: { type: 'doc', content: ['甲', '乙'].map((text, docxIndex) => ({ type: 'docParagraph', attrs: { docxIndex }, content: [{ type: 'text', text, marks: [{ type: 'bold' }] }] })) } })
  editor.storage.listNumbering.defs = defs
  editors.push(editor)
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, anchors)
  ribbons.push(ribbon); document.body.append(ribbon)
  editor.commands.setTextSelection({ from: 1, to: 5 })
  const click = (kind: string) => ribbon.querySelector<HTMLButtonElement>(`[data-action=${kind}]`)!.click()
  return { editor, ribbon, click, baseline: editor.getJSON() }
}
const values = (editor: Editor) => computeListValues(editor.getJSON().content!.map(n => ({ numId: n.attrs!.numId, ilvl: n.attrs!.ilvl })), editor.storage.listNumbering.defs)
it('普通Home编号复用未被正文引用的同类定义，独立num重新从1开始并可继续设置编号值', () => {
  const { editor, baseline, click } = fixture(new Map([['11', { numId: '11', abstractNumId: '7', levels: { 0: { numFmt: 'upperRoman', lvlText: '%1)', start: 4 } }, startOverrides: {} }]]))
  click('numbering')
  expect(values(editor)).toEqual([1, 2])
  const binding = editor.getJSON().content![0]!.attrs!.nativeNumberingBinding
  expect(binding).toMatchObject({ sourceNumId: '11', startOverrides: { 0: 1 } })
  expect(editor.storage.listNumbering.defs.get(editor.getJSON().content![0]!.attrs!.numId)!.abstractNumId).toBe('7')
  editor.commands.setTextSelection(4); setDocxNumberingValue(editor, anchors, { mode: 'restart', value: 9 })
  expect(values(editor)).toEqual([1, 9])
  const current = editor.getJSON(), operations = docxOperations(baseline, current, anchors)
  expect(editor.schema.nodeFromJSON(replayDocxOperations(baseline, operations, anchors)).toJSON()).toEqual(current)
  expect(current.content![0]!.content![0]!.marks).toEqual([{ type: 'bold' }])
})
it('普通Home项目符号未使用的源定义在草稿回放后仍是bullet', () => {
  const { editor, baseline, click } = fixture(new Map([['12', { numId: '12', abstractNumId: '8', levels: { 0: { numFmt: 'bullet', lvlText: '◆', start: 1 } }, startOverrides: {} }]]))
  click('bullets')
  const current = editor.getJSON(), operations = docxOperations(baseline, current, anchors)
  expect(current.content![0]!.attrs!.nativeNumberingBinding).toMatchObject({ sourceNumId: '12' })
  expect(editor.schema.nodeFromJSON(replayDocxOperations(baseline, operations, anchors)).toJSON()).toEqual(current)
})
it('无编号定义时采用源五级默认定义，restart与草稿恢复/UndoRedo不脱离正文历史', () => {
  const { editor, baseline, click } = fixture()
  click('numbering')
  expect(values(editor)).toEqual([1, 2])
  const first = editor.getJSON(), binding = first.content![0]!.attrs!.nativeNumberingBinding
  expect(binding.defaultNumbering).toMatchObject({ kind: 'ordered' })
  expect(editor.storage.listNumbering.defs.get(first.content![0]!.attrs!.numId)!.levels[4]).toMatchObject({ numFmt: 'decimal', lvlText: '%5.', indentLeft: 3600, hanging: 360 })
  editor.commands.setTextSelection(4); setDocxNumberingValue(editor, anchors, { mode: 'restart', value: 6 })
  expect(values(editor)).toEqual([1, 6])
  const current = editor.getJSON(), ops = docxOperations(baseline, current, anchors)
  expect(ops[0]!.binding).toHaveProperty('defaultNumbering')
  expect(editor.schema.nodeFromJSON(replayDocxOperations(baseline, ops, anchors)).toJSON()).toEqual(current)
  expect(editor.commands.undo()).toBe(true); expect(editor.getJSON()).toEqual(first)
  expect(editor.commands.undo()).toBe(true); expect(editor.getJSON()).toEqual(baseline)
  expect([...editor.storage.listNumbering.defs.keys()].filter(id => id.startsWith('native-'))).toEqual([])
  expect(editor.commands.redo()).toBe(true); expect(editor.getJSON()).toEqual(first)
})
it('切换同类列表清除待保存定义且只读来源不改正文', () => {
  const { editor, baseline, click } = fixture()
  click('bullets'); expect(editor.getJSON().content!.map(n => n.attrs!.kind)).toEqual(['bullet', 'bullet'])
  click('bullets'); expect(editor.getJSON()).toEqual(baseline)
  editor.setEditable(false); click('numbering'); expect(editor.getJSON()).toEqual(baseline)
})
it('Home标题转列表与清除仍保留原始标题身份和样式', () => {
  const { editor, click } = fixture()
  editor.commands.setContent({ type: 'doc', content: [{ type: 'docHeading', attrs: { docxIndex: 0, styleId: 'Heading1', level: 2 }, content: [{ type: 'text', text: '标题' }] }] })
  editor.storage.nativeDocxCustomList.sourceDoc = editor.state.doc
  editor.commands.setTextSelection(1)
  const baseline = editor.getJSON()
  click('numbering')
  expect(editor.state.doc.firstChild!.type.name).toBe('docListItem')
  expect(docxOperations(baseline, editor.getJSON(), anchors)).toHaveLength(1)
  click('numbering')
  expect(editor.getJSON()).toEqual(baseline)
})
