import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { undoDepth } from '@tiptap/pm/history'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { outlineViewKey } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/outline-view'
import { createDocxOutlineView } from './docx-outline-view'

const cleanups: Array<() => void> = []
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); document.body.replaceChildren() })
function setup(initialClass = '') {
  const host = document.body.appendChild(document.createElement('div')); host.className = 'docx-native'
  const root = host.appendChild(document.createElement('div')); root.className = initialClass
  let locked = false, updates = 0
  const Guard = Extension.create({ name: 'outlineTestGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction: tr => !tr.docChanged || !locked })] })
  const editor = new Editor({ element: root.appendChild(document.createElement('div')), extensions: [...editorExtensions, Guard], editorProps: { attributes: { class: 'doc-page native-uniform-columns' }, handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docHeading', attrs: { level: 1 }, content: [{ type: 'text', text: '章节甲' }] },
    { type: 'docParagraph', content: [{ type: 'text', text: '保留正文' }] },
    { type: 'docHeading', attrs: { level: 2 }, content: [{ type: 'text', text: '子标题' }] },
    { type: 'docHeading', attrs: { level: 1 }, content: [{ type: 'text', text: '章节乙' }] },
  ] } })
  editor.on('update', () => { updates++ })
  const errors: unknown[] = [], view = createDocxOutlineView({ editor, root, onError: error => errors.push(error) })
  cleanups.push(() => { view.dispose(); editor.destroy() })
  return { root, editor, view, errors, updates: () => updates, lock() { locked = true; editor.setEditable(false) } }
}
function foldFirst(editor: Editor) {
  const handle = editor.view.dom.querySelector<HTMLElement>('.outline-handle')!
  expect(handle.textContent).toBe('⊖')
  handle.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
}

it('switches and folds the real engine without changing document, update events or undo history', () => {
  const f = setup(), baseline = f.editor.getJSON(), history = undoDepth(f.editor.state)
  expect(f.view.mode).toBe('page'); expect(f.view.reason('大纲')).toBeNull()
  f.view.run('大纲')
  expect(f.view.mode).toBe('outline'); expect(f.root.classList.contains('view-outline')).toBe(true)
  expect(outlineViewKey.getState(f.editor.state)?.active).toBe(true)
  expect(f.editor.view.dom.querySelectorAll('.outline-handle')).toHaveLength(3)
  foldFirst(f.editor)
  expect(outlineViewKey.getState(f.editor.state)?.collapsed.size).toBe(1)
  expect(f.editor.view.dom.querySelector('.outline-collapsed')?.textContent).toBe('子标题')
  expect(f.editor.view.dom.querySelector('.outline-handle')?.textContent).toBe('⊕')
  f.editor.view.dom.querySelector<HTMLElement>('.outline-handle')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
  expect(f.editor.view.dom.querySelectorAll('.outline-collapsed')).toHaveLength(0)
  foldFirst(f.editor)
  expect(f.editor.getJSON()).toEqual(baseline); expect(undoDepth(f.editor.state)).toBe(history); expect(f.updates()).toBe(0)
  f.view.run('页面视图')
  expect(f.view.mode).toBe('page'); expect(f.root.classList.contains('view-outline')).toBe(false)
  expect(outlineViewKey.getState(f.editor.state)?.collapsed.size).toBe(0)
  expect(f.editor.view.dom.querySelectorAll('.outline-handle,.outline-collapsed')).toHaveLength(0)
  expect(f.editor.getJSON()).toEqual(baseline); expect(f.editor.getText()).toContain('保留正文'); expect(f.updates()).toBe(0)
  f.view.run('大纲'); expect(f.editor.view.dom.querySelectorAll('.outline-handle')).toHaveLength(3)
  expect(f.editor.view.dom.querySelectorAll('.outline-collapsed')).toHaveLength(0)
})

it('allows display changes under read-only/save locks while Guard still rejects body editing', () => {
  const f = setup(), baseline = f.editor.getJSON(); f.lock()
  const updates = f.updates() // Tiptap setEditable 本身会发 update；仅核对视图没有新增。
  expect(f.view.reason('大纲')).toBeNull(); f.view.run('大纲'); foldFirst(f.editor)
  expect(outlineViewKey.getState(f.editor.state)?.collapsed.size).toBe(1)
  f.editor.commands.insertContent('禁止写入')
  expect(f.editor.getJSON()).toEqual(baseline); expect(f.updates()).toBe(updates)
  f.view.run('页面视图'); expect(f.view.mode).toBe('page'); expect(f.errors).toEqual([])
})

it('refreshes from plugin state and disposal clears folds and restores the original host class', () => {
  const f = setup('kept view-outline')
  expect(f.root.classList.contains('view-outline')).toBe(false)
  f.editor.commands.setOutlineViewActive(true); f.view.refresh(); expect(f.view.mode).toBe('outline')
  foldFirst(f.editor); f.view.dispose(); f.view.dispose()
  expect(f.root.className).toBe('kept view-outline')
  expect(outlineViewKey.getState(f.editor.state)?.active).toBe(false)
  expect(outlineViewKey.getState(f.editor.state)?.collapsed.size).toBe(0)
  expect(f.view.reason('大纲')).not.toBeNull(); f.view.run('大纲')
  expect(outlineViewKey.getState(f.editor.state)?.active).toBe(false)
})
