import { afterEach, expect, it, vi } from 'vitest'
import type { Editor } from '@tiptap/core'
import { createDocxEditorView } from './docx-main'
import { createEditorShell } from './shell'
import { NativeDraft, type NativeDraftIdentity } from './native-draft'
import type { NativeContextResponse } from './native-api'
import { bytesSha256 } from './source-validation'

const fixture = vi.hoisted(() => ({ settings: { pageWidth: 12240, pageHeight: 15840, orientation: 'portrait',
  marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1, headerDist: 720, footerDist: 720, pageBorder: false },
  sectionXml: '<w:sectPr/>', blockXml: '<w:p><w:r><w:t>原文</w:t></w:r></w:p>' }))
vi.mock('@genoffice/docx-engine', () => ({
  readSectionSettings: () => ({ ...fixture.settings }),
  readSections: () => [{ settings: { ...fixture.settings }, lastBlockIndex: 1, sectPrXml: fixture.sectionXml }],
}))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/parse-off-thread', () => ({ parseDocxOffThread: async () => ({
  blocks: [{ docxIndex: 0, type: 'paragraph', originalXml: fixture.blockXml }], fontTable: [], styles: [], numbering: new Map(),
}) }))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/editor/convert', () => ({ pmDocOptions: () => ({}),
  blocksToPmDoc: () => ({ type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: '原文' }] }] }),
}))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions', async () => {
  const { Node, Extension } = await import('@tiptap/core')
  return { editorExtensions: [
    Node.create({ name: 'doc', topNode: true, content: 'block+' }),
    Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => ({ docxIndex: { default: 0 } }), renderHTML: () => ['p', 0] }),
    Node.create({ name: 'text', group: 'inline' }),
    Extension.create({ name: 'listNumbering', addStorage: () => ({}) }), Extension.create({ name: 'tabStops', addStorage: () => ({}) }),
  ] }
})
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/components/PaginationPreview', () => ({ PaginationPreview: () => null }))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/doc-style-css', () => ({ docStyleCss: () => '' }))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/embedded-fonts', () => ({ adoptEmbeddedFonts: async () => true }))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/font-resolve', () => ({ setResolverFontTable: () => {} }))
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/editor/protected-render', () => ({ setStaticAsciiResolver: () => {} }))

const views: Awaited<ReturnType<typeof createDocxEditorView>>[] = []
afterEach(() => { for (const view of views.splice(0)) view.dispose(); document.body.replaceChildren() })
const storage = () => {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
}
async function setup() {
  const bytes = new TextEncoder().encode('来源 Word 固定快照'), sha = await bytesSha256(bytes)
  const hashText = (text: string) => bytesSha256(new TextEncoder().encode(text))
  const identity: NativeDraftIdentity = { documentId: 'word-recovery', revision: 1, sourceSha256: sha,
    scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
  const section = { sectionId: await hashText(`${sha}:section:1`), expectedSectionSha256: await hashText(fixture.sectionXml), settings: { ...fixture.settings } }
  const model = { sourceSha256: sha, sections: [section], blocks: [{ type: 'paragraph', blockId: await hashText(`${sha}:block:0`), expectedObjectSha256: await hashText(fixture.blockXml), editable: true }] }
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
const changedValues = { orientation: 'landscape', pageWidth: 15840, pageHeight: 12240, marginLeft: 720, columns: 2, headerDist: 900 }

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

it('DOCX recovery verifies inspected section identity against the parsed source bytes', async () => {
  const f = await setup()
  f.section.expectedSectionSha256 = 'foreign-section-hash'
  await expect(f.open().then(() => undefined)).rejects.toThrow(/节身份校验失败/)
})
