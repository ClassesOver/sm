import { afterEach, expect, it } from 'vitest'
import { Editor, Mark, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { flushSync } from 'react-dom'
import { createDocxRibbon } from './docx-ribbon'
import { applyParagraphHighlight, DOCX_HIGHLIGHTS, highlightTarget, paragraphHighlight, withoutHighlight } from './docx-highlight'
import { docxOperations, replayDocxOperations, type DocxAnchor } from './docx-operations'
import { NativeDraft } from './native-draft'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => ({ docxIndex: { default: null } }), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const Bold = Mark.create({ name: 'bold', renderHTML: () => ['b', 0] })
const Italic = Mark.create({ name: 'italic', renderHTML: () => ['i', 0] })
const Style = Mark.create({ name: 'docTextStyle', addAttributes: () => Object.fromEntries(['highlight', 'color', 'font', 'sizeHalfPoints', 'rawRPr', 'themeColor', 'vertAlign', 'shading'].map(key => [key, { default: null }])), renderHTML: () => ['span', 0] })
const Link = Mark.create({ name: 'link', addAttributes: () => ({ href: { default: '' }, rId: { default: null }, tooltip: { default: null }, plain: { default: false } }), renderHTML: () => ['a', 0] })
const anchor: DocxAnchor = { docxIndex: 0, blockId: 'body', expectedObjectSha256: 'source-sha', editable: true }
const anchors = [anchor]
const editors: Editor[] = []
function setup() {
  const editor = new Editor({ extensions: [Doc, Paragraph, Text, Style, Bold, Italic, Link, UndoRedo], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0 }, content: [
      { type: 'text', text: 'A😀', marks: [{ type: 'bold' }, { type: 'docTextStyle', attrs: { highlight: 'yellow', color: 'AABBCC', font: 'Calibri', rawRPr: '<w:rPr><w:noProof/></w:rPr>', themeColor: 'AABBCC' } }] },
      { type: 'text', text: 'BC', marks: [{ type: 'italic' }, { type: 'docTextStyle', attrs: { highlight: 'cyan', shading: 'EEEEEE' } }] },
      { type: 'text', text: 'keep', marks: [{ type: 'link', attrs: { href: 'https://keep.test', rId: 'rId4', tooltip: 'keep', plain: true } }] },
    ] }, { type: 'docParagraph', attrs: { docxIndex: null }, content: [{ type: 'text', text: 'new' }] },
  ] } })
  editors.push(editor)
  editor.commands.setTextSelection(2)
  return editor
}
const sourceOnly = (editor: Editor) => ({ ...editor.getJSON(), content: editor.getJSON().content!.slice(0, 1) })
const op = (highlight: unknown) => ({ kind: 'formatParagraph', blockId: 'body', expectedObjectSha256: 'source-sha', style: { highlight } })
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren(); localStorage.clear() })

it.each([...DOCX_HIGHLIGHTS, 'white', 'none'])('applies legal %s to the whole anchored paragraph without flattening mixed marks or links', value => {
  const editor = setup(), original = sourceOnly(editor)
  expect(applyParagraphHighlight(editor, anchors, value)).toBe(true)
  const current = sourceOnly(editor)
  expect(paragraphHighlight(current.content[0])).toBe(value)
  expect(withoutHighlight(current.content[0])).toEqual(withoutHighlight(original.content[0]))
  expect(docxOperations(original, current, anchors)).toEqual([op(value)])
  const restored = replayDocxOperations(original, [op(value)], anchors)
  expect(docxOperations(original, restored, anchors)).toEqual([op(value)])
  expect(withoutHighlight(restored.content![0])).toEqual(withoutHighlight(original.content[0]))
  editor.commands.undo()
  expect(sourceOnly(editor)).toEqual(original)
  editor.commands.redo()
  expect(sourceOnly(editor)).toEqual(current)
})

it('retains explicit none over an unhighlighted/inherited source and gives each command its own undo step', () => {
  const editor = setup()
  applyParagraphHighlight(editor, anchors, 'none')
  const cleared = sourceOnly(editor)
  applyParagraphHighlight(editor, anchors, 'darkBlue')
  editor.commands.undo()
  expect(sourceOnly(editor)).toEqual(cleared)
  editor.commands.redo()
  expect(paragraphHighlight(sourceOnly(editor).content[0])).toBe('darkBlue')
  const inherited = structuredClone(cleared)
  for (const run of inherited.content[0].content!) {
    const style = run.marks?.find(mark => mark.type === 'docTextStyle')
    if (style) style.attrs!.highlight = null
  }
  expect(docxOperations(inherited, cleared, anchors)).toEqual([op('none')])
})

it('restores persisted highlight operations with unchanged source identities and draft undo/redo', () => {
  const editor = setup(), original = sourceOnly(editor)
  const identity = { documentId: 'docx-highlight', revision: 1, sourceSha256: 'sha', scope: { database: 'db', companyId: 'company', userId: 'user', threadId: 'thread' } }
  const draft = new NativeDraft(identity, localStorage)
  applyParagraphHighlight(editor, anchors, 'none')
  draft.setOperations(docxOperations(original, sourceOnly(editor), anchors))
  const restoredDraft = new NativeDraft(identity, localStorage)
  expect(restoredDraft.operations).toEqual([op('none')])
  const restored = replayDocxOperations(original, restoredDraft.operations, anchors)
  expect(docxOperations(original, restored, anchors)).toEqual([op('none')])
  draft.undo(); expect(draft.operations).toEqual([])
  draft.redo(); expect(draft.operations).toEqual([op('none')])
  draft.beginSave()
  expect(() => draft.setOperations([op('yellow')])).toThrow(/正在保存/)
  draft.saveFailed()
})

