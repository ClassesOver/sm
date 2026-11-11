import { afterEach, expect, it, vi } from 'vitest'
import { flushSync } from 'react-dom'
import {undoDepth, redoDepth} from '@tiptap/pm/history'
import {Plugin} from '@tiptap/pm/state'
import type { Editor } from '@tiptap/core'
import { createDocxEditorView } from './docx-main'
import { createEditorShell } from './shell'
import { NativeDraft, type NativeDraftIdentity } from './native-draft'
import type { NativeContextResponse } from './native-api'
import { bindNativeSession } from './native-session'
import { bytesSha256 } from './source-validation'
import type { DocxHeaderFooterController } from './docx-hf-source'
import * as columnLayout from './docx-mixed-columns'
import * as navigationModule from './docx-navigation'
import * as paginationMeasurement from './docx-measure-current-pagination'

const fixture = vi.hoisted(() => ({ legacyHeader: false, comments: [] as { id: string; author: string; text: string }[], noteMarker: false, noteKind: 'footnote', multi: false, sectionCount: 2, inherited: false, settings: { pageWidth: 12240, pageHeight: 15840, orientation: 'portrait',
  marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1, headerDist: 720, footerDist: 720, pageBorder: false },
  sectionXml: '<w:sectPr/>', blockXml: '<w:p><w:r><w:t>原文</w:t></w:r></w:p>' }))
vi.mock('@genoffice/docx-engine', async importOriginal => ({
  ...await importOriginal<typeof import('@genoffice/docx-engine')>(),
  readSectionSettings: () => ({ ...fixture.settings }),
  readSections: () => fixture.multi ? Array.from({ length: fixture.sectionCount }, (_, index) => index).map(index => ({ settings: { ...fixture.settings }, firstBlockIndex: index, lastBlockIndex: index, sectPrXml: index ? '<w:sectPr></w:sectPr>' : fixture.sectionXml, headerRefs: index && fixture.inherited ? {} : { default: index ? 'r2' : 'r1' }, footerRefs: {} })) : [{ settings: { ...fixture.settings }, lastBlockIndex: 1, sectPrXml: fixture.sectionXml, headerRefs: {}, footerRefs: {} }],
}))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/parse-off-thread', () => ({ parseDocxOffThread: async () => ({
  headerText: fixture.legacyHeader ? 'parsed header without capability' : undefined,
  blocks: (fixture.multi ? Array.from({ length: fixture.sectionCount }, (_, index) => index) : [0]).map(docxIndex => ({ docxIndex, type: 'paragraph', originalXml: fixture.blockXml })), comments: fixture.comments, hfParts: { r1: { text: 'header 1', paras: [{ runs: [{ text: 'header 1' }] }] }, r2: { text: 'header 2', paras: [{ runs: [{ text: 'header 2' }] }] } }, fontTable: [], styles: [], numbering: new Map(),
}) }))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/editor/convert', () => ({ pmDocOptions: () => ({}),
  blocksToPmDoc: () => ({ type: 'doc', content: (fixture.multi ? Array.from({ length: fixture.sectionCount }, (_, index) => index) : [0]).map(docxIndex => ({ type: 'docParagraph', attrs: { docxIndex }, content: fixture.noteMarker && docxIndex === 0 ? [{ type: 'text', text: '原' }, { type: 'docNoteRef', attrs: { kind: fixture.noteKind, id: '1', num: 1, rawRPr: null } }, { type: 'text', text: '文' }] : [{ type: 'text', text: docxIndex ? '第二节' : '原文' }] })) }),
}))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions', async () => {
  const { Node, Extension } = await import('@tiptap/core')
  const { UndoRedo } = await import('@tiptap/extensions')
  return { DocNestedTable: Node.create({ name: 'docNestedTable', group: 'block', atom: true, renderHTML: () => ['table'] }), DocTableRow: Node.create({ name: 'docTableRow', content: 'block*', renderHTML: () => ['tr', 0] }), editorExtensions: [
    UndoRedo,
    Node.create({ name: 'doc', topNode: true, content: 'block+' }),
    Node.create({ name: 'docParagraph', group: 'block', content: 'inline*', addAttributes: () => ({ docxIndex: { default: 0 } }), renderHTML: () => ['p', 0] }),
    Node.create({ name: 'text', group: 'inline' }),
    Node.create({ name: 'docNoteRef', group: 'inline', inline: true, atom: true, addAttributes: () => ({ kind: { default: 'footnote' }, id: { default: '' }, num: { default: 1 }, rawRPr: { default: null } }), renderHTML: () => ['sup', '1'] }),
    Extension.create({ name: 'listNumbering', addStorage: () => ({}) }), Extension.create({ name: 'tabStops', addStorage: () => ({}) }),
  ] }
})
type PreviewProps = Parameters<typeof import('./vendor/genoffice-docs/apps/docs/src/renderer/components/PaginationPreview').PaginationPreview>[0]
const previewFixture = vi.hoisted(() => ({ props: null as PreviewProps | null }))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/components/PaginationPreview', () => ({ PaginationPreview: (props: PreviewProps) => { previewFixture.props = props; return null } }))
const hfFixture = vi.hoisted(() => ({ controller: null as DocxHeaderFooterController | null }))
// 子编辑器生命周期单独覆盖；此处捕获真实主视图传入的控制器。
vi.mock('./docx-hf-source', () => ({ DocxHeaderFooterSource: ({ controller }: { controller: DocxHeaderFooterController }) => { hfFixture.controller = controller; return null } }))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/doc-style-css', () => ({ docStyleCss: () => '' }))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/embedded-fonts', () => ({ adoptEmbeddedFonts: async () => true }))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/font-resolve', async importOriginal => ({
  ...await importOriginal<typeof import('./vendor/genoffice-docs/apps/docs/src/renderer/font-resolve')>(),
  setResolverFontTable: () => {}, setBrowserFontMetrics: () => {},
}))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/editor/protected-render', () => ({ setStaticAsciiResolver: () => {} }))

// Keep this lightweight main/recovery harness independent of renderer layout
// imports. Search matching/expansion remain real; decoration tests use the real
// extension in docx-find-replace.test.ts.
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/editor/decoration-extensions', async () => {
  const { PluginKey } = await import('@tiptap/pm/state')
  return { searchPluginKey: new PluginKey('recoverySearch') }
})

const views: Awaited<ReturnType<typeof createDocxEditorView>>[] = []
afterEach(() => { fixture.legacyHeader = false; fixture.comments = []; fixture.noteMarker = false; fixture.noteKind = 'footnote'; fixture.multi = false; fixture.sectionCount = 2; fixture.inherited = false; for (const view of views.splice(0)) view.dispose(); document.body.replaceChildren() })
const storage = () => {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
}
async function setup(headersFooters?: Record<string, unknown>, notes?: Record<string, unknown>, comments?: Record<string, unknown>, commentCreation?: Record<string, unknown>, commentReplies?: Record<string, unknown>, commentThreads?: Record<string, unknown>) {
  const bytes = new TextEncoder().encode('来源 Word 固定快照'), sha = await bytesSha256(bytes)
  const hashText = (text: string) => bytesSha256(new TextEncoder().encode(text))
  const identity: NativeDraftIdentity = { documentId: 'word-recovery', revision: 1, sourceSha256: sha,
    scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
  const section = { sectionId: await hashText(`${sha}:section:1`), expectedSectionSha256: await hashText(fixture.sectionXml), settings: { ...fixture.settings }, pageNumberFmt: headersFooters?.pageNumberFmt ?? null, pageNumberStart: headersFooters?.pageNumberStart ?? null, titlePg: headersFooters?.titlePg === true }
  const model = { sourceSha256: sha, sections: [section], blocks: [{ type: 'paragraph', blockId: await hashText(`${sha}:block:0`), expectedObjectSha256: await hashText(fixture.blockXml), editable: true }], ...(headersFooters ? { headersFooters } : {}), ...(notes ? { notes } : {}) }
  if (comments) Object.assign(model, { comments: { ...comments, sourceSha256: sha } })
  if(commentCreation) Object.assign(model,{commentCreation:{...commentCreation,sourceSha256:sha}})
  if(commentReplies) Object.assign(model,{commentReplies:{...commentReplies,sourceSha256:sha}})
  if(commentThreads) Object.assign(model,{commentThreads:{...commentThreads,sourceSha256:sha}})
  const api = { file: vi.fn(async () => bytes.slice().buffer), preview: vi.fn(async () => ({ model })) }
  const context = { context: { ...identity, format: 'docx', sourceFile: { sha256: sha } }, editingEnabled: true } as unknown as NativeContextResponse
  const store = storage(), draft = new NativeDraft(identity, store)
  const open = async (currentDraft = draft, currentContext = context) => {
    const root = document.createElement('main'); document.body.append(root)
    const shell = createEditorShell(root, 'full', 'docx')
    const view = await createDocxEditorView(shell, { api: api as never, context: currentContext, draft: currentDraft })
    views.push(view)
    const editor = (shell.editor.querySelector('.tiptap') as HTMLElement & { editor: Editor }).editor
    const layout = () => shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="layout"]')!.click()
    const select = (action: string) => shell.editor.querySelector<HTMLSelectElement>(`[data-source-action="${action}"]`)!
    return { shell, view, editor, layout, select }
  }
  return { draft, store, identity, context, section, api, open }
}

it('external refresh establishes a new undo baseline and allows new edits afterwards', async () => {
  const f = await setup(), opened = await f.open()
  opened.editor.commands.insertContentAt(2, '旧修改')
  expect(undoDepth(opened.editor.state)).toBeGreaterThan(0)
  f.draft.setOperations([{...f.draft.operations[0],text:'新基线'}])
  await opened.view.refresh()
  expect(opened.editor.getText()).toBe('新基线')
  expect(undoDepth(opened.editor.state)).toBe(0); expect(redoDepth(opened.editor.state)).toBe(0)
  expect(opened.editor.commands.undo()).toBe(false)
  opened.editor.commands.insertContentAt(2, '新编辑')
  expect(opened.editor.commands.undo()).toBe(true); expect(opened.editor.getText()).toBe('新基线')
})

