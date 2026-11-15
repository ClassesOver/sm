import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NativeDraft } from './native-draft'
import { createPdfEditorView, type PdfEditorHandle } from './pdf-main'
import type { EditorShell } from './shell'
import type { createNativeApi, NativeContextResponse } from './native-api'

vi.mock('./source-validation', () => ({ bytesSha256: async () => 'a'.repeat(64) }))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => {
  class Viewport {
    width: number; height: number; viewBox: number[]
    constructor({ scale = 1, viewBox = [0, 0, 300, 400] }: { scale?: number; viewBox?: number[] }) { this.viewBox = viewBox; this.width = 300 * scale; this.height = 400 * scale }
    convertToPdfPoint(x: number, y: number) { return [x * 300 / this.width, 400 - y * 400 / this.height] }
    convertToViewportPoint(x: number, y: number) { return [x * this.width / 300, (400-y) * this.height / 400] }
  }
  const page = { view: [0, 0, 300, 400], rotate: 0, userUnit: 1, getViewport: (options: { scale: number }) => new Viewport(options), getTextContent: async () => ({ items: [] }), streamTextContent: () => ({}), getAnnotations: async () => [], render: () => ({ promise: Promise.resolve(), cancel() {} }) }
  const pdf = { numPages: 1, getPage: async () => page, getMetadata: async () => ({ info: {} }), getOutline: async () => [], destroy: async () => {} }
  return { AnnotationMode: { ENABLE: 1 }, GlobalWorkerOptions: {}, TextLayer: class { render = async () => {}; cancel() {} }, getDocument: () => ({ promise: Promise.resolve(pdf), destroy: async () => {} }) }
})
const views: PdfEditorHandle[] = []
beforeEach(() => {
  localStorage.clear(); vi.stubGlobal('IntersectionObserver', undefined)
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value() {} })
})
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
async function fixture(editingEnabled = true, capability = true, skipped = false, pdfTextEnabled = true) {
  const root = document.createElement('div'); document.body.append(root)
  const sourceSha256 = 'a'.repeat(64), pageId = `sha256:${sourceSha256}:page:0`
  const identity = { documentId: `static-${views.length}`, revision: 1, sourceSha256, scope: { database: 'db', companyId: 'c', userId: 'u', threadId: 't' } }
  const draft = new NativeDraft(identity, localStorage)
  const api = { file: async () => new Uint8Array([1, 2]).buffer, previewFile: async () => new Uint8Array([3, 4]).buffer,
    preview: async () => ({ sourceSha256, previewDigest: 'f'.repeat(64), appliedOperationIndices: skipped ? [] : [0], skippedOperations: skipped ? [{ operationIndex: 0, kind: 'insertText', pageId, reason: 'missing embedded glyph' }] : [], model: { sourceSha256, pages: [{ pageId, notesReadSafe: true,textObjects:[{objectId:'original',expectedTextSha256:'b'.repeat(64),text:'Original',rect:[60,300,130,315],fontSize:14,fontName:'Arial',fontSha256:null}] }], attachments: [], attachmentsEditable: true, capabilities: { moveText:capability,insertText: capability, insertTextReason: capability ? null : '来源含批注，暂不支持插入文字' } } }) } as unknown as ReturnType<typeof createNativeApi>
  const context = { context: { documentId: identity.documentId, revision: 1, format: 'pdf', scope: identity.scope, sourceFile: { sha256: sourceSha256, path: 'source.pdf', size: 2 } }, editingEnabled, pdfTextEnabled } as NativeContextResponse
  const view = await createPdfEditorView({ editor: root, save: document.createElement('button') } as unknown as EditorShell, { api, context, draft }); views.push(view)
  const open = root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.edit.insertText"]')!
  return { root, draft, view, open, pageId, sourceSha256 }
}
async function configure(f: Awaited<ReturnType<typeof fixture>>, text = 'Report 123') {
  f.open.click()
  const dialog = f.root.querySelector<HTMLDialogElement>('[aria-label="插入文字"]')!
  await vi.waitFor(() => expect(dialog.open).toBe(true))
  dialog.querySelector<HTMLTextAreaElement>('[aria-label="插入文字内容"]')!.value = text
  dialog.querySelector<HTMLInputElement>('[aria-label="插入文字字号"]')!.value = '18'
  dialog.querySelector<HTMLInputElement>('[aria-label="插入文字颜色"]')!.value = '#336699'
  dialog.querySelector<HTMLSelectElement>('[aria-label="插入文字对齐"]')!.value = 'left'
  dialog.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click()
  return dialog
}
async function place(f: Awaited<ReturnType<typeof fixture>>) {
  await vi.waitFor(() => expect(f.root.querySelector('.pdf-page-content')?.querySelector('canvas')).not.toBeNull())
  const holder = f.root.querySelector<HTMLElement>('.pdf-page-content')!
  vi.spyOn(holder, 'getBoundingClientRect').mockReturnValue({ left: 10, top: 20, width: 600, height: 800 } as DOMRect)
  holder.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0, clientX: 210, clientY: 420 }))
  holder.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, button: 0, clientX: 210, clientY: 420 }))
}
it('public insert command stages a searchable text operation at the inverse baseline and supports Undo/Redo', async () => {
  const f = await fixture(); expect(f.open.disabled).toBe(false)
  await configure(f); expect(f.draft.operations).toEqual([])
  await expect(f.view.prepareSave()).rejects.toThrow('落点')
  await place(f)
  const expected = [{ kind: 'insertText', sourceSha256: f.sourceSha256, pageId: f.pageId, origin: [100, 200], text: 'Report 123', fontSize: 18, color: [0.2, 0.4, 0.6], align: 'left' }]
  await vi.waitFor(() => expect(f.draft.operations).toEqual(expected))
  const rotate = f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.page.rotateRight"]')!
  expect(rotate.disabled).toBe(true); rotate.dispatchEvent(new MouseEvent('click'))
  await Promise.resolve(); expect(f.draft.operations).toEqual(expected)
  f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.edit.undo"]')!.click()
  await vi.waitFor(() => expect(f.draft.operations).toEqual([]))
  f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.edit.redo"]')!.click()
  await vi.waitFor(() => expect(f.draft.operations).toEqual(expected))
})
it.each([false, true])('actual insert preview requires confirmation and presents skipped output (%s)', async skipped => {
  const f = await fixture(true, true, skipped); await configure(f); await place(f)
  await vi.waitFor(() => expect(f.draft.operations).toHaveLength(1))
  await expect(f.view.prepareSave()).rejects.toThrow('请核对实际 PDF 预览')
  expect(f.root.dataset.pdfPreview).toBe('true')
  const review = f.root.querySelector<HTMLElement>('.pdf-preview-review')!
  expect(review.hidden).toBe(false); expect(review.textContent).toContain('插入文字')
  if (skipped) {
    expect(review.textContent).toContain('missing embedded glyph')
    expect(review.textContent).toContain('以实际 PDF 为准')
    expect(review.textContent).not.toContain('保留原文')
    expect(review.textContent).not.toContain('未执行')
  }
  const check = review.querySelector<HTMLInputElement>('input')!; check.checked = true; check.dispatchEvent(new Event('change'))
  await expect(f.view.prepareSave()).resolves.toEqual({ confirmedPreviewDigest: 'f'.repeat(64) })
  f.draft.undo(); await f.view.refresh()
  expect(review.hidden).toBe(true); expect(f.root.dataset.pdfPreview).toBe('false')
})
it('does not create operations for incomplete, invalid, canceled or stale placement', async () => {
  const f = await fixture(); f.open.click(); await vi.waitFor(() => expect(f.root.querySelector<HTMLDialogElement>('[aria-label="插入文字"]')!.open).toBe(true))
  await expect(f.view.prepareSave()).rejects.toThrow('配置')
  const dialog = f.root.querySelector<HTMLDialogElement>('[aria-label="插入文字"]')!
  dialog.querySelector<HTMLTextAreaElement>('textarea')!.value = 'bad\u0000line'
  dialog.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click()
  expect(dialog.open).toBe(true); expect(f.draft.operations).toEqual([])
  dialog.close(); await configure(f); f.view.setSaving(true); await place(f)
  expect(f.draft.operations).toEqual([]); f.view.setSaving(false)
  await configure(f); f.draft.setOperations([{ kind: 'rotatePage', pageId: f.pageId, delta: 90 }]); await f.view.refresh(); await place(f)
  expect(f.draft.operations).toEqual([{ kind: 'rotatePage', pageId: f.pageId, delta: 90 }])
})
it('forced command dispatch cannot bypass readonly, capability, saving or existing draft guards', async () => {
  for (const [editable, capability] of [[false, true], [true, false], [true, true]]) {
    const f = await fixture(editable, capability)
    if (editable && capability) f.view.setSaving(true)
    f.open.dispatchEvent(new MouseEvent('click')); await Promise.resolve()
    expect(f.root.querySelector<HTMLDialogElement>('[aria-label="插入文字"]')?.open ?? false).toBe(false)
    expect(f.draft.operations).toEqual([])
  }
  const f = await fixture(); f.draft.setOperations([{ kind: 'rotatePage', pageId: f.pageId, delta: 90 }]); await f.view.refresh()
  expect(f.open.disabled).toBe(true); f.open.dispatchEvent(new MouseEvent('click')); await Promise.resolve()
  expect(f.root.querySelector<HTMLDialogElement>('[aria-label="插入文字"]')!.open).toBe(false)
})
it('requires the PDF text feature flag despite an engine insertion capability', async () => {
  const f = await fixture(true, true, false, false)
  expect(f.open.disabled).toBe(true)
  f.open.dispatchEvent(new MouseEvent('click')); await Promise.resolve()
  expect(f.root.querySelector<HTMLDialogElement>('[aria-label="插入文字"]')!.open).toBe(false)
  expect(f.draft.operations).toEqual([])
})
it('rejects a forced attachment selection after staging an independent insertion', async () => {
  const f = await fixture(); await configure(f); await place(f)
  await vi.waitFor(() => expect(f.draft.operations).toHaveLength(1))
  const before = structuredClone(f.draft.operations)
  const input = f.root.querySelector<HTMLInputElement>('[aria-label="选择新增附件"]')!
  expect(input.disabled).toBe(true)
  Object.defineProperty(input, 'files', { configurable: true, value: [new File(['attachment'], 'notes.txt', { type: 'text/plain' })] })
  input.dispatchEvent(new Event('change'))
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(f.draft.operations).toEqual(before)
})

