import { afterEach, expect, it } from 'vitest'
import { Editor } from '@tiptap/core'
import { flushSync } from 'react-dom'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations, replayDocxOperations, type DocxPmNode } from './docx-operations'

const anchors = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'hash0', editable: true }]
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function setup(attrs: Record<string, unknown> = {}) {
  const editor = new Editor({ extensions: editorExtensions, editorProps: { handleScrollToSelection: () => true }, content: {
    type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, indentLeft: 720, indentRight: 360, ...attrs }, content: [{ type: 'text', text: '特殊缩进正文' }] }],
  } })
  editors.push(editor); editor.commands.setTextSelection(2)
  const root = document.body.appendChild(document.createElement('div'))
  root.append(createDocxRibbon(editor, true, undefined, undefined, undefined, anchors))
  const open = () => flushSync(() => {
    root.querySelector<HTMLButtonElement>('[data-action="line-spacing"]')!.click()
    const button = root.querySelector<HTMLButtonElement>('[data-action="special-indent-options"]')
    expect(button).not.toBeNull(); button!.click()
  })
  return { editor, root, open }
}

it.each([365, -480, 0])('collects and replays special indent %s while preserving left/right indents and text', twips => {
  const original: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, indentLeft: 720, indentRight: 360, indentFirstLine: 480, indentFirstLineChars: 200 }, content: [{ type: 'text', text: '原文' }] }] }
  const current = structuredClone(original)
  Object.assign(current.content![0]!.attrs!, { indentFirstLine: twips, indentFirstLineChars: null })
  const operations = [{ kind: 'setParagraphSpecialIndent', blockId: 'p0', expectedObjectSha256: 'hash0', twips }]
  expect(docxOperations(original, current, anchors)).toEqual(operations)
  expect(replayDocxOperations(original, operations, anchors)).toEqual(current)
})

it.each([['firstLine', '18.25', 365], ['hanging', '24', -480], ['none', '', 0]] as const)('sets %s through the Ribbon with one undo/redo', (kind, points, twips) => {
  const { editor, root, open } = setup({ indentFirstLine: 480, indentFirstLineChars: 200 }), original = editor.getJSON()
  open()
  expect(root.querySelector('[data-character-warning]')!.textContent).toContain('字符')
  const select = root.querySelector<HTMLSelectElement>('[aria-label="特殊缩进类型"]')!
  select.value = kind; select.dispatchEvent(new Event('change', { bubbles: true }))
  const unit = root.querySelector<HTMLSelectElement>('[aria-label="特殊缩进单位"]')
  if (kind === 'firstLine' && unit) { unit.value = 'pt'; unit.dispatchEvent(new Event('change', { bubbles: true })) }
  if (kind !== 'none') root.querySelector<HTMLInputElement>('[aria-label="缩进值（pt）"]')!.value = points
  flushSync(() => root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(root.querySelector('[role="dialog"]')).toBeNull()
  expect(editor.state.doc.firstChild!.attrs).toMatchObject({ indentLeft: 720, indentRight: 360, indentFirstLine: twips, indentFirstLineChars: null })
  expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([{ kind: 'setParagraphSpecialIndent', blockId: 'p0', expectedObjectSha256: 'hash0', twips }])
  flushSync(() => { editor.commands.undo() }); expect(editor.getJSON()).toEqual(original)
  flushSync(() => { editor.commands.redo() }); expect(editor.state.doc.firstChild!.attrs.indentFirstLine).toBe(twips)
})

it.each(['', '-1', '0', '720.05', '18.123'])('keeps invalid special indent %j unchanged', value => {
  const { editor, root, open } = setup(), original = editor.getJSON(); open()
  const select = root.querySelector<HTMLSelectElement>('[aria-label="特殊缩进类型"]')!
  select.value = 'firstLine'; select.dispatchEvent(new Event('change', { bubbles: true }))
  root.querySelector<HTMLInputElement>('[aria-label="缩进值（pt）"]')!.value = value
  root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  expect(editor.getJSON()).toEqual(original)
  expect(root.querySelector('[role="alert"]')!.textContent).toContain('0.05–720')
})

it('cancels character-unit sources without changing them', () => {
  const { editor, root, open } = setup({ indentFirstLine: 480, indentFirstLineChars: 200 }), original = editor.getJSON(); open()
  expect(root.querySelector<HTMLSelectElement>('[aria-label="特殊缩进单位"]')!.value).toBe('chars')
  expect(root.querySelector<HTMLInputElement>('[aria-label="缩进值（字符）"]')!.value).toBe('2')
  root.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
  expect(editor.getJSON()).toEqual(original)
})

it('preserves native character units through Ribbon, draft replay and one undo/redo using the first run size', () => {
  const { editor, root, open } = setup()
  editor.commands.setContent({ type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, indentLeft: 720, indentRight: 360 }, content: [
    { type: 'text', text: '首', marks: [{ type: 'docTextStyle', attrs: { sizeHalfPoints: 24 } }] },
    { type: 'text', text: '光标在这里', marks: [{ type: 'docTextStyle', attrs: { sizeHalfPoints: 40 } }] },
  ] }] })
  editor.commands.setTextSelection(5)
  const before = editor.getJSON(); open()
  const kind = root.querySelector<HTMLSelectElement>('[aria-label="特殊缩进类型"]')!
  kind.value = 'firstLine'; kind.dispatchEvent(new Event('change', { bubbles: true }))
  const unit = root.querySelector<HTMLSelectElement>('[aria-label="特殊缩进单位"]')!
  expect(unit).not.toBeNull(); unit.value = 'chars'; unit.dispatchEvent(new Event('change', { bubbles: true }))
  root.querySelector<HTMLInputElement>('[aria-label="缩进值（字符）"]')!.value = '2.35'
  flushSync(() => root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  const current = editor.getJSON(), ops = [{ kind: 'setParagraphSpecialIndent', blockId: 'p0', expectedObjectSha256: 'hash0', twips: 564, firstLineChars: 235 }]
  expect(docxOperations(before, current, anchors)).toEqual(ops)
  expect(replayDocxOperations(before, ops, anchors)).toEqual(current)
  flushSync(() => { editor.commands.undo() }); expect(editor.getJSON()).toEqual(before)
  flushSync(() => { editor.commands.redo() }); expect(editor.getJSON()).toEqual(current)
  expect(current.content![0]!.attrs).toMatchObject({ indentLeft: 720, indentRight: 360 })
})

