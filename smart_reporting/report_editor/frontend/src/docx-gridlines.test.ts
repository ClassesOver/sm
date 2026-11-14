import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { undoDepth, redoDepth } from '@tiptap/pm/history'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxOutlineView } from './docx-outline-view'
import { NativeDraft } from './native-draft'
import { createDocxGridlines, createDocxTableGridlines } from './docx-gridlines'

const cleanups: Array<() => void> = []
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); document.body.replaceChildren() })
function setup(initialClass = '') {
  const host = document.body.appendChild(document.createElement('div')); host.className = 'docx-native'
  const root = host.appendChild(document.createElement('div')); root.className = initialClass
  let locked = false, updates = 0, transactions = 0
  const memory = new Map<string, string>(), visibility: boolean[] = []
  const draft = new NativeDraft({ documentId: 'gridlines', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' } }, { getItem: key => memory.get(key) ?? null, setItem: (key, value) => { memory.set(key, value) }, removeItem: key => { memory.delete(key) } })
  const Guard = Extension.create({ name: 'gridlineTestGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction: tr => !tr.docChanged || !locked })] })
  const editor = new Editor({ element: root.appendChild(document.createElement('div')), extensions: [...editorExtensions, Guard], editorProps: { attributes: { class: 'doc-page' }, handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docHeading', attrs: { level: 1 }, content: [{ type: 'text', text: '标题' }] },
    { type: 'docParagraph', content: [{ type: 'text', text: '保留正文' }] },
  ] } })
  const baseline = editor.getJSON()
  editor.on('transaction', () => { transactions++ })
  editor.on('update', () => { updates++; draft.setOperations(JSON.stringify(editor.getJSON()) === JSON.stringify(baseline) ? [] : [{ kind: 'replaceText', text: editor.getText() }]) })
  const grid = createDocxGridlines({ editor, root, onVisibilityChange: visible => visibility.push(visible) })
  const outline = createDocxOutlineView({ editor, root })
  cleanups.push(() => { grid.dispose(); outline.dispose(); editor.destroy() })
  return { root, editor, grid, outline, draft, memory, visibility, baseline, updates: () => updates, transactions: () => transactions, lock() { locked = true; editor.setEditable(false, false) } }
}

it('toggles only the source screen grid class without document, transactions, draft or storage changes', () => {
  const f = setup(), doc = f.editor.getJSON(), html = f.editor.getHTML()
  expect(f.grid.visible).toBe(false); expect(f.grid.reason()).toBeNull()
  f.grid.toggle(); expect(f.grid.visible).toBe(true); expect(f.root.classList.contains('show-grid')).toBe(true)
  f.grid.refresh(); expect(f.grid.visible).toBe(true)
  f.grid.toggle(); expect(f.grid.visible).toBe(false); expect(f.root.classList.contains('show-grid')).toBe(false)
  expect(f.editor.getJSON()).toEqual(doc); expect(f.editor.getHTML()).toBe(html)
  expect(f.updates()).toBe(0); expect(f.transactions()).toBe(0); expect(f.draft.operations).toEqual([]); expect([...f.memory]).toEqual([])
  expect(f.visibility).toEqual([true, false]); expect(undoDepth(f.editor.state)).toBe(0); expect(redoDepth(f.editor.state)).toBe(0)
})

it('toggles the source table-only screen grid independently of the page alignment grid', () => {
  const f = setup(), pageGrid = f.grid, tableGrid = createDocxTableGridlines({ editor: f.editor, root: f.root, storage: {
    getItem: key => f.memory.get(key) ?? null,
    setItem: (key, value) => { f.memory.set(key, value) },
  } })
  const doc = f.editor.getJSON(), html = f.editor.getHTML()
  expect(tableGrid.visible).toBe(false)
  expect(tableGrid.reason()).toBeNull()
  tableGrid.toggle()
  expect(tableGrid.visible).toBe(true)
  expect(f.root.classList.contains('show-table-gridlines')).toBe(true)
  expect(pageGrid.visible).toBe(false)
  tableGrid.toggle()
  expect(f.root.classList.contains('show-table-gridlines')).toBe(false)
  expect(f.editor.getJSON()).toEqual(doc)
  expect(f.editor.getHTML()).toBe(html)
  expect(f.updates()).toBe(0)
  expect(f.transactions()).toBe(0)
  expect(f.draft.operations).toEqual([])
  tableGrid.dispose()
})

it('restores and persists the table gridline view preference without changing the document', () => {
  const f = setup(), storage = new Map<string, string>([['aidocs.tableGridlines', 'true']])
  const preference = { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => { storage.set(key, value) } }
  const firstRoot = document.createElement('div')
  const first = createDocxTableGridlines({ editor: f.editor, root: firstRoot, storage: preference })
  const doc = f.editor.getJSON(), html = f.editor.getHTML()
  expect(first.visible).toBe(true)
  expect(firstRoot.classList.contains('show-table-gridlines')).toBe(true)
  first.toggle()
  expect(storage.get('aidocs.tableGridlines')).toBe('false')
  first.dispose()
  const nextRoot = document.createElement('div')
  const reloaded = createDocxTableGridlines({ editor: f.editor, root: nextRoot, storage: preference })
  expect(reloaded.visible).toBe(false)
  expect(nextRoot.classList.contains('show-table-gridlines')).toBe(false)
  expect(f.editor.getJSON()).toEqual(doc)
  expect(f.editor.getHTML()).toBe(html)
  expect(f.transactions()).toBe(0)
  expect(f.updates()).toBe(0)
  reloaded.dispose()
})

it('keeps the table gridline view usable when preference storage is unavailable', () => {
  const f = setup(), root = document.createElement('div')
  const grid = createDocxTableGridlines({ editor: f.editor, root, storage: {
    getItem: () => { throw new Error('storage unavailable') },
    setItem: () => { throw new Error('storage unavailable') },
  } })
  expect(grid.visible).toBe(false)
  grid.toggle()
  expect(grid.visible).toBe(true)
  expect(root.classList.contains('show-table-gridlines')).toBe(true)
  grid.dispose()
})

it('keeps existing draft and real UndoRedo history independent of display switching', () => {
  const f = setup(); f.editor.commands.insertContent('修改')
  const changed = f.editor.getJSON(), operations = f.draft.operations, storage = [...f.memory], updates = f.updates(), transactions = f.transactions()
  const undo = undoDepth(f.editor.state), redo = redoDepth(f.editor.state)
  f.grid.toggle(); f.grid.refresh(); f.grid.toggle()
  expect(f.editor.getJSON()).toEqual(changed); expect(f.draft.operations).toEqual(operations); expect([...f.memory]).toEqual(storage)
  expect(f.updates()).toBe(updates); expect(f.transactions()).toBe(transactions); expect(undoDepth(f.editor.state)).toBe(undo); expect(redoDepth(f.editor.state)).toBe(redo)
  f.editor.commands.undo(); expect(f.editor.getJSON()).toEqual(f.baseline); expect(f.draft.operations).toEqual([])
  f.grid.toggle(); f.editor.commands.redo(); expect(f.editor.getJSON()).toEqual(changed); expect(f.grid.visible).toBe(true)
})

it('allows screen grids under read-only or saving guards and preserves the switch across outline views', () => {
  const f = setup(); f.lock(); const doc = f.editor.getJSON(), updates = f.updates(), storage = [...f.memory]
  expect(f.grid.reason()).toBeNull(); f.grid.toggle(); f.outline.run('大纲')
  expect(f.grid.visible).toBe(true); expect(f.root.classList.contains('show-grid')).toBe(true)
  f.editor.commands.insertContent('禁止写入'); expect(f.editor.getJSON()).toEqual(doc)
  f.outline.run('页面视图'); f.grid.refresh(); expect(f.grid.visible).toBe(true); expect(f.root.classList.contains('view-outline')).toBe(false)
  expect(f.updates()).toBe(updates); expect([...f.memory]).toEqual(storage); expect(f.draft.operations).toEqual([])
})

it('restores the original class on disposal and rejects actions after disposal or editor destruction', () => {
  const f = setup('kept show-grid')
  expect(f.grid.visible).toBe(false); expect(f.root.className).toBe('kept')
  f.grid.toggle(); f.root.classList.remove('show-grid'); f.grid.refresh(); expect(f.root.classList.contains('show-grid')).toBe(true)
  f.grid.toggle(); f.grid.dispose(); f.grid.dispose(); expect(f.root.className).toBe('kept show-grid')
  expect(f.grid.reason()).not.toBeNull(); f.grid.toggle(); f.grid.refresh(); expect(f.root.className).toBe('kept show-grid')
  const destroyed = setup(); destroyed.editor.destroy(); expect(destroyed.grid.reason()).not.toBeNull(); destroyed.grid.toggle(); expect(destroyed.root.classList.contains('show-grid')).toBe(false)
})