it('external refresh refuses saving locks and malformed replay without clearing old history', async () => {
  const f = await setup(), opened = await f.open()
  opened.editor.commands.insertContentAt(2, '保留')
  const original = opened.editor.state, operations = f.draft.operations, depth = undoDepth(original)
  opened.view.setSaving(true)
  f.draft.setOperations([{...operations[0],text:'保存期间不得安装'}])
  await expect(opened.view.refresh()).rejects.toThrow(/保存|关闭/)
  expect(opened.editor.state.doc.eq(original.doc)).toBe(true); expect(undoDepth(opened.editor.state)).toBe(depth)
  opened.view.setSaving(false)
  f.draft.setOperations([{...operations[0],blockId:'foreign'}])
  await expect(opened.view.refresh()).rejects.toThrow()
  expect(opened.editor.state.doc.eq(original.doc)).toBe(true); expect(undoDepth(opened.editor.state)).toBe(depth)
  f.draft.setOperations(operations)
})

it('external refresh rolls back the original editor state when a plugin rejects installation', async () => {
  const f = await setup(), opened = await f.open()
  opened.editor.commands.insertContentAt(2, '保留')
  opened.editor.registerPlugin(new Plugin({filterTransaction:tr=>!tr.docChanged || !tr.doc.textContent.includes('拒绝刷新')}))
  const original = opened.editor.state, operations = f.draft.operations, depth = undoDepth(original)
  f.draft.setOperations([{...operations[0],text:'拒绝刷新'}])
  await expect(opened.view.refresh()).rejects.toThrow(/安装|刷新/)
  expect(opened.editor.state.doc.eq(original.doc)).toBe(true)
  expect(opened.editor.state.selection.eq(original.selection)).toBe(true)
  expect(undoDepth(opened.editor.state)).toBe(depth)
  f.draft.setOperations(operations)
})
it('external refresh synchronizes navigation after an installed candidate is rolled back', async () => {
  const create = navigationModule.createDocxNavigation
  let refreshNavigation = vi.fn()
  const factory = vi.spyOn(navigationModule, 'createDocxNavigation').mockImplementation(options => {
    const navigation = create(options)
    refreshNavigation = vi.fn(navigation.refresh)
    return {...navigation, refresh: refreshNavigation}
  })
  try {
    const f = await setup(), opened = await f.open()
    opened.editor.commands.insertContentAt(2, '保留')
    const original = opened.editor.state, operations = f.draft.operations
    refreshNavigation.mockClear()
    vi.spyOn(opened.editor, 'setEditable').mockImplementationOnce(() => { throw new Error('安装后失败') })
    f.draft.setOperations([{...operations[0],text:'候选内容'}])
    await expect(opened.view.refresh()).rejects.toThrow('安装后失败')
    expect(opened.editor.state.doc.eq(original.doc)).toBe(true)
    expect(refreshNavigation).toHaveBeenCalledOnce()
    f.draft.setOperations(operations)
  } finally { factory.mockRestore() }
})
const commentManifest = () => ({ sourceId: 'c'.repeat(64), commentReadOnlyReason: null, commentTargets: [{ sourceId: 'c'.repeat(64), targetId: 'd'.repeat(64), expectedCommentsSha256: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64), originalCommentId: '7', ordinal: 0, author: 'Alice', date: null, initials: null, text: 'Original comment', relationshipIds: [], editableText: true, readOnlyReason: null }] })
const openCommentPanel = (opened: Awaited<ReturnType<Awaited<ReturnType<typeof setup>>['open']>>) => {
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="review"]')!.click()
  const command = opened.shell.editor.querySelector<HTMLButtonElement>('[data-action="comment-text-list"]')!
  expect(command.querySelector('svg path')).not.toBeNull(); command.click()
  return opened.shell.editor.querySelector<HTMLTextAreaElement>('[data-comment-text]')!
}
it('main restores a resolved comment thread without accepting mixed body changes', async () => {
  fixture.comments = [{ id: '7', author: 'Alice', text: 'Original comment' }]
  const manifest = commentManifest(), target = manifest.commentTargets[0]!
  const f = await setup(undefined, undefined, manifest, undefined, undefined, {
    sourceId: manifest.sourceId, readOnlyReason: null,
    targets: [{ ...target, parentId: null, done: false, canResolve: true, canDelete: true, threadReadOnlyReason: null }],
  })
  const opened = await f.open()
  openCommentPanel(opened)
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-comment-resolve]')!.click()
  const operation = { kind: 'resolveComment', done: true, sourceId: target.sourceId, targetId: target.targetId, expectedCommentsSha256: target.expectedCommentsSha256, expectedObjectSha256: target.expectedObjectSha256 }
  expect(f.draft.operations).toEqual([operation])
  opened.editor.commands.insertContentAt(2, '不可混入'); expect(opened.editor.getText()).toBe('原文')
  const recovered = new NativeDraft(f.identity, f.store)
  opened.editor.commands.undo(); expect(f.draft.operations).toEqual([])
  opened.editor.commands.redo(); expect(f.draft.operations).toEqual([operation])
  opened.view.dispose(); document.body.replaceChildren()
  const restored = await f.open(recovered)
  openCommentPanel(restored)
  expect(recovered.operations).toEqual([operation])
  expect(restored.shell.editor.querySelector('[data-comment-resolve]')?.textContent).toContain('重新打开')
})
it('main collects unblurred comments into source-bound drafts and restores real history and persisted intent', async () => {
  fixture.comments = [{ id: '7', author: 'Alice', text: 'Original comment' }]
  const f = await setup(undefined, undefined, commentManifest()), opened = await f.open(), input = openCommentPanel(opened)
  input.value = 'Edited comment 😀'; input.dispatchEvent(new Event('input', { bubbles: true }))
  expect(f.draft.operations).toEqual([])
  opened.view.flushPendingEdits()
  expect(f.draft.operations).toEqual([{ kind: 'editCommentText', sourceId: 'c'.repeat(64), targetId: 'd'.repeat(64), expectedCommentsSha256: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64), text: 'Edited comment 😀' }])
  expect(opened.editor.getText()).toBe('原文')
  opened.editor.commands.insertContentAt(2, '不得混合'); expect(opened.editor.getText()).toBe('原文')
  const recovered = new NativeDraft(f.identity, f.store)
  opened.editor.commands.undo(); expect(f.draft.operations).toEqual([]); expect(input.value).toBe('Original comment')
  opened.editor.commands.redo(); expect(input.value).toBe('Edited comment 😀')
  opened.view.setSaving(true); expect(input.disabled).toBe(true)
  opened.view.setSaving(false); expect(input.disabled).toBe(false)
  opened.view.dispose(); document.body.replaceChildren()
  const restored = await f.open(recovered), restoredInput = openCommentPanel(restored)
  expect(restoredInput.value).toBe('Edited comment 😀'); expect(recovered.operations[0]).toMatchObject({ kind: 'editCommentText' })
  restoredInput.value = 'Original comment'; restoredInput.dispatchEvent(new Event('input', { bubbles: true })); restored.view.flushPendingEdits()
  expect(recovered.operations).toEqual([])
})

it('main retains ordinary drafts and makes comments readonly until that separate batch is saved or undone', async () => {
  fixture.comments = [{ id: '7', author: 'Alice', text: 'Original comment' }]
  const f = await setup(undefined, undefined, commentManifest()), opened = await f.open()
  opened.editor.commands.insertContentAt(2, '已有正文草稿')
  const operations = f.draft.operations, input = openCommentPanel(opened)
  expect(input.disabled).toBe(true)
  expect(opened.shell.editor.querySelector('.docx-comment-panel')!.textContent).toContain('请先保存或撤销正文')
  expect(f.draft.operations).toEqual(operations)
  opened.editor.commands.undo(); expect(f.draft.operations).toEqual([]); expect(input.disabled).toBe(false)
})

it('main rejects stale recovered comment identity and locks mismatched parser displays', async () => {
  fixture.comments = [{ id: '7', author: 'Alice', text: 'Original comment' }]
  const f = await setup(undefined, undefined, commentManifest())
  const operations = [{ kind: 'editCommentText', sourceId: 'f'.repeat(64), targetId: 'd'.repeat(64), expectedCommentsSha256: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64), text: 'Stale' }]
  f.draft.setOperations(operations)
  await expect(f.open()).rejects.toThrow('批注文字草稿')
  expect(f.draft.operations).toEqual(operations)
  document.body.replaceChildren()
  fixture.comments = [{ id: '7', author: 'Alice', text: 'Parser mismatch' }]
  const other = await setup(undefined, undefined, commentManifest()), opened = await other.open()
  expect(openCommentPanel(opened).disabled).toBe(true)
})

it('main save session flushes unblurred comment text into the request and keeps published snapshots locked', async () => {
  fixture.comments = [{ id: '7', author: 'Alice', text: 'Original comment' }]
  const f = await setup(undefined, undefined, commentManifest()), opened = await f.open(), input = openCommentPanel(opened)
  input.value = '保存前未失焦的批注'; input.dispatchEvent(new Event('input', { bubbles: true }))
  const result = { documentId: f.identity.documentId, revision: 2, parentRevision: 1, revisionRegistered: true, artifacts: { word: { downloadUrl: 'http://localhost/comment.docx' } }, validation: { ok: false, issues: [{ code: 'review', message: '待复核' }] } }
  const api = { save: vi.fn().mockResolvedValue(result), export: vi.fn().mockResolvedValue(result) }
  const session = bindNativeSession(opened.shell, { draft: f.draft, api, format: 'docx', view: opened.view })
  await session.save('save')
  expect(api.save).toHaveBeenCalledOnce()
  expect(api.save.mock.calls[0][0].operations).toEqual([{ kind: 'editCommentText', sourceId: 'c'.repeat(64), targetId: 'd'.repeat(64), expectedCommentsSha256: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64), text: '保存前未失焦的批注' }])
  expect(f.draft.closed).toBe(true); expect(input.disabled).toBe(true)
  expect(document.querySelector<HTMLAnchorElement>('.native-delivery a')!.href).toBe('http://localhost/comment.docx')
  expect(document.body.textContent).toContain('待复核'); session.dispose()
})