it('stages multiline font styles alignment and leading through the public insertion dialog', async () => {
 const f = await fixture(); f.open.click()
 const dialog=f.root.querySelector<HTMLDialogElement>('[aria-label="插入文字"]')!
 await vi.waitFor(()=>expect(dialog.open).toBe(true))
 dialog.querySelector<HTMLTextAreaElement>('[aria-label="插入文字内容"]')!.value='First\n\nSecond'
 dialog.querySelector<HTMLSelectElement>('[aria-label="插入文字字体"]')!.value='times'
 dialog.querySelector<HTMLInputElement>('[aria-label="插入文字粗体"]')!.checked=true
 dialog.querySelector<HTMLInputElement>('[aria-label="插入文字斜体"]')!.checked=true
 dialog.querySelector<HTMLSelectElement>('[aria-label="插入文字对齐"]')!.value='right'
 dialog.querySelector<HTMLInputElement>('[aria-label="插入文字行距"]')!.value='21'
 dialog.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click()
 await place(f)
 await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1))
 expect(f.draft.operations[0]).toMatchObject({kind:'insertText',text:'First\n\nSecond',font:'times',bold:true,italic:true,align:'right',lineLeading:21,origin:[100,200]})
 await expect(f.view.prepareSave()).rejects.toThrow('请核对实际 PDF 预览')
})
it('public commands permit consecutive text inserts and exact management while isolating other mutations',async()=>{
 const f=await fixture();await configure(f,'First');await place(f)
 await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1))
 expect(f.open.disabled).toBe(false)
 await configure(f,'Second');await place(f);await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(2))
 const manage=f.root.querySelector<HTMLButtonElement>('[data-pdf-pending-text-manage]')!
 expect(manage.disabled).toBe(false);manage.click()
 await vi.waitFor(()=>expect(f.root.querySelector<HTMLDialogElement>('[aria-label="管理插入文字"]')?.open).toBe(true))
 f.root.querySelectorAll<HTMLButtonElement>('[data-pdf-pending-text-edit]')[1]!.click()
 const dialog=f.root.querySelector<HTMLDialogElement>('[aria-label="编辑待保存文字"]')!
 expect(dialog.open).toBe(true);dialog.querySelector<HTMLTextAreaElement>('textarea')!.value='Updated second'
 dialog.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click()
 await vi.waitFor(()=>expect(f.draft.operations.map(operation=>operation.text)).toEqual(['First','Updated second']))
 const rotate=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.page.rotateRight"]')!
 expect(rotate.disabled).toBe(true);rotate.dispatchEvent(new MouseEvent('click'));await Promise.resolve()
 expect(f.draft.operations).toHaveLength(2)
})
it('full text operation budget still permits editing and deletion through host commands',async()=>{
 const f=await fixture();await configure(f);await place(f);await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1))
 f.draft.setOperations(Array.from({length:500},()=>f.draft.operations[0]!));await f.view.refresh()
 expect(f.open.disabled).toBe(true)
 const manage=f.root.querySelector<HTMLButtonElement>('[data-pdf-pending-text-manage]')!
 expect(manage.disabled).toBe(false);manage.click()
 await vi.waitFor(()=>expect(f.root.querySelector<HTMLDialogElement>('[aria-label="管理插入文字"]')?.open).toBe(true))
 f.root.querySelector<HTMLButtonElement>('[data-pdf-pending-text-delete]')!.click()
 await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(499))
})
it.each(['insert-first','replace-first'])('public text commands stage both directions without losing existing operations: %s',async order=>{
 const f=await fixture()
 if(order==='insert-first'){await configure(f,'Added');await place(f);await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1))}
 const edit=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.edit.editText"]')!
 expect(edit.disabled).toBe(false);edit.click();await Promise.resolve()
 expect(f.root.querySelector<HTMLSelectElement>('[aria-label="待修改文字对象"]')!.disabled).toBe(false)
 const replacement=f.root.querySelector<HTMLTextAreaElement>('[aria-label="替换后的文字"]')!;replacement.value='Updated original'
 const stage=[...f.root.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='加入文字修改')!;expect(stage.disabled).toBe(false);stage.click()
 await vi.waitFor(()=>expect(f.draft.operations.some(op=>op.kind==='replaceText')).toBe(true))
 if(order==='replace-first'){await configure(f,'Added');await place(f)}
 await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(2))
 expect(f.draft.operations.map(op=>op.kind)).toEqual(order==='insert-first'?['insertText','replaceText']:['replaceText','insertText'])
 expect(f.draft.operations.find(op=>op.kind==='replaceText')).toEqual(expect.objectContaining({newText:'Updated original',sourceSha256:f.sourceSha256}))
 const rotate=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.page.rotateRight"]')!;expect(rotate.disabled).toBe(true)
})
it('the Edit-tab text entry is usable alongside the Home entry in an insertion draft',async()=>{
 const f=await fixture();await configure(f,'Added');await place(f);await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1))
 const editButtons=[...f.root.querySelectorAll<HTMLButtonElement>('button.pdf-tool')].filter(button=>button.querySelector('span')?.textContent==='原位改字')
 expect(editButtons).toHaveLength(2)
 for(const button of editButtons){expect(button.disabled).toBe(false);button.click();await Promise.resolve();expect(f.root.dataset.pdfMode).toBe('text')}
})

