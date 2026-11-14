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
async function fixture() {
 const root=document.body.appendChild(document.createElement('div')),sourceSha256='a'.repeat(64),pageId=`sha256:${sourceSha256}:page:0`
 const identity={documentId:'link-desktop',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}
 const draft=new NativeDraft(identity,localStorage)
 const api={file:async()=>new Uint8Array([1,2]).buffer,preview:async()=>({sourceSha256,model:{sourceSha256,pages:[{pageId,notesReadSafe:true}]}})} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:identity.documentId,revision:1,format:'pdf',scope:identity.scope,sourceFile:{sha256:sourceSha256}},editingEnabled:true} as NativeContextResponse
 const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
 const entry=root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.edit.objects.editLink"]')!
 const dialog=root.querySelector<HTMLDialogElement>('.pdf-link-dialog')!,url=dialog.querySelector<HTMLInputElement>('[aria-label="链接网址"]')!,page=dialog.querySelector<HTMLInputElement>('[aria-label="链接页码"]')!
 const apply=[...dialog.querySelectorAll('button')].find(n=>n.textContent==='确定')!
 const draw=async()=>{
  root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="edit"]')!.click()
  if(entry.getAttribute('aria-pressed')!=='true')entry.click()
  await vi.waitFor(()=>expect(root.querySelector<HTMLElement>('.pdf-page-content')?.onpointerup).toBeTypeOf('function'))
  const holder=root.querySelector<HTMLElement>('.pdf-page-content')!
  vi.spyOn(holder,'getBoundingClientRect').mockReturnValue({left:0,top:0,width:300,height:400} as DOMRect)
  holder.dispatchEvent(new MouseEvent('pointerdown',{bubbles:true,button:0,clientX:30,clientY:40}))
  holder.dispatchEvent(new MouseEvent('pointerup',{bubbles:true,button:0,clientX:130,clientY:70}))
  await vi.waitFor(()=>expect(dialog.open).toBe(true))
 }
 await draw();return {root,draft,view,entry,dialog,url,page,apply,draw,pageId}
}
it('link window exposes desktop regions, an accessible hint and the current page range',async()=>{
 const f=await fixture()
 expect(f.dialog.querySelector('header h3')?.textContent).toBe('添加链接')
 expect(f.dialog.querySelector('footer .pdf-link-actions')).not.toBeNull()
 expect(f.dialog.querySelector('[role=region][aria-label="链接设置说明"]')?.getAttribute('tabindex')).toBe('0')
 expect(f.dialog.querySelector('[role=alert]')?.getAttribute('aria-label')).toBe('链接校验提示')
 expect(document.activeElement).toBe(f.url);expect(f.page.getAttribute('aria-describedby')).toBeTruthy();expect(f.draft.operations).toEqual([])
})
it.each(['title','cancel','escape'])('link %s closes, drops the pending area and returns to its Ribbon entry',async action=>{
 const f=await fixture();f.url.value='https://cancel.invalid'
 if(action==='escape'){
  const event=new Event('cancel',{cancelable:true});f.dialog.dispatchEvent(event);expect(event.defaultPrevented).toBe(true)
 }else{
  const close=action==='title'?f.dialog.querySelector<HTMLButtonElement>('[aria-label="关闭添加链接"]'):[...f.dialog.querySelectorAll('button')].find(n=>n.textContent==='取消')
  expect(close).toBeTruthy();close!.focus();close!.click()
 }
 expect(f.dialog.open).toBe(false);expect(document.activeElement).toBe(f.entry)
 f.apply.dispatchEvent(new MouseEvent('click'));expect(f.draft.operations).toEqual([])
 await f.draw();expect(f.url.value).toBe('');expect(f.page.value).toBe('')
})
it('invalid link keeps its area and input, focuses the reason, then accepts a corrected URL',async()=>{
 const f=await fixture();f.url.value='javascript:alert(1)';f.apply.click()
 const error=f.dialog.querySelector<HTMLElement>('[role=alert]')!
 expect(error.textContent).toContain('http/https/mailto');expect(document.activeElement).toBe(error)
 expect(f.url.value).toBe('javascript:alert(1)');expect(f.dialog.open).toBe(true);expect(f.draft.operations).toEqual([])
 f.url.value='www.example.com/report';f.apply.click()
 await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1))
 expect(f.draft.operations[0]).toMatchObject({kind:'addDrawing',shape:'link',pageId:f.pageId,url:'https://www.example.com/report',rect:[30,330,130,360]})
 expect(f.dialog.open).toBe(false)
})
it('page and URL inputs remain mutually exclusive and commit one page target',async()=>{
 const f=await fixture();f.url.value='https://example.com';f.page.value='1';f.page.dispatchEvent(new Event('input'));expect(f.url.value).toBe('')
 f.url.value='mailto:review@example.com';f.url.dispatchEvent(new Event('input'));expect(f.page.value).toBe('')
 f.page.value='1';f.page.dispatchEvent(new Event('input'));f.apply.click()
 await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1));expect(f.draft.operations[0]).toMatchObject({kind:'addDrawing',shape:'link',destPage:1});expect(f.draft.operations[0].url).toBeUndefined()
})
it.each(['saving','changed'])('pending link refuses a %s host and preserves the current draft',async reason=>{
 const f=await fixture();f.url.value='https://example.com'
 if(reason==='saving')f.view.setSaving(true)
 else f.draft.setOperations([{kind:'rotatePage',pageId:f.pageId,delta:90}])
 const before=structuredClone(f.draft.operations);f.apply.dispatchEvent(new MouseEvent('click'))
 expect(f.dialog.open).toBe(true);expect(f.dialog.querySelector('[role=alert]')?.textContent).toContain('草稿已变化')
 expect(f.draft.operations).toEqual(before)
})