it('main comments without an authorized source remain readonly and recovered edits are retained on rejection', async () => {
  fixture.comments = [{ id: '7', author: 'Alice', text: 'Only parsed' }]
  const f = await setup(), opened = await f.open(), input = openCommentPanel(opened)
  expect(input.disabled).toBe(true)
  expect(opened.shell.editor.querySelector('.docx-comment-panel')!.textContent).toContain('当前来源未提供可编辑的已有批注')
  opened.view.dispose(); document.body.replaceChildren()
  const operations = [{ kind: 'editCommentText', sourceId: 'c'.repeat(64), targetId: 'd'.repeat(64), expectedCommentsSha256: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64), text: 'Unauthorized' }]
  f.draft.setOperations(operations)
  await expect(f.open()).rejects.toThrow('当前来源未提供批注文字编辑能力')
  expect(f.draft.operations).toEqual(operations)
})

it('main comment input reload after undo explicitly discards stale local text and permits a new save', async () => {
  fixture.comments = [{ id: '7', author: 'Alice', text: 'Original comment' }]
  const f = await setup(undefined, undefined, commentManifest()), opened = await f.open(), input = openCommentPanel(opened)
  input.value = 'Applied'; input.dispatchEvent(new Event('input', { bubbles: true })); opened.view.flushPendingEdits()
  input.value = 'Stale local text'; input.dispatchEvent(new Event('input', { bubbles: true }))
  opened.editor.commands.undo(); expect(() => opened.view.flushPendingEdits()).toThrow('来源已经变化')
  expect(input.value).toBe('Stale local text'); expect(f.draft.operations).toEqual([])
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-comment-reload]')!.click()
  expect(input.value).toBe('Original comment')
  input.value = 'Reloaded new edit'; input.dispatchEvent(new Event('input', { bubbles: true }))
  const result = { documentId: f.identity.documentId, revision: 2, parentRevision: 1, revisionRegistered: true, artifacts: {}, validation: { ok: true, issues: [] } }
  const api = { save: vi.fn().mockResolvedValue(result), export: vi.fn().mockResolvedValue(result) }
  const session = bindNativeSession(opened.shell, { draft: f.draft, api, format: 'docx', view: opened.view })
  await session.save('save')
  expect(api.save).toHaveBeenCalledOnce(); expect(api.save.mock.calls[0][0].operations[0]).toMatchObject({ kind: 'editCommentText', text: 'Reloaded new edit' })
  expect(f.draft.closed).toBe(true); session.dispose()
})

it('main wires real Word find/replace to strict source drafts, persistence, undo and save locks', async () => {
  const f = await setup(), opened = await f.open()
  const button = (action: string) => opened.shell.editor.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!
  button('replace').click()
  const panel = opened.shell.editor.querySelector<HTMLElement>('.docx-find-replace')!
  const query = panel.querySelector<HTMLInputElement>('[data-find-query]')!, replacement = panel.querySelector<HTMLInputElement>('[data-find-replacement]')!
  query.value = '原文'; query.dispatchEvent(new Event('input', { bubbles: true }))
  expect(panel.querySelector('[data-find-count]')!.textContent).toBe('1/1')
  expect(f.draft.operations).toEqual([])
  replacement.value = '替换后的😀正文'
  panel.querySelector<HTMLButtonElement>('[data-find-action="replace"]')!.click()
  expect(opened.editor.getText()).toBe('替换后的😀正文')
  expect(f.draft.operations).toEqual([{ kind: 'replaceParagraph', blockId: expect.any(String), expectedObjectSha256: expect.any(String), text: '替换后的😀正文' }])
  expect(panel.querySelector('[data-find-status]')!.textContent).toContain('已替换 1 处')
  const recovered = new NativeDraft(f.identity, f.store)
  expect(recovered.operations).toEqual(f.draft.operations)
  opened.editor.commands.undo(); expect(opened.editor.getText()).toBe('原文'); expect(f.draft.operations).toEqual([])
  opened.editor.commands.redo(); expect(opened.editor.getText()).toBe('替换后的😀正文')
  opened.view.setSaving(true)
  expect(panel.querySelector<HTMLButtonElement>('[data-find-action="replace"]')!.disabled).toBe(true)
  expect(button('find').disabled).toBe(false)
  query.value = '正文'; query.dispatchEvent(new Event('input', { bubbles: true }))
  expect(panel.querySelector('[data-find-count]')!.textContent).toBe('1/1')
  opened.view.setSaving(false)
  document.body.replaceChildren()
  const reopened = await f.open(recovered)
  expect(reopened.editor.getText()).toBe('替换后的😀正文')
  expect(recovered.operations).toEqual(f.draft.operations)
})

it('main keeps section-operation drafts while replacing body text and rejects foreign source before panel creation', async () => {
  const f = await setup()
  const operation = { kind: 'setSectionLayout', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256, values: { columns: 2 } }
  f.draft.setOperations([operation])
  const opened = await f.open()
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-action="replace"]')!.click()
  const panel = opened.shell.editor.querySelector<HTMLElement>('.docx-find-replace')!
  const input = panel.querySelector<HTMLInputElement>('[data-find-query]')!
  input.value = '原文'; input.dispatchEvent(new Event('input', { bubbles: true }))
  panel.querySelector<HTMLInputElement>('[data-find-replacement]')!.value = '新正文'
  panel.querySelector<HTMLButtonElement>('[data-find-action="replace-all"]')!.click()
  expect(f.draft.operations).toContainEqual(operation)
  expect(f.draft.operations).toContainEqual(expect.objectContaining({ kind: 'replaceParagraph', text: '新正文' }))
  const foreign = { ...f.context, context: { ...f.context.context, sourceFile: { ...f.context.context.sourceFile, sha256: 'foreign-sha' } } }
  document.body.replaceChildren()
  await expect(f.open(new NativeDraft(f.identity, storage()), foreign)).rejects.toThrow(/来源文件身份/)
})

const changedValues = { orientation: 'landscape', pageWidth: 15840, pageHeight: 12240, marginLeft: 720, columns: 2, headerDist: 900 }

