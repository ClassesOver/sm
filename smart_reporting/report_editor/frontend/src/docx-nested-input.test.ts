import { Plugin } from '@tiptap/pm/state'
import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { DocNestedTable, editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function setup(allowed = true, paragraphs = ['same'], reject = false) {
  const host = document.createElement('div'); document.body.append(host)
  const errors: string[] = []
  const nested = DocNestedTable.configure({ canEditCell: () => allowed, onCommitError: reason => errors.push(reason) })
  const Guard = Extension.create({ name: 'rejectNestedTest', addProseMirrorPlugins: () => [new Plugin({ filterTransaction: transaction => !reject || !transaction.docChanged })] })
  const model = { colWidthsPct: [100], rows: [[{ paras: paragraphs }]] }
  const editor = new Editor({ element: host, extensions: [...editorExtensions.map(extension => extension.name === 'docNestedTable' ? nested : extension), Guard], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docTable', attrs: { docxIndex: 0, colWidthsPct: [100] }, content: [{ type: 'docTableRow', content: [{ type: 'docTableCell', content: [{ type: 'docParagraph' }, { type: 'docNestedTable', attrs: { model } }, { type: 'docParagraph' }] }] }] }] } })
  editors.push(editor)
  const td = host.querySelector<HTMLElement>('.doc-nested-table td')!
  const current = () => { let value: any; editor.state.doc.descendants(node => { if (node.type.name === 'docNestedTable') value = node.attrs.model }); return value }
  return { editor, td, current, errors }
}
it('keeps unsigned nested input read-only and refuses its dirty DOM commit', () => {
  const { td, current } = setup(false)
  expect(td.getAttribute('contenteditable')).toBe('false')
  td.innerHTML = '<div>forged</div>'; td.dispatchEvent(new Event('input', { bubbles: true }))
  window.dispatchEvent(new Event('ai-docs-commit-tables'))
  expect(current().rows[0][0].paras).toEqual(['same'])
})
it('flushes a focused nested input and preserves paragraph-array boundaries', () => {
  const { td, current } = setup(true, ['a\nb'])
  td.innerHTML = '<div>a</div><div>b</div><div></div>'; td.dispatchEvent(new Event('input', { bubbles: true }))
  window.dispatchEvent(new Event('ai-docs-commit-tables'))
  expect(current().rows[0][0].paras).toEqual(['a', 'b', ''])
})
it('disables the island on save-lock transactions and ignores pending DOM changes', () => {
  const { editor, td, current } = setup()
  td.innerHTML = '<div>unsaved</div>'; td.dispatchEvent(new Event('input', { bubbles: true }))
  editor.setEditable(false, false); editor.commands.setMeta('native-section-layout', true)
  expect(td.getAttribute('contenteditable')).toBe('false')
  window.dispatchEvent(new Event('ai-docs-commit-tables'))
  expect(current().rows[0][0].paras).toEqual(['same'])
})
it('retains invalid dirty input for correction and reports it instead of committing old text', () => {
  let reason = ''
  const host = document.createElement('div'); document.body.append(host)
  const nested = DocNestedTable.configure({ canEditCell: () => true, validateParagraphs: paragraphs => paragraphs.some(text => text.includes('\t')) ? 'unsupported tab' : null, onCommitError: value => { reason = value } })
  const editor = new Editor({ element: host, extensions: editorExtensions.map(extension => extension.name === 'docNestedTable' ? nested : extension), editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docTable', content: [{ type: 'docTableRow', content: [{ type: 'docTableCell', content: [{ type: 'docParagraph' }, { type: 'docNestedTable', attrs: { model: { colWidthsPct: [100], rows: [[{ paras: ['same'] }]] } } }] }] }] }] } })
  editors.push(editor)
  const td = host.querySelector<HTMLElement>('.doc-nested-table td')!
  td.innerHTML = '<div>bad\ttext</div>'; td.dispatchEvent(new Event('input', { bubbles: true }))
  window.dispatchEvent(new Event('ai-docs-commit-tables'))
  expect(reason).toBe('unsupported tab')
  expect(JSON.stringify(editor.getJSON())).toContain('same')
  td.innerHTML = '<div>corrected</div>'
  window.dispatchEvent(new Event('ai-docs-commit-tables'))
  expect(JSON.stringify(editor.getJSON())).toContain('corrected')
})

it('reports a transaction rejected by the operation guard and retains dirty text', () => {
  const { td, current, errors } = setup(true, ['same'], true)
  td.innerHTML='<div>blocked change</div>';td.dispatchEvent(new Event('input',{bubbles:true}))
  window.dispatchEvent(new Event('ai-docs-commit-tables'))
  expect(current().rows[0][0].paras).toEqual(['same'])
  expect(errors[0]).toContain('未能提交')
  window.dispatchEvent(new Event('ai-docs-commit-tables'))
  expect(errors).toHaveLength(2)
})
it('limits Control+A to the active nested cell contents', () => {
  const { td } = setup()
  td.focus()
  const key = new KeyboardEvent('keydown', { key: 'a', ctrlKey: true, bubbles: true, cancelable: true })
  td.dispatchEvent(key)
  expect(key.defaultPrevented).toBe(true)
  expect(window.getSelection()?.toString()).toBe('same')
  expect(td.contains(window.getSelection()?.anchorNode ?? null)).toBe(true)
})
it('restores committed nested text through real ProseMirror undo and redo', () => {
  const { td, editor, current } = setup()
  td.innerHTML='<div>changed</div>';td.dispatchEvent(new Event('input',{bubbles:true}))
  window.dispatchEvent(new Event('ai-docs-commit-tables'))
  expect(current().rows[0][0].paras).toEqual(['changed'])
  expect(editor.commands.undo()).toBe(true)
  expect(current().rows[0][0].paras).toEqual(['same'])
  expect(editor.commands.redo()).toBe(true)
  expect(current().rows[0][0].paras).toEqual(['changed'])
})
