import { afterEach, expect, it, vi } from 'vitest'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { Editor, Mark, Node } from '@tiptap/core'
import { DocxInsertSource } from './docx-insert-source'
import { docxOperations } from './docx-operations'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => ({ docxIndex: { default: 0 } }), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const Link = Mark.create({ name: 'link', addAttributes: () => ({ href: { default: '' }, rId: { default: null } }), renderHTML: ({ HTMLAttributes }) => ['a', HTMLAttributes, 0] })
const anchors = [{ docxIndex: 0, blockId: 'source', expectedObjectSha256: 'sha', editable: true }]
const cleanup: (() => void)[] = []
afterEach(() => { cleanup.splice(0).forEach(dispose => dispose()); document.body.replaceChildren() })

function fixture() {
  const root = document.body.appendChild(document.createElement('main'))
  const editor = new Editor({ element: root.appendChild(document.createElement('div')), extensions: [Doc, Paragraph, Text, Link], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', content: [{ type: 'text', text: 'A😀BC' }] }] } })
  editor.commands.setTextSelection({ from: 2, to: 5 })
  const baseline = editor.getJSON(), react = createRoot(root.appendChild(document.createElement('div')))
  const render = (editable = true) => flushSync(() => react.render(<DocxInsertSource editor={editor} editable={editable} anchors={anchors} />))
  render()
  const open = () => flushSync(() => root.querySelector<HTMLButtonElement>('[data-action=insert-link]')!.click())
  const close = () => flushSync(() => react.unmount())
  cleanup.push(() => { close(); editor.destroy() })
  const field = () => document.querySelector<HTMLInputElement>('[aria-label="Link URL"]')!
  const fill = (value: string) => {
    // 原生 setter 同时适用于受控 React 字段和模态框中的原生字段。
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field(), value)
    flushSync(() => field().dispatchEvent(new Event('input', { bubbles: true })))
  }
  const submit = () => flushSync(() => field().closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  return { root, editor, baseline, open, close, render, field, fill, submit }
}

it('Escape closes a source-selected link dialog without changing the document', () => {
  const f = fixture(); f.open()
  expect(document.activeElement).toBe(f.field())
  flushSync(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  expect(document.querySelector('[role=dialog]')).toBeNull()
  expect(f.editor.getJSON()).toEqual(f.baseline)
})

it('keeps an unsafe URL error inline and applies a corrected link to the captured UTF16 selection', () => {
  const f = fixture(); f.open(); f.fill('javascript:alert(1)'); f.submit()
  expect(document.querySelector('[role=alert]')?.textContent).toBeTruthy()
  expect(f.editor.getJSON()).toEqual(f.baseline)
  f.fill('https://example.test/report'); f.submit()
  expect(document.querySelector('[role=dialog]')).toBeNull()
  expect(docxOperations(f.baseline, f.editor.getJSON(), anchors)).toEqual([{ kind: 'setParagraphLink', blockId: 'source', expectedObjectSha256: 'sha', from: 1, to: 4, href: 'https://example.test/report' }])
})

it('disables an already open link when the host becomes readonly and preserves entered text', () => {
  const f = fixture(); f.open(); f.fill('https://example.test/report'); f.render(false)
  expect(f.field().value).toBe('https://example.test/report')
  expect(document.querySelector<HTMLButtonElement>('[data-command=applyLink]')!.disabled).toBe(true)
  f.submit()
  expect(f.editor.getJSON()).toEqual(f.baseline)
  expect(document.querySelector('[role=dialog]')).not.toBeNull()
})

it('rejects stale source text and removes the modal on source component unmount', () => {
  const f = fixture(); f.open(); f.fill('https://example.test/report')
  f.editor.commands.insertContent('changed')
  const changed = f.editor.getJSON(); f.submit()
  expect(document.querySelector('[role=alert]')?.textContent).toContain('选区已改变')
  expect(f.editor.getJSON()).toEqual(changed)
  f.close(); expect(document.querySelector('[role=dialog]')).toBeNull()
})

it('reveals a keyboard-readable URL error without losing the draft or taking focus from the input', () => {
  const f = fixture(); f.open(); f.fill('javascript:alert(1)')
  const error = document.querySelector<HTMLElement>('[role=alert]')!
  const reveal = vi.fn(); error.scrollIntoView = reveal
  f.field().focus(); f.submit()
  expect(error.textContent).toBeTruthy()
  expect(error.getAttribute('aria-label')).toBe('超链接错误')
  expect(error.tabIndex).toBe(0)
  expect(reveal).toHaveBeenCalledWith({ block: 'nearest' })
  expect(document.activeElement).toBe(f.field())
  expect(f.field().value).toBe('javascript:alert(1)')
  expect(f.editor.getJSON()).toEqual(f.baseline)
  f.fill('https://example.test/corrected'); f.submit()
  expect(document.querySelector('[role=dialog]')).toBeNull()
  expect(docxOperations(f.baseline, f.editor.getJSON(), anchors)).toEqual([{ kind: 'setParagraphLink', blockId: 'source', expectedObjectSha256: 'sha', from: 1, to: 4, href: 'https://example.test/corrected' }])
})
