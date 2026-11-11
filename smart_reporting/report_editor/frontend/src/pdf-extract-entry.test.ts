import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NativeDraft } from './native-draft'
import { createPdfEditorView, type PdfEditorHandle } from './pdf-main'
import type { EditorShell } from './shell'
import type { createNativeApi, NativeContextResponse } from './native-api'

vi.mock('./source-validation', () => ({ bytesSha256: async () => 'a'.repeat(64) }))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => {
  const page = { view: [0, 0, 400, 500], rotate: 0, userUnit: 1,
    getViewport: () => ({ viewBox: [0, 0, 400, 500], width: 400, height: 500 }), getTextContent: async () => ({ items: [] }), getAnnotations: async () => [],
    render: () => ({ promise: Promise.resolve(), cancel() {} }) }
  const document = { numPages: 1, getPage: async () => page, getMetadata: async () => ({ info: {} }), getOutline: async () => [], destroy: async () => {} }
  return { AnnotationMode: { ENABLE: 1 }, GlobalWorkerOptions: {}, TextLayer: class {}, getDocument: () => ({ promise: Promise.resolve(document), destroy: async () => {} }) }
})

const views: PdfEditorHandle[] = []
beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('IntersectionObserver', class { observe() {} disconnect() {} unobserve() {} })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
})
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

async function fixture(editingEnabled = true) {
  const root = document.createElement('div'); document.body.append(root)
  const sourceSha256 = 'a'.repeat(64), pageId = `sha256:${sourceSha256}:page:0`
  const identity = { documentId: 'extract-entry', revision: 1, sourceSha256, scope: { database: 'db', companyId: 'c', userId: 'u', threadId: 't' } }
  const draft = new NativeDraft(identity, localStorage)
  const extractPages = vi.fn(async (_payload: {requestId: string; expectedSha256: string; pages: number[]}) => ({ documentId: 'child', revision: 1, parentRevision: null, revisionRegistered: true,
    artifacts: { pdf: { downloadUrl: '/reports/v1/download/child/pdf' } }, validation: { ok: false, issues: [{ code: 'pending', message: '验收待完成' }] } }))
  const api = { extractPages, file: async () => new Uint8Array([1, 2]).buffer, preview: async () => ({ sourceSha256, model: { sourceSha256, pages: [{ pageId, notesReadSafe: true }], capabilities: { cropPage: true } } }) } as unknown as ReturnType<typeof createNativeApi>
  const context = { context: { documentId: 'extract-entry', revision: 1, format: 'pdf', scope: identity.scope, sourceFile: { sha256: sourceSha256 } }, editingEnabled, pdfTextEnabled: false } as NativeContextResponse
  const view = await createPdfEditorView({ editor: root, save: document.createElement('button') } as unknown as EditorShell, { api, context, draft })
  views.push(view)
  const open = root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.page.extract"]')!
  const dialog = root.querySelector<HTMLDialogElement>('dialog[aria-label="提取页面"]')!
  return { root, draft, view, open, dialog, extractPages, pageId }
}

it('opens the actual Ribbon extraction command and displays the separate PDF without dirtying the source draft', async () => {
  const f = await fixture(); expect(f.open.disabled).toBe(false); f.open.click()
  await vi.waitFor(() => expect(f.dialog.open).toBe(true))
  f.dialog.querySelector<HTMLButtonElement>('[data-pdf-extract-apply]')!.click()
  await vi.waitFor(() => expect(f.dialog.querySelector('a')).not.toBeNull())
  expect(f.extractPages.mock.calls[0]![0]).toMatchObject({ expectedSha256: 'a'.repeat(64), pages: [1] })
  expect(f.draft.operations).toEqual([]); expect(f.draft.dirty).toBe(false)
  expect(f.dialog.textContent).toContain('验收未通过')
})

it('rejects forced Ribbon and submit actions for readonly, saving and unsaved source state', async () => {
  const readonly = await fixture(false)
  readonly.open.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(readonly.dialog.open).toBe(false); expect(readonly.extractPages).not.toHaveBeenCalled()
  const f = await fixture(); f.view.setSaving(true)
  f.open.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(f.dialog.open).toBe(false)
  f.view.setSaving(false); f.open.click(); await vi.waitFor(() => expect(f.dialog.open).toBe(true))
  f.draft.setOperations([{ kind: 'rotatePage', pageId: f.pageId, delta: 90 }])
  f.dialog.querySelector<HTMLButtonElement>('[data-pdf-extract-apply]')!.dispatchEvent(new MouseEvent('click'))
  await vi.waitFor(() => expect(f.dialog.textContent).toContain('先保存或撤销'))
  expect(f.extractPages).not.toHaveBeenCalled()
  expect(f.draft.operations).toHaveLength(1)
})
