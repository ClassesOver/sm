import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NativeDraft } from './native-draft'
import { createPdfEditorView, type PdfEditorHandle } from './pdf-main'
import type { EditorShell } from './shell'
import type { createNativeApi, NativeContextResponse } from './native-api'

const fixtureState = vi.hoisted(() => ({ pending: false, renders: [] as { resolve: () => void; reject: () => void; cancel: ReturnType<typeof vi.fn> }[] }))
vi.mock('./source-validation', () => ({ bytesSha256: async () => 'a'.repeat(64) }))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => {
  class Viewport {
    viewBox: number[]; width: number; height: number
    constructor({ viewBox = [0, 0, 400, 500], scale = 1 }: { viewBox?: number[]; scale?: number }) {
      this.viewBox = viewBox; this.width = (viewBox[2]! - viewBox[0]!) * scale; this.height = (viewBox[3]! - viewBox[1]!) * scale
    }
    convertToPdfPoint(x: number, y: number) { return [this.viewBox[0]! + x / this.width * (this.viewBox[2]! - this.viewBox[0]!), this.viewBox[3]! - y / this.height * (this.viewBox[3]! - this.viewBox[1]!)] }
  }
  const page = { view: [0, 0, 400, 500], rotate: 0, userUnit: 1,
    getViewport: (options: { scale: number }) => new Viewport(options), getTextContent: async () => ({ items: [] }), getAnnotations: async () => [],
    render() {
      let resolve!: () => void
      let reject!: (error: Error) => void
      const promise = fixtureState.pending ? new Promise<void>((done, fail) => { resolve = done; reject = fail }) : Promise.resolve()
      const cancel = vi.fn(() => resolve?.())
      fixtureState.renders.push({ resolve: () => resolve?.(), reject: () => reject?.(new Error('render failed')), cancel })
      return { promise, cancel }
    },
  }
  const document = { numPages: 1, getPage: async () => page, getMetadata: async () => ({ info: {} }), getOutline: async () => [], destroy: async () => {} }
  return { AnnotationMode: { ENABLE: 1 }, GlobalWorkerOptions: {}, TextLayer: class {}, getDocument: () => ({ promise: Promise.resolve(document), destroy: async () => {} }) }
})

const views: PdfEditorHandle[] = []
beforeEach(() => {
  fixtureState.pending = false; fixtureState.renders = []; localStorage.clear()
  vi.stubGlobal('IntersectionObserver', class { observe() {} disconnect() {} unobserve() {} })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
})
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

async function fixture() {
  const root = document.createElement('div'); document.body.append(root)
  const sourceSha256 = 'a'.repeat(64), pageId = `sha256:${sourceSha256}:page:0`
  const identity = { documentId: 'crop-dialog', revision: 1, sourceSha256, scope: { database: 'db', companyId: 'c', userId: 'u', threadId: 't' } }
  const draft = new NativeDraft(identity, localStorage)
  const api = { file: async () => new Uint8Array([1, 2]).buffer, previewFile: vi.fn(async () => new Uint8Array([3, 4]).buffer), preview: async () => ({ sourceSha256, previewDigest: 'b'.repeat(64), appliedOperationIndices: [0], skippedOperations: [], model: { sourceSha256, pages: [{ pageId, notesReadSafe: true }], capabilities: { cropPage: true } } }) } as unknown as ReturnType<typeof createNativeApi>
  const context = { context: { documentId: 'crop-dialog', revision: 1, format: 'pdf', scope: identity.scope, sourceFile: { sha256: sourceSha256 } }, editingEnabled: true, pdfTextEnabled: false } as NativeContextResponse
  const view = await createPdfEditorView({ editor: root, save: document.createElement('button') } as unknown as EditorShell, { api, context, draft })
  views.push(view)
  const open = root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.page.crop"]')!
  const dialog = root.querySelector<HTMLDialogElement>('dialog[aria-label="裁切当前页面"]')!
  const inputs = [...dialog.querySelectorAll<HTMLInputElement>('input[type="number"]')]
  return { root, draft, view, open, dialog, inputs, pageId, api }
}

