import { afterEach, expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { flushSync } from 'react-dom'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations, replayDocxOperations, type DocxPmNode } from './docx-operations'

const anchors = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'hash0', editable: true }]
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function setup() {
  const editor = new Editor({ extensions: editorExtensions, editorProps: { handleScrollToSelection: () => true }, content: {
    type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '行距目标正文' }] }],
  } })
  editors.push(editor)
  editor.commands.setTextSelection(2)
  const root = document.createElement('div'); document.body.append(root)
  root.append(createDocxRibbon(editor, true, undefined, undefined, undefined, anchors))
  const open = () => flushSync(() => {
    root.querySelector<HTMLButtonElement>('[data-action="line-spacing"]')!.click()
    root.querySelector<HTMLButtonElement>('[data-action="line-spacing-options"]')!.click()
  })
  return { editor, root, open }
}

it.each(['exact', 'atLeast'])('collects and recovers %s spacing without changing text or other paragraph attributes', lineRule => {
  const original: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, align: 'right', spaceAfter: 120, lineSpacing: 1.5, lineRule: null, lineRawTwips: null }, content: [{ type: 'text', text: '不改正文' }] }] }
  const current = structuredClone(original)
  Object.assign(current.content![0]!.attrs!, { lineSpacing: null, lineRule, lineRawTwips: 365 })
  const operations = [{ kind: 'setParagraphSpacing', blockId: 'p0', expectedObjectSha256: 'hash0', lineRule, lineRawTwips: 365 }]
  expect(docxOperations(original, current, anchors)).toEqual(operations)
  expect(replayDocxOperations(original, operations, anchors)).toEqual(current)
})

it('applies exact point spacing through the real Ribbon and supports one undo and redo', () => {
  const { editor, root, open } = setup(), original = editor.getJSON()
  expect(root.querySelector<HTMLButtonElement>('[data-action="line-spacing-options"]')!.disabled).toBe(false)
  open()
  const dialog = root.querySelector<HTMLElement>('[role="dialog"][aria-label="段落行距"]')!
  const rule = dialog.querySelector<HTMLSelectElement>('[aria-label="行距类型"]')!
  rule.value = 'exact'; rule.dispatchEvent(new Event('change', { bubbles: true }))
  const input = dialog.querySelector<HTMLInputElement>('[aria-label="行距值（pt）"]')!
  input.value = '18.25'
  flushSync(() => dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(root.querySelector('[role="dialog"]')).toBeNull()
  expect(editor.state.doc.firstChild!.attrs).toMatchObject({ lineSpacing: null, lineRule: 'exact', lineRawTwips: 365 })
  expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([{ kind: 'setParagraphSpacing', blockId: 'p0', expectedObjectSha256: 'hash0', lineRule: 'exact', lineRawTwips: 365 }])
  flushSync(() => { editor.commands.undo() }); expect(editor.getJSON()).toEqual(original)
  flushSync(() => { editor.commands.redo() }); expect(editor.state.doc.firstChild!.attrs.lineRawTwips).toBe(365)
})

it('retains an existing minimum spacing value, cancels unchanged, and clears its rule for a preset', () => {
  const { editor, root, open } = setup()
  editor.view.dispatch(editor.state.tr.setNodeMarkup(0, undefined, { ...editor.state.doc.firstChild!.attrs, lineSpacing: null, lineRule: 'atLeast', lineRawTwips: 365 }))
  const original = editor.getJSON()
  open()
  expect(root.querySelector<HTMLSelectElement>('[aria-label="行距类型"]')!.value).toBe('atLeast')
  expect(root.querySelector<HTMLInputElement>('[aria-label="行距值（pt）"]')!.value).toBe('18.25')
  root.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
  expect(editor.getJSON()).toEqual(original)
  open()
  const rule = root.querySelector<HTMLSelectElement>('[aria-label="行距类型"]')!
  rule.value = 'multiple'; rule.dispatchEvent(new Event('change', { bubbles: true }))
  root.querySelector<HTMLInputElement>('[aria-label="行距倍数"]')!.value = '1.5'
  flushSync(() => root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(editor.state.doc.firstChild!.attrs).toMatchObject({ lineSpacing: 1.5, lineRule: null, lineRawTwips: null })
})

it.each([0.06, 1.23, 4, 132])('collects and recovers the custom multiple %s without losing other attributes', lineSpacing => {
  const original: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, align: 'right', spaceAfter: 120, lineSpacing: null, lineRule: 'exact', lineRawTwips: 365 }, content: [{ type: 'text', text: '正文保留' }] }] }
  const current = structuredClone(original)
  Object.assign(current.content![0]!.attrs!, { lineSpacing, lineRule: null, lineRawTwips: null })
  const operations = [{ kind: 'setParagraphSpacing', blockId: 'p0', expectedObjectSha256: 'hash0', lineSpacing }]
  expect(docxOperations(original, current, anchors)).toEqual(operations)
  expect(replayDocxOperations(original, operations, anchors)).toEqual(current)
})