it('resolves character fallback from paragraph style and clears character units when switching to hanging', () => {
  const { editor, root, open } = setup({ styleId: 'Body' }), original = editor.getJSON()
  editor.storage.listNumbering.styles = new Map([['Body', { styleId: 'Body', type: 'paragraph', name: 'Body', display: { sizeHalfPoints: 36 } }]])
  open()
  const kind = root.querySelector<HTMLSelectElement>('[aria-label="特殊缩进类型"]')!
  kind.value = 'firstLine'; kind.dispatchEvent(new Event('change', { bubbles: true }))
  const unit = root.querySelector<HTMLSelectElement>('[aria-label="特殊缩进单位"]')!
  unit.value = 'chars'; unit.dispatchEvent(new Event('change', { bubbles: true }))
  root.querySelector<HTMLInputElement>('[aria-label="缩进值（字符）"]')!.value = '2.35'
  flushSync(() => root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([{ kind: 'setParagraphSpecialIndent', blockId: 'p0', expectedObjectSha256: 'hash0', twips: 846, firstLineChars: 235 }])
  open()
  const nextKind = root.querySelector<HTMLSelectElement>('[aria-label="特殊缩进类型"]')!
  nextKind.value = 'hanging'; nextKind.dispatchEvent(new Event('change', { bubbles: true }))
  expect(root.querySelector<HTMLSelectElement>('[aria-label="特殊缩进单位"]')!.disabled).toBe(true)
  root.querySelector<HTMLInputElement>('[aria-label="缩进值（pt）"]')!.value = '24'
  flushSync(() => root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(docxOperations(original, editor.getJSON(), anchors)).toEqual([{ kind: 'setParagraphSpecialIndent', blockId: 'p0', expectedObjectSha256: 'hash0', twips: -480 }])
})

it.each(['', '0', '-1', '100.01', '2.345', '61'])('rejects invalid or oversized character input %j without creating a draft', value => {
  const { editor, root, open } = setup({ indentFirstLine: 480, indentFirstLineChars: 200 }), original = editor.getJSON(); open()
  const input = root.querySelector<HTMLInputElement>('[aria-label="缩进值（字符）"]')!
  expect(input).not.toBeNull(); input.value = value
  root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  expect(editor.getJSON()).toEqual(original)
  expect(root.querySelector('[role="alert"]')!.textContent).toContain('字符')
})

it.each([0, -1, 10001, 1.5, null, true, '235'])('rejects invalid character-unit draft %j', firstLineChars => {
  const original: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 } }] }
  expect(() => replayDocxOperations(original, [{ kind: 'setParagraphSpecialIndent', blockId: 'p0', expectedObjectSha256: 'hash0', twips: 564, firstLineChars }], anchors)).toThrow()
})

it('does not accept hanging twips with first-line character units', () => {
  const original: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 } }] }
  expect(() => replayDocxOperations(original, [{ kind: 'setParagraphSpecialIndent', blockId: 'p0', expectedObjectSha256: 'hash0', twips: -480, firstLineChars: 200 }], anchors)).toThrow()
})

it.each(['document', 'selection', 'readonly'])('refuses special-indent confirmation after %s changes', change => {
  const { editor, root, open } = setup(); open()
  if (change === 'document') flushSync(() => { editor.commands.insertContent('变化') })
  else if (change === 'selection') flushSync(() => { editor.commands.setTextSelection(3) })
  else flushSync(() => { editor.setEditable(false) })
  const original = editor.getJSON()
  root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  expect(editor.getJSON()).toEqual(original)
  expect(root.querySelector('[role="alert"]')!.textContent).toContain('重新打开')
})

it.each([-14401, 14401, 1.5, null, true, '365'])('rejects invalid special-indent draft %j', twips => {
  const original: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 } }] }
  expect(() => replayDocxOperations(original, [{ kind: 'setParagraphSpecialIndent', blockId: 'p0', expectedObjectSha256: 'hash0', twips }], anchors)).toThrow()
})

it('rejects forged identities and list targets for special-indent recovery', () => {
  const original: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 } }] }
  const op = { kind: 'setParagraphSpecialIndent', blockId: 'p0', expectedObjectSha256: 'forged', twips: 365 }
  expect(() => replayDocxOperations(original, [op], anchors)).toThrow()
  original.content![0]!.type = 'docListItem'
  expect(() => replayDocxOperations(original, [{ ...op, expectedObjectSha256: 'hash0' }], anchors)).toThrow()
})