it('loads the actual PDF for a crop-only draft and returns to source editing without losing the crop', async () => {
  const f = await fixture()
  const operations = [{ kind: 'cropPage', pageId: f.pageId, rect: [40, 50, 360, 450] }]
  f.draft.setOperations(operations)
  await f.view.refresh()
  const preview = [...f.root.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '校验当前修改')!
  preview.click()
  await vi.waitFor(() => expect(f.api.previewFile).toHaveBeenCalledWith({ expectedSha256: 'a'.repeat(64), operations, expectedPreviewDigest: 'b'.repeat(64) }, expect.any(AbortSignal)))
  await vi.waitFor(() => expect(f.root.dataset.pdfPreview).toBe('true'))
  expect(f.draft.operations).toEqual(operations)
  expect(f.open.disabled).toBe(true)
  const back = [...f.root.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '返回原稿编辑')!
  back.click()
  await vi.waitFor(() => expect(f.root.dataset.pdfPreview).toBe('false'))
  expect(f.draft.operations).toEqual(operations)
  expect(f.open.disabled).toBe(false)
})

it('connects the real crop dialog handles to margins and one existing crop draft operation', async () => {
  const f = await fixture(); f.open.click()
  await vi.waitFor(() => expect(f.dialog.querySelectorAll('[data-pdf-crop-handle]')).toHaveLength(8))
  const stage = f.dialog.querySelector<HTMLElement>('[data-pdf-crop-canvas]')!
  vi.spyOn(stage, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 400, height: 500 } as DOMRect)
  const send = (target: EventTarget, type: string, clientX: number, clientY: number) => {
    const event = new MouseEvent(type, { bubbles: true, button: 0, clientX, clientY })
    Object.defineProperty(event, 'pointerId', { value: 1 }); target.dispatchEvent(event)
  }
  send(f.dialog.querySelector('[data-pdf-crop-handle="nw"]')!, 'pointerdown', 0, 0)
  send(window, 'pointermove', 40, 100); send(window, 'pointerup', 40, 100)
  expect(f.inputs.map(input => input.value)).toEqual(['10', '20', '0', '0'])
  f.inputs[2]!.value = '30'; f.inputs[2]!.dispatchEvent(new Event('input'))
  expect(f.dialog.querySelector<HTMLElement>('[data-pdf-crop-region]')!.style.width).toBe('60%')
  expect(f.draft.operations).toEqual([])
  ;[...f.dialog.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '应用裁切')!.click()
  await vi.waitFor(() => expect(f.draft.operations).toEqual([{ kind: 'cropPage', pageId: f.pageId, rect: [40, 0, 280, 400] }]))
  expect(f.dialog.open).toBe(false)
  f.draft.undo(); expect(f.draft.operations).toEqual([])
})

it.each(['close', 'draft', 'dispose'])('discards a late crop screenshot after %s without changing the draft', async reason => {
  const f = await fixture(); fixtureState.pending = true; f.open.click()
  await vi.waitFor(() => expect(fixtureState.renders).toHaveLength(1))
  const task = fixtureState.renders[0]!
  if (reason === 'close') f.dialog.close()
  else if (reason === 'draft') f.draft.setOperations([{ kind: 'rotatePage', pageId: f.pageId, delta: 90 }])
  else f.view.dispose()
  task.resolve()
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(f.root.querySelector('[data-pdf-crop-canvas]')).toBeNull()
  expect(f.draft.operations).toEqual(reason === 'draft' ? [{ kind: 'rotatePage', pageId: f.pageId, delta: 90 }] : [])
  if (reason === 'draft') expect(f.dialog.textContent).toContain('草稿已变化')
  if (reason !== 'draft') expect(task.cancel).toHaveBeenCalled()
})

it('rejects stale numeric apply and forced crop opening while saving', async () => {
  const f = await fixture()
  f.view.setSaving(true)
  f.open.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(f.dialog.open).toBe(false); expect(fixtureState.renders).toHaveLength(0)
  f.view.setSaving(false); f.open.click()
  await vi.waitFor(() => expect(f.dialog.querySelector('[data-pdf-crop-canvas]')).not.toBeNull())
  const before = [{ kind: 'rotatePage', pageId: f.pageId, delta: 90 }]
  f.draft.setOperations(before)
  f.inputs[0]!.value = '10'
  ;[...f.dialog.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '应用裁切')!.click()
  await vi.waitFor(() => expect(f.dialog.textContent).toContain('草稿已变化'))
  expect(f.draft.operations).toEqual(before)
})

it('ends loading with a stale-draft explanation if a late screenshot fails', async () => {
  const f = await fixture(); fixtureState.pending = true; f.open.click()
  await vi.waitFor(() => expect(fixtureState.renders).toHaveLength(1))
  f.draft.setOperations([{ kind: 'rotatePage', pageId: f.pageId, delta: 90 }])
  fixtureState.renders[0]!.reject()
  await vi.waitFor(() => expect(f.dialog.textContent).toContain('草稿已变化'))
  expect(f.dialog.textContent).not.toContain('正在读取当前页面')
})