it('edits a custom multiple through the Ribbon, preserves it on reopen, and supports undo/redo', () => {
  const { editor, root, open } = setup(), original = editor.getJSON()
  open()
  const input = root.querySelector<HTMLInputElement>('input[aria-label="行距倍数"]')
  expect(input).not.toBeNull()
  input!.value = '1.23'
  flushSync(() => root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(root.querySelector('[role="dialog"]')).toBeNull()
  expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([{ kind: 'setParagraphSpacing', blockId: 'p0', expectedObjectSha256: 'hash0', lineSpacing: 1.23 }])
  flushSync(() => { editor.commands.undo() }); expect(editor.getJSON()).toEqual(original)
  flushSync(() => { editor.commands.redo() }); expect(editor.state.doc.firstChild!.attrs.lineSpacing).toBe(1.23)
  const current = editor.getJSON()
  open(); expect(root.querySelector<HTMLInputElement>('[aria-label="行距倍数"]')!.value).toBe('1.23')
  root.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
  expect(editor.getJSON()).toEqual(current)
})

it.each(['', '0', '0.05', '132.01', '1.234'])('rejects invalid custom multiple %j without changing the document', value => {
  const { editor, root, open } = setup(), original = editor.getJSON()
  open()
  const input = root.querySelector<HTMLInputElement>('input[aria-label="行距倍数"]')
  expect(input).not.toBeNull()
  input!.value = value
  root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  expect(editor.getJSON()).toEqual(original)
  expect(root.querySelector('[role="dialog"] [role="alert"]')!.textContent).toContain('0.06–132')
})

it.each([0.05, 132.01, 1.234, NaN, Infinity, null, true, '1.23'])('rejects invalid custom multiple draft %j', lineSpacing => {
  const original: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 } }] }
  expect(() => replayDocxOperations(original, [{ kind: 'setParagraphSpacing', blockId: 'p0', expectedObjectSha256: 'hash0', lineSpacing }], anchors)).toThrow()
})

it.each(['', '0', '1584.05', '18.123'])('keeps the dialog and document unchanged for invalid points %j', value => {
  const { editor, root, open } = setup(), original = editor.getJSON()
  open()
  const rule = root.querySelector<HTMLSelectElement>('[aria-label="行距类型"]')!
  rule.value = 'exact'; rule.dispatchEvent(new Event('change', { bubbles: true }))
  root.querySelector<HTMLInputElement>('[aria-label="行距值（pt）"]')!.value = value
  root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  expect(editor.getJSON()).toEqual(original)
  expect(root.querySelector('[role="dialog"] [role="alert"]')!.textContent).toContain('1–1584')
})

it.each(['document', 'selection', 'readonly'])('refuses an open dialog after its %s changes', change => {
  const { editor, root, open } = setup()
  open()
  const rule = root.querySelector<HTMLSelectElement>('[aria-label="行距类型"]')!
  rule.value = 'exact'; rule.dispatchEvent(new Event('change', { bubbles: true }))
  if (change === 'document') flushSync(() => { editor.commands.insertContent('变化') })
  else if (change === 'selection') flushSync(() => { editor.commands.setTextSelection(3) })
  else flushSync(() => { editor.setEditable(false) })
  const before = editor.getJSON()
  root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  expect(editor.getJSON()).toEqual(before)
  expect(root.querySelector('[role="dialog"] [role="alert"]')!.textContent).toContain('重新打开')
})

it.each([
  { lineRule: 'exact' }, { lineRawTwips: 360 }, { lineRule: 'auto', lineRawTwips: 360 },
  { lineRule: 'exact', lineRawTwips: 0 }, { lineRule: 'exact', lineRawTwips: 31681 },
  { lineRule: 'atLeast', lineRawTwips: 360.5 }, { lineRule: 'exact', lineRawTwips: 360, lineSpacing: 2 },
])('rejects incomplete, mixed or invalid line-spacing drafts: %j', values => {
  const original: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '正文' }] }] }
  expect(() => replayDocxOperations(original, [{ kind: 'setParagraphSpacing', blockId: 'p0', expectedObjectSha256: 'hash0', ...values }], anchors)).toThrow()
})

it.each([
  { lineSpacing: 1.04, lineRule: 'auto', lineRawTwips: 250 },
  { lineSpacing: null, lineRule: null, lineRawTwips: null },
])('confirms unchanged displayed spacing without rewriting the source %j', attrs => {
  const { editor, root, open } = setup()
  editor.view.dispatch(editor.state.tr.setNodeMarkup(0, undefined, { ...editor.state.doc.firstChild!.attrs, ...attrs }))
  const original = editor.getJSON(), before = editor.state.doc
  open()
  expect(root.querySelector<HTMLInputElement>('[aria-label="行距倍数"]')!.value).toBe(String(attrs.lineSpacing ?? 1))
  flushSync(() => root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(root.querySelector('[role="dialog"]')).toBeNull()
  expect(editor.state.doc).toBe(before)
  expect(editor.getJSON()).toEqual(original)
  expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([])
})
