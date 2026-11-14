import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Editor } from '@tiptap/core'
import { flushSync } from 'react-dom'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { measurementUnit, MEASUREMENT_UNIT_KEY, subscribeMeasurementUnit } from './vendor/genoffice-docs/apps/docs/src/renderer/units'
import { AUTOCORRECT_RULES, AUTOCORRECT_DEFAULTS, autocorrectPrefs } from './vendor/genoffice-docs/apps/docs/src/renderer/autocorrect-pref'
import { NativeDocxCustomList } from './docx-custom-list'
import { docxOperations, replayDocxOperations } from './docx-operations'
import { openDocxPreferencesDialog, installDocxAutocorrect } from './docx-preferences'
const disposers: (() => void)[] = [], editors: Editor[] = []
// List marker width is a browser canvas measurement; jsdom has no canvas implementation.
beforeEach(() => { vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null) })
afterEach(() => { disposers.splice(0).reverse().forEach(close => close()); editors.splice(0).forEach(editor => editor.destroy()); localStorage.clear(); document.body.replaceChildren(); vi.restoreAllMocks() })
const anchors = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'hash0', editable: true }]
function editorWith(text: string) {
  const editor = new Editor({ extensions: [...editorExtensions, NativeDocxCustomList], content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, align: 'center' }, ...(text ? { content: [{ type: 'text', text }] } : {}) }] } })
  editors.push(editor); editor.commands.setTextSelection(text.length + 1); disposers.push(installDocxAutocorrect(editor, anchors)); return editor
}
function type(editor: Editor, text: string) {
  let handled = false
  editor.view.someProp('handleTextInput', handler => { handled = !!handler(editor.view, editor.state.selection.from, editor.state.selection.to, text, () => editor.state.tr.insertText(text)); return handled })
  if (!handled) editor.commands.insertContent(text)
  return handled
}
it('measurement selection persists all five units and notifies existing consumers immediately', () => {
  const opener = document.createElement('button'); document.body.append(opener); opener.focus()
  disposers.push(openDocxPreferencesDialog('general'))
  const select = document.querySelector<HTMLSelectElement>('[role=dialog] select')!
  let notifications = 0; disposers.push(subscribeMeasurementUnit(() => notifications++))
  expect([...select.options].map(option => option.value)).toEqual(['in', 'cm', 'mm', 'pt', 'pi'])
  for (const unit of ['in', 'cm', 'mm', 'pt', 'pi']) {
    flushSync(() => { select.value = unit; select.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(localStorage.getItem(MEASUREMENT_UNIT_KEY)).toBe(unit); expect(measurementUnit()).toBe(unit)
  }
  expect(notifications).toBe(5)
  flushSync(() => document.querySelector('[role=dialog]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  expect(document.querySelector('[role=dialog]')).toBeNull(); expect(document.activeElement).toBe(opener)
})
it('six switches change actual typed editor preferences and reset restores defaults', () => {
  const editor = editorWith(''); disposers.push(openDocxPreferencesDialog('autocorrect'))
  const boxes = [...document.querySelectorAll<HTMLInputElement>('input[type=checkbox]')]; expect(boxes).toHaveLength(6)
  boxes.forEach((box, index) => { flushSync(() => box.click()); expect(autocorrectPrefs()[AUTOCORRECT_RULES[index]!]).toBe(!AUTOCORRECT_DEFAULTS[AUTOCORRECT_RULES[index]!]) })
  expect(type(editor, '"')).toBe(false); expect(editor.state.doc.textContent).toBe('"')
  flushSync(() => document.querySelector<HTMLButtonElement>('[data-action=autocorrect-reset]')!.click()); expect(autocorrectPrefs()).toEqual(AUTOCORRECT_DEFAULTS)
  expect(type(editor, '"')).toBe(true); expect(editor.state.doc.textContent).toBe('"”')
})
it.each(['-', '3.', 'c)'])('typed %s list preserves source identity and persists native numbering with replay and undo', prefix => {
  const editor = editorWith(prefix), baseline = editor.getJSON(); expect(type(editor, ' ')).toBe(true)
  const node = editor.state.doc.firstChild!; expect(node.type.name).toBe('docListItem'); expect(node.attrs).toMatchObject({ docxIndex: 0, align: 'center' })
  expect(editor.storage.listNumbering.defs.get(node.attrs.numId)).toBeDefined()
  const operations = docxOperations(baseline, editor.getJSON(), anchors)
  expect(operations.some(operation => operation.kind === 'setParagraphCustomList' || operation.kind === 'setParagraphNumberingValue')).toBe(true)
  expect(docxOperations(baseline, replayDocxOperations(baseline, operations, anchors), anchors)).toEqual(operations)
  if (prefix !== '-') expect(editor.storage.listNumbering.defs.get(node.attrs.numId)!.levels[0]!.start).toBe(3)
  editor.commands.undo(); expect(editor.getJSON()).toEqual(baseline)
})

it.each([
  ['smartQuotes', '', '"', '“'], ['dashes', 'a--b', ' ', 'a—b '],
  ['symbols', '(c', ')', '©'], ['capitalize', 'hello', ' ', 'Hello '],
  ['ordinals', '1st', ' ', '1st '], ['autoLists', '-', ' ', ''],
] as const)('%s switch controls real as-you-type transformations immediately', (rule, before, typed, corrected) => {
  const editor = editorWith(before), baseline = editor.getJSON()
  disposers.push(openDocxPreferencesDialog('autocorrect'))
  const box = document.querySelectorAll<HTMLInputElement>('input[type=checkbox]')[AUTOCORRECT_RULES.indexOf(rule)]!
  if (!box.checked) flushSync(() => box.click())
  expect(type(editor, typed)).toBe(true); expect(editor.state.doc.textContent).toBe(corrected)
  if (rule === 'ordinals') expect(editor.getJSON().content![0]!.content!.some(node => node.marks?.some(mark => mark.attrs?.vertAlign === 'superscript'))).toBe(true)
  if (rule === 'autoLists') expect(editor.state.doc.firstChild!.type.name).toBe('docListItem')
  editor.commands.setContent(baseline); editor.commands.setTextSelection(before.length + 1)
  flushSync(() => box.click()); expect(type(editor, typed)).toBe(false)
  expect(editor.state.doc.textContent).toBe(before + typed)
  expect(editor.state.doc.firstChild!.type.name).toBe('docParagraph')
  expect(editor.getJSON().content![0]!.content!.every(node => !node.marks?.some(mark => mark.attrs?.vertAlign === 'superscript'))).toBe(true)
})

it('list correction Backspace restores the typed prefix, source attributes and numbering overlay', () => {
  const editor = editorWith('3.'), baseline = editor.getJSON()
  expect(type(editor, ' ')).toBe(true)
  const id = editor.state.doc.firstChild!.attrs.numId
  let handled = false
  editor.view.someProp('handleKeyDown', handler => { handled = !!handler(editor.view, new KeyboardEvent('keydown', { key: 'Backspace' })); return handled })
  expect(handled).toBe(true)
  expect(editor.state.doc.textContent).toBe('3. ')
  expect(editor.state.doc.firstChild!.attrs).toMatchObject({ docxIndex: 0, align: 'center' })
  expect(editor.storage.listNumbering.defs.has(id)).toBe(false)
  expect(docxOperations(baseline, editor.getJSON(), anchors).map(operation => operation.kind)).toEqual(['replaceParagraph'])
})

it('composition Escape leaves settings open and ordinary Escape closes it', () => {
  disposers.push(openDocxPreferencesDialog('autocorrect'))
  document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', isComposing: true, bubbles: true }))
  expect(document.querySelector('[role=dialog]')).not.toBeNull()
  flushSync(() => document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  expect(document.querySelector('[role=dialog]')).toBeNull()
})

it('typed list allocation refuses readonly or missing source anchors without creating definitions', () => {
  const editor = editorWith('3.'), defs = new Map(editor.storage.listNumbering.defs)
  const cleanup = installDocxAutocorrect(editor, [{ ...anchors[0]!, editable: false }]); disposers.push(cleanup)
  expect(type(editor, ' ')).toBe(false); expect(editor.state.doc.firstChild!.type.name).toBe('docParagraph')
  expect(editor.storage.listNumbering.defs).toEqual(defs)
  cleanup()
  editor.commands.setContent({ type: 'doc', content: [{ type: 'docParagraph', content: [{ type: 'text', text: '-' }] }] }); editor.commands.setTextSelection(2)
  expect(type(editor, ' ')).toBe(false); expect(editor.state.doc.firstChild!.type.name).toBe('docParagraph')
  expect(editor.storage.listNumbering.defs).toEqual(defs)
})
