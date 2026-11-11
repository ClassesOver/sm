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
  localStorage.clear()
  const root = document.createElement('div'); document.body.append(root)
  const sourceSha256 = 'a'.repeat(64), pageId = `sha256:${sourceSha256}:page:0`
  const identity = { documentId: 'extract-entry', revision: 1, sourceSha256, scope: { database: 'db', companyId: 'c', userId: 'u', threadId: 't' } }
  const draft = new NativeDraft(identity, localStorage)
  const convertOffice = vi.fn(async (_payload: {requestId:string;expectedSha256:string;format:'docx'|'xlsx'}) => ({ documentId: 'child', revision: 1, parentRevision: null, revisionRegistered: true,
    artifacts: { word: { downloadUrl: '/reports/v1/download/child/word' },xlsx: {downloadUrl:'/reports/v1/download/child/xlsx'} }, validation: { ok: false, issues: [{ code: 'pending', message: '验收待完成' }] } }))
  const api = { convertOffice, file: async () => new Uint8Array([1, 2]).buffer, preview: async () => ({ sourceSha256, model: { sourceSha256, pages: [{ pageId, notesReadSafe: true }], capabilities: { cropPage: true } } }) } as unknown as ReturnType<typeof createNativeApi>
  const context = { context: { documentId: 'extract-entry', revision: 1, format: 'pdf', scope: identity.scope, sourceFile: { sha256: sourceSha256 } }, editingEnabled, pdfTextEnabled: false } as NativeContextResponse
  const view = await createPdfEditorView({ editor: root, save: document.createElement('button') } as unknown as EditorShell, { api, context, draft })
  views.push(view)
  const open = root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.convert.toWord"]')!
  const dialog = root.querySelector<HTMLDialogElement>('dialog.pdf-layout-dialog')!
  return { root, draft, view, open, dialog, convertOffice, pageId }
}


for(const [format,command,label] of [['docx','toWord','Word'],['xlsx','toExcel','Excel']] as const){
  it('opens '+label+' conversion from the Ribbon and keeps the PDF draft unchanged',async()=>{
    const f=await fixture(),open=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.convert.'+command+'"]')!
    expect(open.disabled).toBe(false);open.click()
    await vi.waitFor(()=>expect(f.root.querySelector<HTMLDialogElement>('[aria-label="转换 PDF 为'+label+'"]')?.open).toBe(true))
    const dialog=f.root.querySelector<HTMLDialogElement>('[aria-label="转换 PDF 为'+label+'"]')!
    expect(dialog.open).toBe(true);dialog.querySelector<HTMLButtonElement>('[data-pdf-convert-office-apply]')!.click()
    await vi.waitFor(()=>expect(dialog.querySelector('a')).not.toBeNull())
    expect(f.convertOffice).toHaveBeenCalledWith(expect.objectContaining({expectedSha256:'a'.repeat(64),format}))
    expect(dialog.textContent).toContain('验收未通过');expect(f.draft.operations).toEqual([])
  })
}
it('forced conversion command and submit respect readonly, saving and dirty source guards',async()=>{
  for(const state of ['readonly','saving','dirty']){
    const f=await fixture(state!=='readonly')
    if(state==='saving')f.view.setSaving(true)
    if(state==='dirty'){f.draft.setOperations([{kind:'rotatePage',pageId:f.pageId,delta:90}]);await f.view.refresh()}
    f.open.dispatchEvent(new MouseEvent('click'))
    expect(f.root.querySelector<HTMLDialogElement>('[aria-label="转换 PDF 为Word"]')?.open??false).toBe(false)
    expect(f.convertOffice).not.toHaveBeenCalled()
  }
  const f=await fixture();f.open.click();await vi.waitFor(()=>expect(f.root.querySelector<HTMLDialogElement>('[aria-label="转换 PDF 为Word"]')?.open).toBe(true));const dialog=f.root.querySelector<HTMLDialogElement>('[aria-label="转换 PDF 为Word"]')!
  f.draft.setOperations([{kind:'rotatePage',pageId:f.pageId,delta:90}]);dialog.querySelector<HTMLButtonElement>('[data-pdf-convert-office-apply]')!.dispatchEvent(new MouseEvent('click'))
  await vi.waitFor(()=>expect(dialog.textContent).toContain('先保存或撤销'));expect(f.convertOffice).not.toHaveBeenCalled()
})