it('main shares native undo order across body, header content and layout and persists the undone values', async () => {
  const part = { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原页眉', hasPageNumber: false, editable: true }
  const f = await setup({ titlePg: false, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null, parts: { 'header.default': part } })
  const opened = await f.open()
  opened.editor.commands.insertContentAt(2, '甲')
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  controller.onCommit('header', 'default', { text: '新页眉' })
  opened.editor.commands.insertContentAt(2, '乙')
  opened.layout()
  const orientation = opened.select('layout-orientation')
  orientation.value = 'landscape'; orientation.dispatchEvent(new Event('change', { bubbles: true }))
  opened.editor.commands.undo()
  expect(opened.select('layout-orientation').value).toBe('portrait')
  expect(f.draft.operations.some(op => op.kind === 'setSectionLayout')).toBe(false)
  expect(controller.valueOf('header', 'default')?.value.text).toBe('新页眉')
  opened.editor.commands.undo(); expect(opened.editor.getText()).toBe('原甲文')
  opened.editor.commands.undo()
  expect(controller.valueOf('header', 'default')?.value.text).toBe('原页眉')
  expect(f.draft.operations.some(op => op.kind === 'setHeaderFooter')).toBe(false)
  opened.editor.commands.undo(); expect(f.draft.operations).toEqual([])
  for (let i = 0; i < 4; i++) opened.editor.commands.redo()
  expect(opened.select('layout-orientation').value).toBe('landscape')
  expect(controller.valueOf('header', 'default')?.value.text).toBe('新页眉')
  opened.view.setSaving(true); opened.editor.commands.undo()
  expect(opened.select('layout-orientation').value).toBe('landscape')
  opened.view.setSaving(false); opened.editor.commands.undo()
  expect(opened.select('layout-orientation').value).toBe('portrait')
})

it('main native undo treats restored body and layout as the opening baseline', async () => {
  const f = await setup()
  const operation = { kind: 'setSectionLayout', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256, values: { columns: 2 } }
  const { model } = await f.api.preview(), block = model.blocks[0]!
  const body = { kind: 'replaceParagraph', blockId: block.blockId, expectedObjectSha256: block.expectedObjectSha256, text: '恢复正文' }
  f.draft.setOperations([operation, body])
  const recovered = new NativeDraft(f.identity, f.store), opened = await f.open(recovered)
  opened.editor.commands.undo()
  expect(recovered.operations).toEqual([operation, body])
  opened.editor.commands.insertContentAt(2, '后改')
  opened.editor.commands.undo()
  expect(opened.editor.getText()).toBe('恢复正文')
  expect(recovered.operations).toEqual(expect.arrayContaining([operation, body]))
  opened.editor.commands.redo()
  expect(recovered.operations).toContainEqual(operation)
})

it('DOCX recovery restores section controls and canvas then retains layout during later body editing', async () => {
  const f = await setup()
  const operation = { kind: 'setSectionLayout', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256, values: changedValues }
  f.draft.setOperations([operation])
  const recovered = new NativeDraft(f.identity, f.store)
  const opened = await f.open(recovered)
  opened.layout()
  expect(opened.select('layout-orientation').value).toBe('landscape')
  expect(opened.select('layout-columns').value).toBe('2')
  expect(opened.shell.editor.querySelector<HTMLInputElement>('[data-source-action="layout-header-distance"]')!.value).toBe('900')
  expect(opened.editor.view.dom.style.width).toBe('1056px')
  expect(opened.editor.view.dom.style.paddingLeft).toBe('48px')
  opened.editor.commands.insertContentAt(2, '后续修改')
  expect(recovered.operations.find(value => value.kind === 'setSectionLayout')).toEqual(operation)
  expect(recovered.operations.some(value => value.kind === 'replaceParagraph')).toBe(true)
})

it('DOCX recovery reprojects undo and redo section settings without resaving stale layout values', async () => {
  const f = await setup(), opened = await f.open()
  opened.layout()
  const orientation = opened.select('layout-orientation')
  orientation.value = 'landscape'; orientation.dispatchEvent(new Event('change', { bubbles: true }))
  expect(f.draft.operations[0]).toMatchObject({ kind: 'setSectionLayout', values: { orientation: 'landscape' } })
  f.draft.undo(); await opened.view.refresh()
  expect(opened.select('layout-orientation').value).toBe('portrait')
  expect(opened.editor.view.dom.style.width).toBe('816px')
  f.draft.redo(); await opened.view.refresh()
  expect(opened.select('layout-orientation').value).toBe('landscape')
  expect(opened.editor.view.dom.style.width).toBe('1056px')
  f.draft.undo(); await opened.view.refresh()
  opened.editor.commands.insertContentAt(2, '只改正文')
  expect(f.draft.operations.some(value => value.kind === 'setSectionLayout')).toBe(false)
})

it('DOCX recovery rejects a section identity from a different source and preserves its draft', async () => {
  const f = await setup()
  const operations = [{ kind: 'setSectionLayout', sectionId: 'foreign-section', expectedSectionSha256: f.section.expectedSectionSha256, values: changedValues }]
  f.draft.setOperations(operations)
  await expect(f.open()).rejects.toThrow(/节.*身份|页面设置.*来源/)
  expect(f.draft.operations).toEqual(operations)
})

it('DOCX recovery disables section inputs and rejects forced changes during saving or readonly viewing', async () => {
  const f = await setup(), opened = await f.open()
  opened.layout()
  opened.view.setSaving(true)
  expect(opened.select('layout-orientation').disabled).toBe(true)
  expect(opened.shell.editor.querySelector<HTMLInputElement>('[data-source-action="layout-header-distance"]')!.disabled).toBe(true)
  const locked = opened.select('layout-orientation')
  locked.value = 'landscape'; locked.dispatchEvent(new Event('change', { bubbles: true }))
  expect(f.draft.operations).toEqual([])
  opened.view.setSaving(false)
  expect(opened.select('layout-orientation').disabled).toBe(false)
  f.draft.beginSave(); f.draft.saveCompleted({ revision: 2, revisionRegistered: true })
  opened.view.setSaving(false)
  expect(opened.select('layout-orientation').disabled).toBe(true)
  document.body.replaceChildren()
  const readonlyDraft = new NativeDraft(f.identity, storage())
  const readonly = await f.open(readonlyDraft, { ...f.context, editingEnabled: false })
  readonly.layout()
  const orientation = readonly.select('layout-orientation')
  expect(orientation.disabled).toBe(true)
  orientation.value = 'landscape'; orientation.dispatchEvent(new Event('change', { bubbles: true }))
  expect(orientation.value).toBe('portrait')
  expect(readonlyDraft.operations).toEqual([])
})

it.each([
  { expectedSectionSha256: 'foreign-sha' },
  { values: { columns: 4 } },
  { values: { pageWidth: 1000 } },
  { values: { marginLeft: 14000, marginRight: 14000 } },
  { values: { futureSetting: true } },
])('DOCX recovery keeps an unsupported or mismatched section snapshot intact: %j', async patch => {
  const f = await setup()
  const operations = [{ kind: 'setSectionLayout', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256, values: changedValues, ...patch }]
  f.draft.setOperations(operations)
  await expect(f.open().then(() => undefined)).rejects.toThrow(/草稿/)
  expect(f.draft.operations).toEqual(operations)
})

it('DOCX recovery keeps header/footer drafts through body edits when part anchors match', async () => {
  const hfModel = { titlePg: true, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null,
    parts: { 'header.default': { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原页眉', hasPageNumber: false, editable: true } } }
  const f = await setup(hfModel)
  const operation = { kind: 'setHeaderFooter', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256,
    part: 'header', variant: 'default', expectedPartSha256: 'part-sha', text: '恢复页眉', pageNumber: false }
  f.draft.setOperations([operation])
  const recovered = new NativeDraft(f.identity, f.store)
  const opened = await f.open(recovered)
  opened.editor.commands.insertContentAt(2, '后续正文')
  expect(recovered.operations.find(value => value.kind === 'setHeaderFooter')).toEqual(operation)
  expect(recovered.operations.some(value => value.kind === 'replaceParagraph')).toBe(true)
  opened.editor.commands.undo()
  expect(recovered.operations.find(value => value.kind === 'setHeaderFooter')).toEqual(operation)
})

it('DOCX recovery retains header/footer drafts while changing section layout and restoring again', async () => {
  const hfModel = { titlePg: true, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null,
    parts: { 'header.default': { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原页眉', hasPageNumber: false, editable: true } } }
  const f = await setup(hfModel)
  const operation = { kind: 'setHeaderFooter', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256,
    part: 'header', variant: 'default', expectedPartSha256: 'part-sha', text: '保留页眉', pageNumber: false }
  f.draft.setOperations([operation])
  const opened = await f.open()
  opened.layout()
  const orientation = opened.select('layout-orientation')
  orientation.value = 'landscape'; orientation.dispatchEvent(new Event('change', { bubbles: true }))
  expect(f.draft.operations).toContainEqual(operation)
  expect(f.draft.operations).toContainEqual(expect.objectContaining({ kind: 'setSectionLayout', values: expect.objectContaining({ orientation: 'landscape' }) }))
  views.splice(views.indexOf(opened.view), 1)
  opened.view.dispose()
  document.body.replaceChildren()
  const recovered = new NativeDraft(f.identity, f.store)
  const reopened = await f.open(recovered)
  expect(recovered.operations).toContainEqual(operation)
  expect(reopened.editor.view.dom.style.width).toBe('1056px')
})

it('DOCX header/footer controller flushes pending edits, projects drafts and keeps saving or closed views locked', async () => {
  const hfModel = { titlePg: true, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null,
    parts: { 'header.default': { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原页眉', hasPageNumber: false, editable: true } } }
  const f = await setup(hfModel), opened = await f.open()
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  const pending = { flush: vi.fn(() => controller.onCommit('header', 'default', { text: '未失焦页眉' }, { titlePg: false })), setEditable: vi.fn() }
  controller.registerEditor!(pending)
  opened.view.flushPendingEdits()
  expect(pending.flush).toHaveBeenCalledOnce()
  expect(f.draft.operations).toContainEqual(expect.objectContaining({ kind: 'setHeaderFooter', text: '未失焦页眉', titlePg: false }))
  expect(controller.valueOf('header', 'default')?.value.text).toBe('未失焦页眉')
  expect(controller.model.titlePg).toBe(false)
  controller.onCommit('header', 'default', { text: '后续修改' })
  expect(f.draft.operations).toContainEqual(expect.objectContaining({ text: '后续修改', titlePg: false }))
  opened.view.setSaving(true)
  expect(pending.setEditable).toHaveBeenLastCalledWith(false)
  expect(controller.editable).toBe(false)
  controller.onCommit('header', 'default', { text: '锁定期间修改' })
  expect(controller.valueOf('header', 'default')?.value.text).toBe('后续修改')
  opened.view.setSaving(false)
  expect(pending.setEditable).toHaveBeenLastCalledWith(true)
  f.draft.beginSave(); f.draft.saveCompleted({ revision: 2, revisionRegistered: true })
  opened.view.setSaving(false)
  expect(pending.setEditable).toHaveBeenLastCalledWith(false)
  expect(controller.editable).toBe(false)
})

it('DOCX header/footer controller removes a text draft when restored to the source value', async () => {
  const hfModel = { titlePg: true, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null,
    parts: { 'header.default': { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原页眉', hasPageNumber: false, editable: true } } }
  const f = await setup(hfModel), opened = await f.open()
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  controller.onCommit('header', 'default', { text: '临时修改' })
  expect(f.draft.operations).toHaveLength(1)
  controller.onCommit('header', 'default', { text: '原页眉' })
  expect(f.draft.operations).toEqual([])
  expect(controller.valueOf('header', 'default')?.value.text).toBe('原页眉')
})

it('DOCX header/footer text edits retain the latest global flags across parts', async () => {
  const part = { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原文', hasPageNumber: false, editable: true }
  const f = await setup({ titlePg: false, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null,
    parts: { 'header.default': part, 'footer.default': { ...part, rId: 'rId8', expectedPartSha256: 'footer-sha' } } })
  const opened = await f.open()
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  controller.onCommit('header', 'default', { text: '页眉' }, { titlePg: true })
  controller.onCommit('footer', 'default', { text: '页脚' }, { titlePg: false, evenAndOddHeaders: true })
  controller.onCommit('header', 'default', { text: '新页眉' })
  expect(controller.model.titlePg).toBe(false)
  expect(controller.model.evenAndOddHeaders).toBe(true)
  expect(f.draft.operations.at(-1)).toMatchObject({ text: '新页眉', titlePg: false, evenAndOddHeaders: true })
})

it('keeps layout and trailing header first-page flags consistent across both controls and recovery', async () => {
  const part = { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原文', hasPageNumber: false, editable: true }
  const f = await setup({ titlePg: false, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null, parts: { 'header.default': part } })
  const opened = await f.open(); opened.layout()
  const toggle = () => opened.shell.editor.querySelector<HTMLInputElement>('[data-source-action="header-title-page"]')!
  toggle().click()
  expect(f.draft.operations).toContainEqual(expect.objectContaining({ kind: 'setSectionLayout', values: { titlePg: true } }))
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  expect(controller.model.titlePg).toBe(true)
  controller.onCommit('header', 'default', { text: '页眉' }, { titlePg: false })
  expect(controller.model.titlePg).toBe(false)
  f.draft.undo(); await opened.view.refresh()
  expect(controller.model.titlePg).toBe(true)
  expect(f.draft.operations.some(op => op.kind === 'setHeaderFooter')).toBe(false)
  f.draft.redo(); await opened.view.refresh()
  expect(controller.model.titlePg).toBe(false)
  opened.layout(); expect(toggle().checked).toBe(false)
  toggle().click()
  expect(controller.model.titlePg).toBe(true)
  expect(f.draft.operations.find(op => op.kind === 'setHeaderFooter')).toMatchObject({ text: '页眉' })
  expect(f.draft.operations.find(op => op.kind === 'setHeaderFooter')).not.toHaveProperty('titlePg')
  opened.view.dispose(); views.splice(views.indexOf(opened.view), 1); document.body.replaceChildren()
  const recovered = new NativeDraft(f.identity, f.store), reopened = await f.open(recovered); reopened.layout()
  expect(reopened.shell.editor.querySelector<HTMLInputElement>('[data-source-action="header-title-page"]')!.checked).toBe(true)
  expect(recovered.operations.find(op => op.kind === 'setHeaderFooter')).toMatchObject({ text: '页眉' })
})

it('DOCX recovery rejects a header/footer draft with a stale part anchor and preserves it', async () => {
  const f = await setup()
  const operation = { kind: 'setHeaderFooter', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256,
    part: 'header', variant: 'default', expectedPartSha256: 'stale-part', text: '页眉', pageNumber: false }
  f.draft.setOperations([operation])
  await expect(f.open().then(() => undefined)).rejects.toThrow(/页眉页脚/)
  expect(f.draft.operations).toEqual([operation])
})

it('rejects a recovered first-page flag conflict before mounting and preserves the draft', async () => {
  const part = { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原文', hasPageNumber: false, editable: true }
  const f = await setup({ titlePg: false, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null, parts: { 'header.default': part } })
  const operations = [
    { kind: 'setSectionLayout', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256, values: { titlePg: true } },
    { kind: 'setHeaderFooter', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256,
      part: 'header', variant: 'default', expectedPartSha256: 'part-sha', text: '页眉', pageNumber: false, titlePg: false },
  ]
  f.draft.setOperations(operations)
  const recovered = new NativeDraft(f.identity, f.store)
  await expect(f.open(recovered)).rejects.toThrow('草稿同一节的首页不同设置冲突，请恢复一致的草稿后重试')
  expect(recovered.operations).toEqual(operations)
  expect(document.querySelector('.docx-native')).toBeNull()
})

it('keeps document odd-even settings synchronized with header editing, history and recovery', async () => {
  const part = { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原文', hasPageNumber: false, editable: true }
  const f = await setup({ titlePg: false, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null, parts: { 'header.default': part } })
  const opened = await f.open(); opened.layout()
  const checkbox = () => opened.shell.editor.querySelector<HTMLInputElement>('[data-source-action="header-even-odd"]')!
  checkbox().click()
  expect(f.draft.operations).toContainEqual(expect.objectContaining({ kind: 'setSectionLayout', values: { evenAndOddHeaders: true } }))
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  expect(controller.model.evenAndOddHeaders).toBe(true)
  controller.onCommit('header', 'default', { text: '页眉' }, { evenAndOddHeaders: false })
  expect(controller.model.evenAndOddHeaders).toBe(false)
  f.draft.undo(); await opened.view.refresh()
  expect(controller.model.evenAndOddHeaders).toBe(true)
  expect(f.draft.operations.some(operation => operation.kind === 'setHeaderFooter')).toBe(false)
  f.draft.redo(); await opened.view.refresh()
  expect(controller.model.evenAndOddHeaders).toBe(false)
  opened.layout(); expect(checkbox().checked).toBe(false)
  checkbox().click()
  expect(f.draft.operations.find(op => op.kind === 'setHeaderFooter')).not.toHaveProperty('evenAndOddHeaders')
  opened.view.dispose(); views.splice(views.indexOf(opened.view), 1); document.body.replaceChildren()
  const recovered = new NativeDraft(f.identity, f.store), reopened = await f.open(recovered); reopened.layout()
  expect(reopened.shell.editor.querySelector<HTMLInputElement>('[data-source-action="header-even-odd"]')!.checked).toBe(true)
  expect(recovered.operations.find(op => op.kind === 'setHeaderFooter')).toMatchObject({ text: '页眉' })
})

it('rejects recovered conflicting document odd-even settings before mounting', async () => {
  const part = { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原文', hasPageNumber: false, editable: true }
  const f = await setup({ titlePg: false, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null, parts: { 'header.default': part } })
  const operations = [
    { kind: 'setSectionLayout', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256, values: { evenAndOddHeaders: true } },
    { kind: 'setHeaderFooter', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256,
      part: 'header', variant: 'default', expectedPartSha256: 'part-sha', text: '页眉', pageNumber: false, evenAndOddHeaders: false },
  ]
  f.draft.setOperations(operations)
  await expect(f.open(new NativeDraft(f.identity, f.store))).rejects.toThrow(/奇偶页不同设置冲突/)
  expect(f.draft.operations).toEqual(operations)
  expect(document.querySelector('.docx-native')).toBeNull()
})

it('DOCX recovery verifies inspected section identity against the parsed source bytes', async () => {
  const f = await setup()
  f.section.expectedSectionSha256 = 'foreign-section-hash'
  await expect(f.open().then(() => undefined)).rejects.toThrow(/节身份校验失败/)
})


it.each(['pageNumberFmt', 'pageNumberStart'])('rejects recovered conflicting %s before mounting and preserves the draft', async key => {
  const part = { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原文', hasPageNumber: false, editable: true }
  const f = await setup({ titlePg: false, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null, parts: { 'header.default': part } })
  const operations = [
    { kind: 'setSectionLayout', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256, values: { [key]: null } },
    { kind: 'setHeaderFooter', sectionId: f.section.sectionId, expectedSectionSha256: f.section.expectedSectionSha256,
      part: 'header', variant: 'default', expectedPartSha256: 'part-sha', text: '页眉', pageNumber: false, [key]: key === 'pageNumberFmt' ? 'upperRoman' : 0 },
  ]
  f.draft.setOperations(operations)
  const recovered = new NativeDraft(f.identity, f.store)
  await expect(f.open(recovered)).rejects.toThrow(/页码格式设置冲突/)
  expect(recovered.operations).toEqual(operations)
  expect(document.querySelector('.docx-native')).toBeNull()
})


it('synchronizes page numbering between layout and header editing with atomic history and recovery', async () => {
  const part = { rId: 'rId7', expectedPartSha256: 'part-sha', text: '原文', hasPageNumber: false, editable: true }
  const f = await setup({ titlePg: false, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null, parts: { 'header.default': part } })
  const opened = await f.open(); opened.layout()
  const edit = (format: string, start: string) => {
    flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-source-action="page-number-format"]')!.click())
    const select = opened.shell.editor.querySelector<HTMLSelectElement>('[aria-label="页码编号格式"]')!
    select.value = format
    flushSync(() => select.dispatchEvent(new Event('change', { bubbles: true })))
    const input = opened.shell.editor.querySelector<HTMLInputElement>('[aria-label="起始页码"]')!
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, start)
    flushSync(() => input.dispatchEvent(new Event('input', { bubbles: true })))
    flushSync(() => opened.shell.editor.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  }
  edit('upperRoman', '0')
  expect(f.draft.operations).toContainEqual(expect.objectContaining({ kind: 'setSectionLayout', values: { pageNumberFmt: 'upperRoman', pageNumberStart: 0 } }))
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  expect(controller.model).toMatchObject({ pageNumberFmt: 'upperRoman', pageNumberStart: 0 })
  controller.onCommit('header', 'default', { text: '页眉' }, { pageNumberFmt: 'lowerLetter', pageNumberStart: 5 })
  expect(controller.model).toMatchObject({ pageNumberFmt: 'lowerLetter', pageNumberStart: 5 })
  f.draft.undo(); await opened.view.refresh()
  expect(controller.model).toMatchObject({ pageNumberFmt: 'upperRoman', pageNumberStart: 0 })
  expect(f.draft.operations.some(operation => operation.kind === 'setHeaderFooter')).toBe(false)
  f.draft.redo(); await opened.view.refresh()
  expect(controller.model).toMatchObject({ pageNumberFmt: 'lowerLetter', pageNumberStart: 5 })
  opened.layout(); edit('decimal', '')
  expect(f.draft.operations.find(op => op.kind === 'setHeaderFooter')).not.toHaveProperty('pageNumberStart')
  expect(f.draft.operations.find(op => op.kind === 'setHeaderFooter')).not.toHaveProperty('pageNumberFmt')
  opened.view.dispose(); views.splice(views.indexOf(opened.view), 1); document.body.replaceChildren()
  const recovered = new NativeDraft(f.identity, f.store), reopened = await f.open(recovered)
  reopened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  expect(hfFixture.controller!.model).toMatchObject({ pageNumberFmt: null, pageNumberStart: null })
  expect(recovered.operations.find(op => op.kind === 'setHeaderFooter')).toMatchObject({ text: '页眉' })
})


async function setupMultiHf(inherited = false) {
  const part = { rId: 'r2', expectedPartSha256: 'part2', text: 'header 2', hasPageNumber: false, editable: true }
  const f = await setup({ titlePg: false, evenAndOddHeaders: false, pageNumberFmt: null, pageNumberStart: null, parts: { 'header.default': part } })
  fixture.multi = true; fixture.inherited = inherited
  const { model } = await f.api.preview()
  model.sections.length = 0
  for (const index of [0, 1]) {
    const rid = `r${index + 1}`, sectionId = await bytesSha256(new TextEncoder().encode(`${f.identity.sourceSha256}:section:${index}`))
    model.sections.push({ ...f.section, sectionId, expectedSectionSha256: await bytesSha256(new TextEncoder().encode(index ? '<w:sectPr></w:sectPr>' : fixture.sectionXml)),
      ...{ headersFooters: { parts: { 'header.default': { ...part, text: `header ${index + 1}`, rId: rid, expectedPartSha256: `part${index + 1}`, relationshipsSha256: `graph${index + 1}`, ownRelationshipsSha256: `graph${index + 1}`, ownRId: rid, ownPath: `word/header${index + 1}.xml`, ownPartSha256: `part${index + 1}`, ownerSectionId: sectionId, path: `word/header${index + 1}.xml`, linked: index ? false : null } } } } })
  }
  if (inherited) {
    const first = model.sections[0]!, second = model.sections[1]!
    Object.assign(second, { headersFooters: { parts: { 'header.default': { ...(first as unknown as { headersFooters: { parts: Record<string, object> } }).headersFooters.parts['header.default'], ownRId: null, ownPath: null, ownPartSha256: 'empty', linked: true } } } })
  }
  model.blocks.push({ ...model.blocks[0]!, blockId: await bytesSha256(new TextEncoder().encode(`${f.identity.sourceSha256}:block:1`)) })
  return { ...f, model }
}

it('previews parsed headers when the inspection does not grant header editing', async () => {
  fixture.legacyHeader = true
  const f = await setup(), opened = await f.open()
  previewFixture.props = null
  flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="view"]')!.click())
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-action="pagination-preview"]')!.click()
  await vi.waitFor(() => expect(previewFixture.props).not.toBeNull())
  const props = previewFixture.props!
  expect(props.resolveHf!(props.sections, 0, 'header', 'default').value?.text).toBe('parsed header without capability')
  expect(f.draft.operations).toEqual([])
})

it('previews unsaved section page numbering and inherited header edits without changing the draft', async () => {
  const f = await setupMultiHf(), opened = await f.open()
  opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const second = hfFixture.controller!, first = second.forSection!(f.model.sections[0]!.sectionId)
  first.onCommit('header', 'default', { text: 'draft header' })
  second.onLink!('header', 'default', true)
  second.onCommit('header', 'default', { text: 'draft header' }, { pageNumberFmt: 'upperRoman', pageNumberStart: 7, titlePg: true })
  expect(second.model).toMatchObject({ pageNumberFmt: 'upperRoman', pageNumberStart: 7, titlePg: true })
  const operations = structuredClone(f.draft.operations)
  previewFixture.props = null
  flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="view"]')!.click())
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-action="pagination-preview"]')!.click()
  await vi.waitFor(() => expect(previewFixture.props).not.toBeNull())
  const props = previewFixture.props!
  expect(props.sections[1]).toMatchObject({ pageNumberFmt: 'upperRoman', pageNumberStart: 7, titlePg: true })
  expect(props.hf.titlePg).toBe(true)
  expect(props.resolveHf!(props.sections, 1, 'header', 'default')).toMatchObject({ owner: 0, value: { text: 'draft header' } })
  expect(f.draft.operations).toEqual(operations)
})

it('projects link owner/content through one undo/redo and validates recovered owner before mounting', async () => {
  const f = await setupMultiHf(), opened = await f.open()
  opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  expect(controller.sectionLabel).toBe('第 2 节，共 2 节')
  expect(controller.valueOf('header', 'default')?.value.text).toBe('header 2')
  controller.onLink!('header', 'default', true)
  expect(controller.linked!('header', 'default').value).toBe(true)
  expect(controller.valueOf('header', 'default')?.value.text).toBe('header 1')
  expect(f.draft.operations).toHaveLength(1)
  f.draft.undo(); await opened.view.refresh()
  expect(f.draft.operations).toEqual([])
  expect(controller.linked!('header', 'default').value).toBe(false)
  expect(controller.valueOf('header', 'default')?.value.text).toBe('header 2')
  f.draft.redo(); await opened.view.refresh()
  expect(controller.valueOf('header', 'default')?.value.text).toBe('header 1')
  const saved = structuredClone(f.draft.operations)
  opened.view.dispose(); views.splice(views.indexOf(opened.view), 1); document.body.replaceChildren()
  const recovered = new NativeDraft(f.identity, f.store), reopened = await f.open(recovered)
  reopened.editor.commands.setTextSelection(reopened.editor.state.doc.content.size - 1)
  reopened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  expect(hfFixture.controller!.valueOf('header', 'default')?.value.text).toBe('header 1')
  reopened.view.dispose(); views.splice(views.indexOf(reopened.view), 1); document.body.replaceChildren()
  const forged = saved.map(operation => ({ ...operation, expectedOwnerSectionId: 'foreign' }))
  f.draft.setOperations(forged)
  const invalid = new NativeDraft(f.identity, f.store)
  await expect(f.open(invalid)).rejects.toThrow('身份')
  expect(invalid.operations).toEqual(forged)
  expect(document.querySelector('.docx-native')).toBeNull()
})


it('unlinks pending inherited edits in one history step without losing the owner content', async () => {
  const f = await setupMultiHf(true), opened = await f.open()
  opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  expect(controller.linked!('header', 'default').value).toBe(true)
  controller.onLink!('header', 'default', false, { text: 'pending inherited text', paras: [{ runs: [{ text: 'pending inherited text' }] }] })
  expect(f.draft.operations).toHaveLength(3)
  expect(f.draft.operations.find(operation => operation.kind === 'setHeaderFooter' && !operation.afterLink)).toMatchObject({ sectionId: f.model.sections[0]!.sectionId, text: 'pending inherited text' })
  expect(controller.valueOf('header', 'default')?.value.text).toBe('pending inherited text')
  f.draft.undo(); await opened.view.refresh()
  expect(f.draft.operations).toEqual([])
  expect(controller.linked!('header', 'default').value).toBe(true)
  expect(controller.valueOf('header', 'default')?.value.text).toBe('header 1')
  f.draft.redo(); await opened.view.refresh()
  expect(controller.valueOf('header', 'default')?.value.text).toBe('pending inherited text')
})

it('edits a newly unlinked owner before saving and restores its content across history and recovery', async () => {
  const f = await setupMultiHf(true), opened = await f.open()
  opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  controller.onLink!('header', 'default', false)
  expect(controller.valueOf('header', 'default')?.anchor.editable).toBe(true)
  controller.onCommit('header', 'default', { text: 'edited before saving link' })
  expect(f.draft.operations).toContainEqual(expect.objectContaining({ kind: 'setHeaderFooter', sectionId: f.model.sections[1]!.sectionId, afterLink: true, text: 'edited before saving link', expectedPartSha256: 'part1' }))
  expect(controller.valueOf('header', 'default')?.value.text).toBe('edited before saving link')
  f.draft.undo(); await opened.view.refresh()
  expect(controller.linked!('header', 'default').value).toBe(false)
  expect(controller.valueOf('header', 'default')?.value.text).toBe('header 1')
  f.draft.redo(); await opened.view.refresh()
  expect(controller.valueOf('header', 'default')?.value.text).toBe('edited before saving link')
  opened.view.dispose(); views.splice(views.indexOf(opened.view), 1); document.body.replaceChildren()
  const recovered = new NativeDraft(f.identity, f.store), reopened = await f.open(recovered)
  reopened.editor.commands.setTextSelection(reopened.editor.state.doc.content.size - 1)
  reopened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  expect(hfFixture.controller!.valueOf('header', 'default')?.value.text).toBe('edited before saving link')
})


it('edits the inherited owner immediately after linking on and keeps the two changes in recoverable history', async () => {
  const f = await setupMultiHf(), opened = await f.open()
  opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  controller.onLink!('header', 'default', true)
  controller.onCommit('header', 'default', { text: 'edited linked owner' })
  expect(f.draft.operations.find(operation => operation.kind === 'setHeaderFooter')).toMatchObject({ sectionId: f.model.sections[0]!.sectionId, text: 'edited linked owner' })
  expect(f.draft.operations.find(operation => operation.kind === 'setHeaderFooter')).not.toHaveProperty('afterLink')
  expect(controller.valueOf('header', 'default')?.value.text).toBe('edited linked owner')
  f.draft.undo(); await opened.view.refresh()
  expect(controller.linked!('header', 'default').value).toBe(true)
  expect(controller.valueOf('header', 'default')?.value.text).toBe('header 1')
  f.draft.redo(); await opened.view.refresh()
  expect(controller.valueOf('header', 'default')?.value.text).toBe('edited linked owner')
})


it.each([false, true])('freezes the edited intermediate owner when a third section unlinks (pending=%s)', async pending => {
  const f = await setupMultiHf(true)
  fixture.sectionCount = 3
  const third = { ...f.model.sections[1]!, sectionId: await bytesSha256(new TextEncoder().encode(`${f.identity.sourceSha256}:section:2`)) }
  f.model.sections.push(third)
  f.model.blocks.push({ ...f.model.blocks[0]!, blockId: await bytesSha256(new TextEncoder().encode(`${f.identity.sourceSha256}:block:2`)) })
  const opened = await f.open()
  opened.editor.commands.setTextSelection(opened.editor.state.doc.child(0).nodeSize + 1)
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  controller.onLink!('header', 'default', false)
  controller.onCommit('header', 'default', { text: 'intermediate X' })
  opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
  expect(controller.valueOf('header', 'default')?.value.text).toBe('intermediate X')
  controller.onLink!('header', 'default', false, pending ? { text: 'pending Y' } : undefined)
  const expected = pending ? 'pending Y' : 'intermediate X'
  expect(controller.valueOf('header', 'default')?.value.text).toBe(expected)
  expect(f.draft.operations.filter(operation => operation.kind === 'setHeaderFooter')).toEqual(expect.arrayContaining([
    expect.objectContaining({ sectionId: f.model.sections[1]!.sectionId, afterLink: true, text: expected }),
    expect.objectContaining({ sectionId: third.sectionId, afterLink: true, text: expected }),
  ]))
  f.draft.undo(); await opened.view.refresh()
  expect(controller.linked!('header', 'default').value).toBe(true)
  expect(controller.valueOf('header', 'default')?.value.text).toBe('intermediate X')
  f.draft.redo(); await opened.view.refresh()
  expect(controller.valueOf('header', 'default')?.value.text).toBe(expected)
})

it('flushes pending same-save HF content before leaving the header/footer tab', async () => {
  const f = await setupMultiHf(true), opened = await f.open()
  opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  controller.onLink!('header', 'default', false)
  const flush = vi.fn(() => controller.onCommit('header', 'default', { text: 'pending before tab exit' }))
  controller.registerEditor!({ flush, setEditable: vi.fn() })
  opened.layout()
  expect(flush).toHaveBeenCalledOnce()
  expect(f.draft.operations.find(operation => operation.kind === 'setHeaderFooter')).toMatchObject({ afterLink: true, text: 'pending before tab exit' })
})

it('main integrates note markers, root intent, undo/redo, persisted recovery and saving locks', async () => {
  const f = await setup(undefined, { footnotes: [], endnotes: [] }), opened = await f.open()
  const button = (action: string) => opened.shell.editor.querySelector<HTMLButtonElement>(`[data-note-action="${action}"]`)!
  flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="references"]')!.click())
  opened.editor.commands.setTextSelection(2)
  expect(button('insert-footnote').disabled).toBe(false)
  button('insert-footnote').click()
  const dialog = opened.shell.editor.querySelector<HTMLElement>('.workbook-ribbon-note-dialog')!
  dialog.querySelector<HTMLTextAreaElement>('textarea')!.value = '注释正文'
  flushSync(() => dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(f.draft.operations).toEqual([{ kind: 'insertNote', noteKind: 'footnote', blockId: expect.any(String), expectedObjectSha256: expect.any(String), offset: 1, text: '注释正文' }])
  expect(opened.editor.getJSON().content![0].content!.map(node => node.type)).toEqual(['text', 'docNoteRef', 'text'])
  opened.editor.commands.undo(); expect(f.draft.operations).toEqual([])
  opened.editor.commands.redo(); expect(f.draft.operations[0].text).toBe('注释正文')
  const recovered = new NativeDraft(f.identity, f.store)
  document.body.replaceChildren()
  const reopened = await f.open(recovered)
  expect(reopened.editor.getJSON().content![0].content!.filter(node => node.type === 'docNoteRef')).toHaveLength(1)
  expect(recovered.operations).toEqual(f.draft.operations)
  flushSync(() => reopened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="references"]')!.click())
  reopened.view.setSaving(true)
  expect(reopened.shell.editor.querySelector<HTMLButtonElement>('[data-note-action="insert-footnote"]')!.disabled).toBe(true)
})
it('keeps notes disabled for old preview mocks without removing ordinary editing', async () => {
  const f = await setup(), opened = await f.open()
  flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="references"]')!.click())
  expect(opened.shell.editor.querySelector<HTMLButtonElement>('[data-note-action="insert-footnote"]')!.disabled).toBe(true)
  opened.editor.commands.insertContent('可编辑')
  expect(f.draft.operations[0].kind).toBe('replaceParagraph')
})

it('deletes an existing note through schema text merging without treating it as body editing', async () => {
  fixture.noteMarker = true
  const notes = { footnotes: [{ id: '1', text: '原注释', expectedNoteSha256: 'note-sha', editable: true, references: [] as { blockId: string; expectedObjectSha256: string; referenceIndex: number }[] }], endnotes: [] }
  const f = await setup(undefined, notes), source = (await f.api.preview()).model.blocks[0]
  notes.footnotes[0].references.push({ blockId: source.blockId, expectedObjectSha256: source.expectedObjectSha256, referenceIndex: 0 })
  const opened = await f.open()
  flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="references"]')!.click())
  const select = opened.shell.editor.querySelector<HTMLSelectElement>('[aria-label="已有脚注和尾注"]')!
  flushSync(() => { select.value = JSON.stringify(['footnote', '1']); select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(opened.shell.editor.querySelector<HTMLButtonElement>('[data-note-action="delete"]')!.disabled).toBe(false)
  flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-note-action="delete"]')!.click())
  expect(f.draft.operations).toEqual([{ kind: 'deleteNote', noteKind: 'footnote', noteId: '1', expectedNoteSha256: 'note-sha', expectedReferences: notes.footnotes[0].references }])
  expect(opened.editor.getJSON().content![0].content).toEqual([{ type: 'text', text: '原文' }])
  opened.editor.commands.undo(); expect(f.draft.operations).toEqual([])
})

it('saves same-paragraph text before and after inserting a note with undo and continued recovered editing', async () => {
  const f = await setup(undefined, { footnotes: [], endnotes: [] }), opened = await f.open()
  opened.editor.commands.insertContentAt(2, '新增')
  const beforeNote = opened.editor.getJSON()
  opened.editor.commands.setTextSelection(4)
  flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="references"]')!.click())
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-note-action="insert-footnote"]')!.click()
  const dialog = opened.shell.editor.querySelector<HTMLElement>('.workbook-ribbon-note-dialog')!
  dialog.querySelector<HTMLTextAreaElement>('textarea')!.value = '同段脚注'
  flushSync(() => dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(opened.editor.getText()).toBe('原新增文')
  expect(f.draft.operations.map(op => op.kind)).toEqual(['patchParagraphRuns', 'insertNote'])
  opened.editor.commands.undo(); expect(opened.editor.getJSON().content).toEqual(beforeNote.content)
  opened.editor.commands.redo()
  opened.editor.commands.insertContentAt(5, '后续')
  expect(opened.editor.getText()).toBe('原新增后续文')
  const saved = structuredClone(f.draft.operations)
  opened.view.dispose(); views.splice(views.indexOf(opened.view), 1); document.body.replaceChildren()
  const recovered = new NativeDraft(f.identity, f.store), reopened = await f.open(recovered)
  expect(reopened.editor.getText()).toBe('原新增后续文')
  expect(recovered.operations).toEqual(saved)
  reopened.editor.commands.insertContentAt(reopened.editor.state.doc.content.size - 1, '再改')
  expect(reopened.editor.getText()).toBe('原新增后续文再改')
  expect(recovered.operations.map(op => op.kind)).toEqual(['patchParagraphRuns', 'insertNote'])
  expect(recovered.operations.find(op => op.kind === 'insertNote')!.offset).toBe(3)
})
it('deletes an existing note then edits its source paragraph while preserving draft undo', async () => {
  fixture.noteMarker = true
  const notes = { footnotes: [{ id: '1', text: '原注释', expectedNoteSha256: 'note-sha', editable: true, references: [] as { blockId: string; expectedObjectSha256: string; referenceIndex: number }[] }], endnotes: [] }
  const f = await setup(undefined, notes), source = (await f.api.preview()).model.blocks[0]
  notes.footnotes[0].references.push({ blockId: source.blockId, expectedObjectSha256: source.expectedObjectSha256, referenceIndex: 0 })
  const opened = await f.open()
  flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="references"]')!.click())
  const select = opened.shell.editor.querySelector<HTMLSelectElement>('[aria-label="已有脚注和尾注"]')!
  flushSync(() => { select.value = JSON.stringify(['footnote', '1']); select.dispatchEvent(new Event('change', { bubbles: true })) })
  flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-note-action="delete"]')!.click())
  opened.editor.commands.insertContentAt(2, '已改')
  expect(opened.editor.getText()).toBe('原已改文')
  expect(f.draft.operations.map(op => op.kind)).toEqual(['patchParagraphRuns', 'deleteNote'])
  opened.editor.commands.undo(); expect(opened.editor.getText()).toBe('原文')
})

it('prepares fixed first/last HF targets without moving body selection and invalidates them after draft changes', async () => {
  const f = await setupMultiHf(), opened = await f.open()
  opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!, selection = opened.editor.state.selection
  expect(controller.prepareEdges).toBeTypeOf('function')
  const measurement = vi.spyOn(paginationMeasurement, 'measureCurrentDocxPagination').mockResolvedValue({ cuts: [{ start: 0, end: 100, section: 0, pageNo: 2 }] as never, blocks: [], geoms: [], hfHs: [], rowSplits: [], live: [] })
  try {
    const edges = await controller.prepareEdges!()
    expect(edges.header.controller.anchor.sectionId).toBe(f.model.sections[0]!.sectionId)
    expect(edges.footer.controller.anchor.sectionId).toBe(f.model.sections[1]!.sectionId)
    expect(edges.header.part).toBe('header'); expect(edges.footer.part).toBe('footer')
    expect(opened.editor.state.selection.eq(selection)).toBe(true)
    expect(f.draft.operations).toEqual([])
    edges.assertCurrent()
    controller.onCommit('header', 'default', { text: 'changed header' })
    expect(() => edges.assertCurrent()).toThrow('发生变化')
    expect(measurement).toHaveBeenCalledOnce()
  } finally { measurement.mockRestore() }
})

it('rejects pending HF edge preparation after the real main view is disposed', async () => {
  const f = await setupMultiHf(), opened = await f.open()
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  expect(controller.prepareEdges).toBeTypeOf('function')
  const measurement = vi.spyOn(paginationMeasurement, 'measureCurrentDocxPagination').mockImplementation(async (_input, stillCurrent) => {
    opened.view.dispose(); views.splice(views.indexOf(opened.view), 1)
    expect(stillCurrent()).toBe(false)
    throw new Error('文档或页面设置发生变化')
  })
  try { await expect(controller.prepareEdges!()).rejects.toThrow('发生变化') }
  finally { measurement.mockRestore() }
})

it('invalidates an awaiting edge snapshot when body selection changes the canvas section geometry', async () => {
  const f = await setupMultiHf(), opened = await f.open()
  opened.editor.commands.setTextSelection(1)
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  const measurement = vi.spyOn(paginationMeasurement, 'measureCurrentDocxPagination').mockImplementation(async (_input, stillCurrent) => {
    opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
    expect(stillCurrent()).toBe(false)
    throw new Error('文档或页面设置发生变化')
  })
  try { await expect(controller.prepareEdges!()).rejects.toThrow('发生变化') }
  finally { measurement.mockRestore() }
})

it('clears an Insert edge controller after leaving HF so manual HF follows the current body section', async () => {
  const f = await setupMultiHf(), opened = await f.open()
  opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
  const measurement = vi.spyOn(paginationMeasurement, 'measureCurrentDocxPagination').mockResolvedValue({ cuts: [{ start: 0, end: 100, section: 0, pageNo: 2 }] as never, blocks: [], geoms: [], hfHs: [], rowSplits: [], live: [] })
  const tab = (id: string) => opened.shell.editor.querySelector<HTMLButtonElement>(`[data-tab-id="${id}"]`)!
  try {
    flushSync(() => tab('insert').click())
    flushSync(() => opened.shell.editor.querySelector<HTMLButtonElement>('[data-action="insert-header"]')!.click())
    await vi.waitFor(() => expect(opened.shell.editor.querySelector('[data-rb-panel] [role="status"]')).toBeNull())
    const edit = [...opened.shell.editor.querySelectorAll<HTMLButtonElement>('[data-rb-panel] button')].find(button => button.textContent === '编辑页眉')!
    flushSync(() => edit.click())
    expect(hfFixture.controller!.anchor.sectionId).toBe(f.model.sections[0]!.sectionId)
    flushSync(() => tab('home').click())
    opened.editor.commands.setTextSelection(opened.editor.state.doc.content.size - 1)
    flushSync(() => tab('headerFooter').click())
    expect(hfFixture.controller!.anchor.sectionId).toBe(f.model.sections[1]!.sectionId)
  } finally { measurement.mockRestore() }
})

it.each(['footnote', 'endnote'] as const)('rejects HF preparation when current %s references change during the shared font wait', async noteKind => {
  const f = await setupMultiHf()
  fixture.noteMarker = true; fixture.noteKind = noteKind
  Object.assign(f.model, { notes: { footnotes: [], endnotes: [], [`${noteKind}s`]: [{ id: '1', text: '原注释', expectedNoteSha256: 'note-sha', editable: true, references: [] }] } })
  const opened = await f.open()
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller = hfFixture.controller!
  let release!: () => void
  const ready = new Promise<void>(resolve => { release = resolve })
  const originalFonts = Object.getOwnPropertyDescriptor(document, 'fonts')
  Object.defineProperty(document, 'fonts', { configurable: true, value: { ready } })
  const measurement = vi.spyOn(paginationMeasurement, 'measureCurrentDocxPagination')
  try {
    const pending = controller.prepareEdges!()
    await Promise.resolve()
    opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="references"]')!.click()
    const select = opened.shell.editor.querySelector<HTMLSelectElement>('[aria-label="已有脚注和尾注"]')!
    select.value = JSON.stringify([noteKind, '1']); select.dispatchEvent(new Event('change', { bubbles: true }))
    await vi.waitFor(() => expect(opened.shell.editor.querySelector<HTMLButtonElement>('[data-note-action="delete"]')!.disabled).toBe(false))
    opened.shell.editor.querySelector<HTMLButtonElement>('[data-note-action="delete"]')!.click()
    release()
    await expect(pending).rejects.toThrow('发生变化')
    expect(measurement).not.toHaveBeenCalled()
  } finally {
    release(); measurement.mockRestore()
    if (originalFonts) Object.defineProperty(document, 'fonts', originalFonts)
    else delete (document as unknown as Record<string, unknown>).fonts
  }
})

it('reuses the committed unequal-column lifecycle for repeated edge preparation and resets on real body edits', async()=>{
 const layout=vi.spyOn(columnLayout,'layoutMixedDocxColumns').mockReturnValue({converged:true,passes:2})
 const measurement=vi.spyOn(paginationMeasurement,'measureCurrentDocxPagination').mockResolvedValue({cuts:[{start:0,end:100,section:0,pageNo:2}] as never,blocks:[],geoms:[],hfHs:[],rowSplits:[],live:[]})
 fixture.settings.columns=2
 fixture.sectionXml='<w:sectPr><w:cols w:num="2" w:equalWidth="0"><w:col w:w="1800" w:space="360"/><w:col w:w="3600"/></w:cols></w:sectPr>'
 try{
  const f=await setupMultiHf(),opened=await f.open()
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  const controller=hfFixture.controller!
  await controller.prepareEdges!();const calls=layout.mock.calls.length
  await controller.prepareEdges!()
  expect(layout.mock.calls.length).toBe(calls)
  const history=layout.mock.calls.at(-1)![2]!
  history.forced.set(document.createElement('p'),120)
  opened.editor.commands.insertContentAt(2,'改')
  await controller.prepareEdges!()
  expect(layout.mock.calls.length).toBeGreaterThan(calls)
  expect(layout.mock.calls.at(-1)![2]).toBe(history)
  expect(history.forced.size).toBe(0)
 }finally{layout.mockRestore();measurement.mockRestore();fixture.settings.columns=1;fixture.sectionXml='<w:sectPr/>'}
})
it('uses the committed natural-flow cuts for HF preparation without re-slicing display gaps',async()=>{
 const committed={blocks:[],slices:[],sections:[],cuts:[{start:0,end:100,section:0,pageNo:2}],geoms:[],hfHeights:[],rowSplits:[],carries:[]} as never
 const layout=vi.spyOn(columnLayout,'layoutMixedDocxColumns').mockReturnValue({converged:true,passes:2,layout:committed})
 const measurement=vi.spyOn(paginationMeasurement,'measureCurrentDocxPagination')
 fixture.settings.columns=2
 fixture.sectionXml='<w:sectPr><w:cols w:num="2" w:equalWidth="0"><w:col w:w="1800" w:space="360"/><w:col w:w="3600"/></w:cols></w:sectPr>'
 try{
  const f=await setupMultiHf(),opened=await f.open()
  opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="headerFooter"]')!.click()
  await hfFixture.controller!.prepareEdges!()
  expect(layout).toHaveBeenCalled()
  expect(measurement).not.toHaveBeenCalled()
 }finally{layout.mockRestore();measurement.mockRestore();fixture.settings.columns=1;fixture.sectionXml='<w:sectPr/>'}
})

it('main new comment captures exact text and flushes unblurred input into native history and recovery',async()=>{
 const f=await setup(undefined,undefined,undefined,{sourceId:'b'.repeat(64),readOnlyReason:null,targets:[{targetId:'c'.repeat(64),blockIndex:0,paragraphOrdinal:0,expectedParagraphSha256:'d'.repeat(64),text:'原文',readOnlyReason:null}]}),opened=await f.open()
 opened.editor.commands.setTextSelection({from:1,to:2})
 opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="review"]')!.click()
 const command=opened.shell.editor.querySelector<HTMLButtonElement>('[data-action="comment-create"]')!;expect(command.disabled).toBe(false);expect(command.querySelector('svg path')).not.toBeNull();command.click()
 const input=opened.shell.editor.querySelector<HTMLTextAreaElement>('[data-new-comment-text]')!;expect(opened.shell.editor.querySelector('[data-new-comment-selection]')!.textContent).toBe('原')
 input.value='取消草稿';input.dispatchEvent(new Event('input',{bubbles:true}));opened.shell.editor.querySelector<HTMLButtonElement>('[data-new-comment-cancel]')!.click();expect(f.draft.operations).toEqual([])
 opened.shell.editor.querySelector<HTMLButtonElement>('[data-tab-id="insert"]')!.click();const insert=opened.shell.editor.querySelector<HTMLButtonElement>('[data-action="insert-new-comment"]')!;expect(insert.disabled).toBe(false);expect(insert.querySelector('svg path')).not.toBeNull();insert.click();input.value='保存前未失焦的新批注';input.dispatchEvent(new Event('input',{bubbles:true}));opened.view.flushPendingEdits()
 expect(f.draft.operations).toHaveLength(1);expect(f.draft.operations[0]).toMatchObject({kind:'createComment',text:'保存前未失焦的新批注',ranges:[{from:0,to:1,text:'原'}]})
 const operations=f.draft.operations;opened.editor.commands.undo();expect(f.draft.operations).toEqual([]);opened.editor.commands.redo();expect(f.draft.operations).toEqual(operations)
 opened.view.dispose();views.splice(views.indexOf(opened.view),1);document.body.replaceChildren()
 const recovered=new NativeDraft(f.identity,f.store),restored=await f.open(recovered)
 expect(recovered.operations).toEqual(operations);expect(restored.editor.getJSON().attrs?.nativeCommentCreationOperations).toEqual(operations)
 const api={...f.api,save:vi.fn(async(_request:unknown)=>({documentId:f.identity.documentId,revision:2,parentRevision:1,revisionRegistered:true,artifacts:{word:{downloadUrl:'http://localhost/new-comment.docx'}},validation:{ok:false,issues:[{code:'review',message:'待复核'}]}})),export:vi.fn()}
 const session=bindNativeSession(restored.shell,{draft:recovered,api:api as never,format:'docx',view:restored.view})
 await session.save('save');expect((api.save.mock.calls[0][0] as {operations:unknown}).operations).toEqual(operations);expect(recovered.closed).toBe(true);session.dispose()
})

it('main binds existing comment reply to native undo redo recovery and unblurred save',async()=>{
 fixture.comments=[{id:'7',author:'Alice',text:'Original comment'}]
 const comments=commentManifest(),replies={sourceId:comments.sourceId,readOnlyReason:null,targets:comments.commentTargets.map(t=>({...t,parentId:null,canReply:true,replyReadOnlyReason:null}))}
 const f=await setup(undefined,undefined,comments,undefined,replies),opened=await f.open();openCommentPanel(opened)
 const button=opened.shell.editor.querySelector<HTMLButtonElement>('[data-comment-reply]')!;expect(button).not.toBeNull();expect(button.disabled).toBe(false);button.click()
 const input=opened.shell.editor.querySelector<HTMLTextAreaElement>('[data-comment-reply-text]')!;expect(opened.shell.editor.querySelector('[data-comment-reply-parent]')!.textContent).toContain('Original comment')
 input.value='取消回复';opened.shell.editor.querySelector<HTMLButtonElement>('[data-comment-reply-cancel]')!.click();expect(f.draft.operations).toEqual([])
 button.click();input.value='未失焦的回复😀';opened.view.flushPendingEdits()
 expect(f.draft.operations).toHaveLength(1);expect(f.draft.operations[0]).toMatchObject({kind:'replyComment',targetId:'d'.repeat(64),text:'未失焦的回复😀'})
 const operations=f.draft.operations;opened.editor.commands.undo();expect(f.draft.operations).toEqual([]);opened.editor.commands.redo();expect(f.draft.operations).toEqual(operations)
 opened.editor.commands.insertContentAt(2,'不得混合');expect(opened.editor.getText()).toBe('原文')
 opened.view.dispose();views.splice(views.indexOf(opened.view),1);document.body.replaceChildren()
 const recovered=new NativeDraft(f.identity,f.store),restored=await f.open(recovered)
 expect(recovered.operations).toEqual(operations);expect(restored.editor.getJSON().attrs?.nativeCommentReplyOperations).toEqual(operations)
 const api={...f.api,save:vi.fn(async(_request:unknown)=>({documentId:f.identity.documentId,revision:2,parentRevision:1,revisionRegistered:true,artifacts:{word:{downloadUrl:'http://localhost/reply.docx'}},validation:{ok:false,issues:[{code:'review',message:'待复核'}]}})),export:vi.fn()}
 const session=bindNativeSession(restored.shell,{draft:recovered,api:api as never,format:'docx',view:restored.view})
 await session.save('save');expect((api.save.mock.calls[0][0] as {operations:unknown}).operations).toEqual(operations);expect(recovered.closed).toBe(true);session.dispose()
})