it('public source move controls retain the original object identity and isolate rewrite and insert',async()=>{
 const f=await fixture();f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.edit.editText"]')!.click();await Promise.resolve()
 const x=f.root.querySelector<HTMLInputElement>('[aria-label="原文位移 X"]')!,y=f.root.querySelector<HTMLInputElement>('[aria-label="原文位移 Y"]')!,submit=f.root.querySelector<HTMLButtonElement>('[data-pdf-move-text]')!
 x.value='35';y.value='-25';submit.click();await vi.waitFor(()=>expect(f.draft.operations).toEqual([{kind:'moveText',sourceSha256:f.sourceSha256,pageId:f.pageId,objectId:'original',expectedTextSha256:'b'.repeat(64),delta:[35,-25]}]))
 expect(f.open.disabled).toBe(true);expect(f.root.querySelector<HTMLTextAreaElement>('[aria-label="替换后的文字"]')!.disabled).toBe(true)
 expect(f.root.querySelector<HTMLSelectElement>('[aria-label="待修改文字对象"]')!.disabled).toBe(false)
 x.value='10';y.value='20';submit.click();await vi.waitFor(()=>expect(f.draft.operations[0]!.delta).toEqual([10,20]))
 await expect(f.view.prepareSave()).rejects.toThrow('请核对实际 PDF 预览')
 expect(f.root.dataset.pdfPreview).toBe('true')
})
