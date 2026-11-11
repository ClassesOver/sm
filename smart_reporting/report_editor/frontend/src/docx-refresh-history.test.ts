import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { closeHistory, redo, redoDepth, undo, undoDepth } from '@tiptap/pm/history'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeDocxHistory, commitDocxNativeOperations, seedDocxNativeOperations } from './docx-native-history'
import { resetDocxHistory } from './docx-refresh-history'

const editors: Editor[] = []
afterEach(() => editors.splice(0).forEach(editor => editor.destroy()))
const intentNames = ['nativeBookmarkOperations', 'nativeCrossReferenceOperations', 'nativeCaptionOperation', 'nativeCommentTextOperations', 'nativeCommentCreationOperations', 'nativeCommentReplyOperations', 'nativeCommentThreadOperations']
const header = { kind: 'setHeaderFooter', sectionId: 's0', text: '新页眉', pageNumber: false }
const layout = { kind: 'setSectionLayout', sectionId: 's0', values: { columns: 2, pageNumberStart: 7 } }
const content = (text: string) => ({ type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text }] }] })
function setup(withHistory = true) {
  const key = new PluginKey<{ count: number }>('refreshRetainedState')
  const marker = new Plugin({ key, state: { init: () => ({ count: 0 }), apply: (tr, value) => tr.getMeta(key) ? { count: value.count + 1 } : value } })
  const Intents = Extension.create({ name: 'refreshHistoryIntents', addGlobalAttributes: () => [{ types: ['doc'], attributes: Object.fromEntries(intentNames.map(name => [name, { default: null, rendered: false }])) }], addProseMirrorPlugins: () => [marker] })
  const editor = new Editor({ extensions: [...editorExtensions.filter(extension => withHistory || extension.name !== 'undoRedo'), NativeDocxHistory, Intents], editorProps: { handleScrollToSelection: () => true }, content: content('旧正文') })
  editors.push(editor)
  return { editor, marker, key }
}
function install(editor: Editor, text = '新正文') {
  editor.chain().setMeta('addToHistory', false).setContent(content(text), { emitUpdate: false }).run()
  let tr = editor.state.tr.setMeta('addToHistory', false)
  for (const name of intentNames) tr = tr.setDocAttribute(name, [{ intent: name, revision: 'new' }])
  editor.view.dispatch(tr)
  seedDocxNativeOperations(editor, [header, layout])
  return resetDocxHistory(editor)
}
const step = (editor: Editor, command: typeof undo) => command(editor.state, editor.view.dispatch)

it('establishes the refreshed body and all root intents as an undo baseline in the same Editor', () => {
  const { editor } = setup()
  editor.commands.insertContent('旧输入')
  commitDocxNativeOperations(editor, [{ ...header, text: '旧页眉' }])
  for (const name of intentNames) editor.view.dispatch(closeHistory(editor.state.tr).setDocAttribute(name, [{ intent: name, revision: 'old' }]))
  expect(undoDepth(editor.state)).toBeGreaterThan(1)
  install(editor)
  const baseline = editor.getJSON()
  expect(editor.getText()).toBe('新正文')
  expect(baseline.attrs?.nativeDocxOperations).toEqual([header, layout])
  for (const name of intentNames) expect(baseline.attrs?.[name]).toEqual([{ intent: name, revision: 'new' }])
  expect(undoDepth(editor.state)).toBe(0)
  expect(redoDepth(editor.state)).toBe(0)
  expect(step(editor, undo)).toBe(false)
  expect(step(editor, redo)).toBe(false)
  expect(editor.getJSON()).toEqual(baseline)
  editor.commands.setTextSelection(1)
  editor.commands.insertContent('新输入')
  expect(step(editor, undo)).toBe(true)
  expect(editor.getJSON()).toEqual(baseline)
  expect(step(editor, redo)).toBe(true)
  expect(editor.getText()).toBe('新输入新正文')
  commitDocxNativeOperations(editor, [header])
  expect(step(editor, undo)).toBe(true)
  expect(editor.getJSON().attrs?.nativeDocxOperations).toEqual([header, layout])
  for (const name of intentNames) {
    editor.view.dispatch(closeHistory(editor.state.tr).setDocAttribute(name, [{ intent: name, revision: 'manual' }]))
    const changed = editor.getJSON()
    expect(step(editor, undo)).toBe(true)
    expect(editor.getJSON().attrs?.[name]).toEqual([{ intent: name, revision: 'new' }])
    expect(step(editor, redo)).toBe(true)
    expect(editor.getJSON()).toEqual(changed)
    expect(step(editor, undo)).toBe(true)
  }
})

it('clears a redo-only branch so redo cannot resurrect pre-refresh body or layout', () => {
  const { editor } = setup()
  editor.commands.insertContent('过期输入')
  commitDocxNativeOperations(editor, [layout])
  expect(step(editor, undo)).toBe(true)
  expect(step(editor, undo)).toBe(true)
  expect(undoDepth(editor.state)).toBe(0)
  expect(redoDepth(editor.state)).toBe(2)
  install(editor)
  const baseline = editor.getJSON()
  expect(redoDepth(editor.state)).toBe(0)
  expect(step(editor, redo)).toBe(false)
  expect(editor.getJSON()).toEqual(baseline)
})

it('preserves document, selection, stored marks, plugin instances and other plugin state', () => {
  const { editor, marker, key } = setup()
  editor.commands.insertContent('历史')
  editor.commands.setTextSelection({ from: 2, to: 4 })
  editor.view.dispatch(editor.state.tr.setMeta(key, true).setStoredMarks([editor.schema.marks.bold.create()]))
  const before = editor.state, markerState = marker.getState(before)
  expect(resetDocxHistory(editor)).toBe(true)
  expect(editor.state.doc).toBe(before.doc)
  expect(editor.state.selection).toBe(before.selection)
  expect(editor.state.storedMarks).toBe(before.storedMarks)
  expect(editor.state.plugins).toEqual(before.plugins)
  editor.state.plugins.forEach((plugin, i) => expect(plugin).toBe(before.plugins[i]))
  expect(marker.getState(editor.state)).toBe(markerState)
  expect(markerState).toEqual({ count: 1 })
})

it('does not reconfigure a first refresh with empty history', () => {
  const { editor } = setup()
  const before = editor.state
  expect(resetDocxHistory(editor)).toBe(false)
  expect(editor.state).toBe(before)
  expect(install(editor)).toBe(false)
  expect(editor.getText()).toBe('新正文')
})

it('does not replace state when history is disabled or the editor is destroyed', () => {
  const { editor } = setup(false)
  editor.commands.insertContent('无历史')
  const before = editor.state
  expect(resetDocxHistory(editor)).toBe(false)
  expect(editor.state).toBe(before)
  editor.destroy()
  expect(resetDocxHistory(editor)).toBe(false)
})
