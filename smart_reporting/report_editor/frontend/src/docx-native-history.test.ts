import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { undo, redo, undoDepth } from '@tiptap/pm/history'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { mountHfEditor } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-editor'
import { NativeDocxHistory, commitDocxNativeOperations, docxNativeOperationsOf, seedDocxNativeOperations } from './docx-native-history'

const editors: Editor[] = []
afterEach(() => editors.splice(0).forEach(editor => editor.destroy()))
const header = { kind: 'setHeaderFooter', sectionId: 's0', text: '页眉', pageNumber: false }
const link = { kind: 'setHeaderFooterLink', sectionId: 's1', linked: true }
const layout = { kind: 'setSectionLayout', sectionId: 's0', values: { columns: 2, pageNumberStart: 3, titlePg: true } }
function setup() {
  let locked = false
  const Guard = Extension.create({ name: 'historyTestLock', addProseMirrorPlugins: () => [new Plugin({ filterTransaction: tr => !tr.docChanged || !locked })] })
  const editor = new Editor({ extensions: [...editorExtensions, NativeDocxHistory, Guard], editorProps: { handleScrollToSelection: () => true }, content: { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '正文' }] }] } })
  editors.push(editor)
  return { editor, lock: (value: boolean) => { locked = value; editor.setEditable(!value) } }
}
const intents = (editor: Editor) => docxNativeOperationsOf(editor.getJSON())
const step = (editor: Editor, command: typeof undo) => command(editor.state, editor.view.dispatch)

it('undoes and redoes header content, links, fields and layout in body edit order', () => {
  const { editor } = setup()
  editor.commands.insertContent('甲')
  expect(commitDocxNativeOperations(editor, [header])).toBe(true)
  editor.commands.insertContent('乙')
  expect(commitDocxNativeOperations(editor, [header, link])).toBe(true)
  const numbered = { ...header, text: '页码', pageNumber: true }
  expect(commitDocxNativeOperations(editor, [numbered, link, layout])).toBe(true)
  expect(undoDepth(editor.state)).toBe(5)
  step(editor, undo); expect(intents(editor)).toEqual([header, link])
  step(editor, undo); expect(intents(editor)).toEqual([header])
  step(editor, undo); expect(editor.getText()).toBe('甲正文')
  step(editor, undo); expect(intents(editor)).toEqual([])
  step(editor, undo); expect(editor.getText()).toBe('正文')
  for (let i = 0; i < 5; i++) expect(step(editor, redo)).toBe(true)
  expect(editor.getText()).toBe('甲乙正文')
  expect(intents(editor)).toEqual([numbered, link, layout])
})

it('restores a draft as the initial history baseline, and ignores body operation snapshots', () => {
  const { editor } = setup()
  seedDocxNativeOperations(editor, [header, { kind: 'replaceText', text: '恢复正文' }])
  expect(intents(editor)).toEqual([header])
  expect(undoDepth(editor.state)).toBe(0)
  commitDocxNativeOperations(editor, [header, layout])
  step(editor, undo)
  expect(intents(editor)).toEqual([header])
  expect(step(editor, undo)).toBe(false)
})

it('does not create duplicate history entries and keeps operation values detached', () => {
  const { editor } = setup()
  const operation = { ...layout, values: { columns: 2 } }
  expect(commitDocxNativeOperations(editor, [operation])).toBe(true)
  operation.values.columns = 3
  expect(intents(editor)).toEqual([layout].map(op => ({ ...op, values: { columns: 2 } })))
  expect(commitDocxNativeOperations(editor, intents(editor))).toBe(false)
  expect(undoDepth(editor.state)).toBe(1)
})

it('blocks committing and history mutation during readonly/saving locks', () => {
  const { editor, lock } = setup()
  commitDocxNativeOperations(editor, [header])
  lock(true)
  expect(commitDocxNativeOperations(editor, [header, layout])).toBe(false)
  step(editor, undo)
  expect(intents(editor)).toEqual([header])
  lock(false)
  step(editor, undo)
  expect(intents(editor)).toEqual([])
})

it('leaves nested header input history independent until its value is committed', () => {
  const { editor: body } = setup()
  const host = document.createElement('div')
  document.body.append(host)
  const nested = mountHfEditor(host, { value: { text: '页眉' }, pageNo: '1', pageTotal: '1', spellcheck: false,
    onCommit: value => { commitDocxNativeOperations(body, [{ ...header, ...value }]) }, onExit: () => {} })
  try {
    nested.editor.commands.insertContent('输入')
    step(nested.editor, undo)
    expect(nested.editor.getText()).toBe('页眉')
    expect(nested.changed()).toBeNull()
    expect(undoDepth(body.state)).toBe(0)
    step(nested.editor, redo)
    nested.exit()
    expect(intents(body)[0]!.text).toContain('输入')
    step(body, undo)
    expect(intents(body)).toEqual([])
  } finally { nested.discard(); host.remove() }
})
it('keeps document theme and protection in the same undoable and restorable journal',()=>{
 const {editor}=setup(),theme={kind:'setDocumentTheme',expectedThemeSha256:'a'.repeat(64),fontPreset:'ribbonThemeFontArial'},protection={kind:'setDocumentProtection',expectedSettingsSha256:'b'.repeat(64),protection:null}
 expect(commitDocxNativeOperations(editor,[theme])).toBe(true);expect(intents(editor)).toEqual([theme]);expect(commitDocxNativeOperations(editor,[theme,protection])).toBe(true);step(editor,undo);expect(intents(editor)).toEqual([theme]);step(editor,redo);expect(intents(editor)).toEqual([theme,protection]);seedDocxNativeOperations(editor,[theme,protection]);expect(intents(editor)).toEqual([theme,protection])
})
it('restores non-body revision decisions as document history without changing body content',()=>{
 const {editor}=setup(),before=editor.state.doc.content.toJSON(),story={kind:'resolveStoryRevision',targetId:'story',expectedPartSha256:'a'.repeat(64),expectedWrapperSha256:'b'.repeat(64),action:'reject'}
 expect(commitDocxNativeOperations(editor,[story])).toBe(true);expect(intents(editor)).toEqual([story]);expect(editor.state.doc.content.toJSON()).toEqual(before);step(editor,undo);expect(intents(editor)).toEqual([]);step(editor,redo);expect(intents(editor)).toEqual([story])
})
