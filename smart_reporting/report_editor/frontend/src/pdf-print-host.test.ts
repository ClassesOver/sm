import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NativeDraft } from './native-draft'
import { createPdfEditorView, type PdfEditorHandle } from './pdf-main'
import type { EditorShell } from './shell'
import type { createNativeApi, NativeContextResponse } from './native-api'

vi.mock('./source-validation', () => ({ bytesSha256: async () => 'a'.repeat(64) }))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => {
  class Viewport {
    viewBox: number[]; width: number; height: number
    constructor({ viewBox = [0, 0, 400, 500], scale = 1 }: { viewBox?: number[]; scale?: number }) {
      this.viewBox = viewBox; this.width = (viewBox[2]! - viewBox[0]!) * scale; this.height = (viewBox[3]! - viewBox[1]!) * scale
    }
  }
  const page = { view: [0, 0, 400, 500], rotate: 0, userUnit: 1,
    getViewport: ({ scale = 1 }: { scale?: number }) => new Viewport({ scale }),
    getTextContent: async () => ({ items: [] }), getAnnotations: async () => [],
    render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }) }
  const source = { numPages: 1, getPage: async () => page, getMetadata: async () => ({ info: {} }), getOutline: async () => [], destroy: async () => {} }
  return { AnnotationMode: { ENABLE: 1 }, GlobalWorkerOptions: {}, TextLayer: class {}, getDocument: () => ({ promise: Promise.resolve(source), destroy: async () => {} }) }
})

const views: PdfEditorHandle[] = []
beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('IntersectionObserver', class { observe() {} disconnect() {} unobserve() {} })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
  Object.defineProperty(window, 'print', { configurable: true, value: vi.fn() })
})
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('opens the print range dialog from the Ribbon and prints the selected visible page', async () => {
  const root = document.createElement('div'); document.body.append(root)
  const sourceSha256 = 'a'.repeat(64), pageId = `sha256:${sourceSha256}:page:0`
  const identity = { documentId: 'print-dialog', revision: 1, sourceSha256, scope: { database: 'db', companyId: 'c', userId: 'u', threadId: 't' } }
  const draft = new NativeDraft(identity, localStorage)
  const api = { file: async () => new Uint8Array([1, 2]).buffer, previewFile: async () => new Uint8Array([3, 4]).buffer,
    preview: async () => ({ sourceSha256, previewDigest: 'b'.repeat(64), appliedOperationIndices: [], skippedOperations: [], model: { sourceSha256, pages: [{ pageId, markupReadSafe: true }], capabilities: {} } }) } as unknown as ReturnType<typeof createNativeApi>
  const context = { context: { documentId: 'print-dialog', revision: 1, format: 'pdf', scope: identity.scope, sourceFile: { sha256: sourceSha256, path: '/workspace/source.pdf' } }, editingEnabled: true, pdfTextEnabled: false } as NativeContextResponse
  const view = await createPdfEditorView({ editor: root, save: document.createElement('button') } as unknown as EditorShell, { api, context, draft })
  views.push(view)
  const command = root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.print.print"]')!
  command.click()
  const dialog = root.querySelector<HTMLDialogElement>('dialog[aria-label="打印 PDF"]')!
  expect(dialog.open).toBe(true)
  dialog.querySelector<HTMLInputElement>('input[value="custom"]')!.click()
  dialog.querySelector<HTMLInputElement>('[aria-label="打印页码"]')!.value = '1'
  dialog.querySelector<HTMLButtonElement>('[data-pdf-print-confirm]')!.click()
  await vi.waitFor(() => expect(root.querySelectorAll('.pdf-print-page')).toHaveLength(1))
  expect(window.print).toHaveBeenCalledOnce()
  expect(root.querySelector('.pdf-print-page')?.getAttribute('aria-label')).toBe('第 1 页')
})
