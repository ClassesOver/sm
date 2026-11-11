import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { flushSync } from 'react-dom'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'

const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'body-0', expectedObjectSha256: 'sha-0', editable: true }]
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function setup(text: string, marks: { type: string }[] = [], extra?: DocxPmNode) {
  let baseline: DocxPmNode | undefined
  const rejected: string[] = [], errors: unknown[] = []
  const Guard = Extension.create({ name: 'testNativeGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) {
    if (!baseline || !tr.docChanged) return true
    try { docxOperations(baseline, tr.doc.toJSON() as DocxPmNode, anchors, undefined, editor.schema); return true } catch (error) { rejected.push((error as Error).message); return false }
  } })] })
  const editor = new Editor({ extensions: [...editorExtensions, Guard], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text, marks }, ...(extra ? [extra] : [])] },
  ] } })
  editors.push(editor); baseline = editor.getJSON() as DocxPmNode
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, anchors, undefined, undefined, undefined, error => errors.push(error))
  document.body.append(ribbon)
  const click = (action: string) => flushSync(() => {
    const button = ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!
    expect(button, action).not.toBeNull(); expect(button.disabled, button.title).toBe(false); button.click()
  })
  return { editor, baseline, ribbon, click, rejected, errors }
}

it.each([
  ['upper', 'straße', 'STRASSE'], ['lower', 'HeLLo', 'hello'], ['title', 'hELLO woRLD', 'Hello World'],
  ['sentence', 'hELLO. wORLD', 'Hello. World'], ['toggle', 'AbC', 'aBc'],
  ['fullWidth', 'A 1 ｶﾞ', 'Ａ　１　ガ'], ['halfWidth', 'Ａ　１　ガ', 'A 1 ｶﾞ'],
])('converts selected text using %s, keeps marks and replays native operations', (mode, input, output) => {
  const { editor, baseline, click, rejected } = setup(input, [{ type: 'bold' }])
  editor.commands.setTextSelection({ from: 1, to: input.length + 1 })
  click('change-case'); click(`change-case:${mode}`)
  expect(editor.state.doc.textContent).toBe(output)
  expect(editor.state.selection.from).toBe(1); expect(editor.state.selection.to).toBe(output.length + 1)
  expect(editor.getJSON().content![0].content![0].marks).toContainEqual({ type: 'bold' })
  expect(rejected).toEqual([])
  const operations = docxOperations(baseline, editor.getJSON() as DocxPmNode, anchors, undefined, editor.schema)
  expect(operations).toEqual([{ kind: 'replaceParagraph', blockId: 'body-0', expectedObjectSha256: 'sha-0', text: output }])
  const restored = replayDocxOperations(baseline, operations, anchors, undefined, editor.schema)
  expect(docxOperations(baseline, restored, anchors, undefined, editor.schema)).toEqual(operations)
  editor.commands.undo(); expect(editor.getJSON()).toEqual(baseline)
  editor.commands.redo(); expect(editor.state.doc.textContent).toBe(output)
})

it('changes only a selected substring and disables collapsed, readonly and mixed-format selections', () => {
  const { editor, ribbon, click } = setup('hello world')
  const button = () => ribbon.querySelector<HTMLButtonElement>('[data-action="change-case"]')!
  expect(button().disabled).toBe(true)
  editor.commands.setTextSelection({ from: 2, to: 5 }); click('change-case'); click('change-case:upper')
  expect(editor.state.doc.textContent).toBe('hELLo world')
  editor.setEditable(false); expect(button().disabled).toBe(true)
  const mixed = setup('straße', [{ type: 'bold' }], { type: 'text', text: ' next' })
  mixed.editor.commands.setTextSelection({ from: 1, to: 7 })
  expect(mixed.ribbon.querySelector<HTMLButtonElement>('[data-action="change-case"]')!.disabled).toBe(true)
  expect(mixed.editor.state.doc.textContent).toBe('straße next')
})