it.each([null, true, 1, '#FFFF00', 'FFFF00', 'accent1', 'Yellow', '', {}, []])('rejects invalid enum %j in command and replay', value => {
  const editor = setup(), original = sourceOnly(editor)
  expect(() => applyParagraphHighlight(editor, anchors, value)).toThrow(/高亮/)
  expect(() => replayDocxOperations(original, [op(value)], anchors)).toThrow(/高亮/)
  expect(sourceOnly(editor)).toEqual(original)
})

it('saves partial highlight edits and rejects stale/foreign draft fields', () => {
  const editor = setup(), original = sourceOnly(editor)
  editor.commands.setTextSelection({ from: 1, to: 2 })
  editor.commands.setMark('docTextStyle', { highlight: 'green' })
  expect(docxOperations(original, sourceOnly(editor), anchors)).toEqual([{ ...op('green'), kind: 'formatRange', from: 0, to: 1 }])
  expect(() => replayDocxOperations(original, [{ ...op('none'), expectedObjectSha256: 'foreign' }], anchors)).toThrow(/身份/)
  expect(() => replayDocxOperations(original, [{ ...op('none'), rawRPr: '<w:rPr/>' }], anchors)).toThrow(/字段/)
  expect(() => replayDocxOperations(original, [{ ...op('none'), style: { highlight: 'none', themeColor: 'accent1' } }], anchors)).toThrow(/字段/)
})

it('reuses the source palette, preserves document selection on palette presses, and honors save locks', () => {
  const editor = setup(), original = sourceOnly(editor)
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, anchors)
  document.body.append(ribbon)
  const button = (action: string) => ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!
  expect(button('highlight').disabled).toBe(false)
  flushSync(() => button('highlight-palette').click())
  expect(ribbon.querySelectorAll('.color-highlight-swatch')).toHaveLength(15)
  const selection = editor.state.selection.toJSON()
  const swatch = button('highlight-darkGreen')
  const pointer = new Event('pointerdown', { bubbles: true, cancelable: true })
  swatch.dispatchEvent(pointer)
  expect(pointer.defaultPrevented).toBe(false)
  const mouse = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
  swatch.dispatchEvent(mouse)
  expect(mouse.defaultPrevented).toBe(true)
  expect(ribbon.querySelector('.docx-ribbon-highlight-palette')).not.toBeNull()
  expect(document.documentElement.classList.contains('genoffice-popover-open')).toBe(true)
  flushSync(() => swatch.click())
  expect(ribbon.querySelector('.docx-ribbon-highlight-palette')).not.toBeNull()
  expect(document.documentElement.classList.contains('genoffice-popover-open')).toBe(true)
  expect(editor.state.selection.toJSON()).toEqual(selection)
  expect(docxOperations(original, sourceOnly(editor), anchors)).toEqual([op('darkGreen')])
  editor.commands.undo()
  // A transaction rerender must retain the actual focusable swatch and its handlers.
  const yellow = button('highlight-yellow')
  yellow.focus()
  editor.commands.setMeta('palette-focus-regression', true)
  expect(document.activeElement).toBe(yellow)
  expect(button('highlight-yellow')).toBe(yellow)
  const yellowMouse = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
  yellow.dispatchEvent(yellowMouse)
  expect(yellowMouse.defaultPrevented).toBe(true)
  flushSync(() => yellow.click())
  expect(docxOperations(original, sourceOnly(editor), anchors)).toEqual([op('yellow')])
  flushSync(() => button('highlight-none').click())
  expect(docxOperations(original, sourceOnly(editor), anchors)).toEqual([op('none')])
  editor.setEditable(false); editor.commands.setMeta('saving', true)
  expect(button('highlight').disabled).toBe(true)
  expect(button('highlight-palette').disabled).toBe(true)
  const locked = sourceOnly(editor)
  expect(applyParagraphHighlight(editor, anchors, 'red')).toBe(false)
  expect(sourceOnly(editor)).toEqual(locked)
  editor.setEditable(true)
  editor.commands.setTextSelection(editor.state.doc.content.size - 1)
  expect(highlightTarget(editor, anchors)).toBeUndefined()
  expect(button('highlight').disabled).toBe(true)
  editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 })
  expect(button('highlight').disabled).toBe(true)
  editor.commands.setTextSelection(2)
  expect(applyParagraphHighlight(editor, [{ ...anchor, editable: false }], 'yellow')).toBe(false)
  expect(highlightTarget(editor, [anchor, anchor])).toBeUndefined()
})

it('highlights only the selected UTF16 range and rejects a split emoji', () => {
  const editor = setup(), original = sourceOnly(editor)
  editor.commands.setTextSelection({ from: 2, to: 5 })
  expect(applyParagraphHighlight(editor, anchors, 'green')).toBe(true)
  expect(docxOperations(original, sourceOnly(editor), anchors)).toEqual([{ ...op('green'), kind: 'formatRange', from: 1, to: 4 }])
  editor.commands.undo(); expect(sourceOnly(editor)).toEqual(original)
  editor.commands.setTextSelection({ from: 2, to: 3 })
  expect(applyParagraphHighlight(editor, anchors, 'green')).toBe(false)
  expect(sourceOnly(editor)).toEqual(original)
})

it('keeps unsupported source run metadata opaque and rejects edits to it', () => {
  const editor = setup(), original = sourceOnly(editor)
  editor.commands.setTextSelection({ from: 2, to: 5 })
  applyParagraphHighlight(editor, anchors, 'green')
  const current = sourceOnly(editor)
  const run = current.content[0].content![0]
  run.marks!.find(mark => mark.type === 'docTextStyle')!.attrs!.rawRPr = '<w:rPr><w:vanish/></w:rPr>'
  expect(() => docxOperations(original, current, anchors)).toThrow(/文字样式/)
})
