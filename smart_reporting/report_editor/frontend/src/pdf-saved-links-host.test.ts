import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NativeDraft } from './native-draft'
import { createPdfEditorView, type PdfEditorHandle } from './pdf-main'
import type { EditorShell } from './shell'
import type { createNativeApi, NativeContextResponse } from './native-api'
import {pdfRibbonLabel} from './pdf-ribbon-locales'

const linkFixture=vi.hoisted(()=>({annotations:[] as Record<string,unknown>[],readAnnotations:undefined as (()=>Promise<Record<string,unknown>[]>)|undefined,destination:null as unknown[]|null,resolveDestination:undefined as ((name:string)=>Promise<unknown[]|null>)|undefined}))
vi.mock('./source-validation', () => ({ bytesSha256: async () => 'a'.repeat(64) }))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', async () => {
  const {AnnotationLayer,AnnotationType}=await vi.importActual<typeof import('pdfjs-dist/legacy/build/pdf.mjs')>('pdfjs-dist/legacy/build/pdf.mjs')
  class Viewport {
    width: number; height: number; viewBox: number[]; scale:number; userUnit=1; rotation=0; rawDims={pageWidth:300,pageHeight:400,pageX:0,pageY:0}
    clone(options:{scale?:number;dontFlip?:boolean}={}){return new Viewport({scale:this.scale,viewBox:this.viewBox,...options})}
    constructor({ scale = 1, viewBox = [0, 0, 300, 400] }: { scale?: number; viewBox?: number[] }) { this.scale=scale;this.viewBox = viewBox; this.width = 300 * scale; this.height = 400 * scale }
    convertToPdfPoint(x: number, y: number) { return [x * 300 / this.width, 400 - y * 400 / this.height] }
    convertToViewportPoint(x: number, y: number) { return [x * this.width / 300, (400-y) * this.height / 400] }
  }
  const page = { view: [0, 0, 300, 400], rotate: 0, userUnit: 1, getViewport: (options: { scale: number }) => new Viewport(options), getTextContent: async () => ({ items: [] }), streamTextContent: () => ({}), getAnnotations: async () => linkFixture.readAnnotations?linkFixture.readAnnotations():linkFixture.annotations, render: () => ({ promise: Promise.resolve(), cancel() {} }) }
  const pdf = { numPages: 3, getPage: async () => page, getMetadata: async () => ({ info: {} }), getOutline: async () => [], getDestination: async(name:string)=>linkFixture.resolveDestination?linkFixture.resolveDestination(name):linkFixture.destination, getPageIndex: async()=>2, destroy: async () => {} }
  return { AnnotationLayer, AnnotationType, AnnotationMode: { ENABLE: 1 }, GlobalWorkerOptions: {}, TextLayer: class { render = async () => {}; cancel() {} }, getDocument: () => ({ promise: Promise.resolve(pdf), destroy: async () => {} }) }
})
const views: PdfEditorHandle[] = []
beforeEach(() => {
  linkFixture.annotations=[];linkFixture.readAnnotations=undefined;linkFixture.destination=null;linkFixture.resolveDestination=undefined; localStorage.clear(); vi.stubGlobal('IntersectionObserver', undefined)
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value() {} })
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value(this:HTMLElement,options:ScrollToOptions) { this.scrollLeft=options.left??this.scrollLeft;this.scrollTop=options.top??this.scrollTop } })
})
afterEach(() => { views.splice(0).forEach(view => view.dispose()); document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
const annotation=(id:string,target:Record<string,unknown>)=>({id,annotationType:2,subtype:'Link',rect:[30,330,130,360],rotation:0,borderStyle:{width:0,style:1,horizontalCornerRadius:0,verticalCornerRadius:0},...target})
async function fixture(annotations=[annotation('web',{url:'https://example.com/report'})],editingEnabled=true,waitForLinks=true){
 linkFixture.annotations=annotations
 const root=document.body.appendChild(document.createElement('div')),sourceSha256='a'.repeat(64)
 const identity={documentId:'saved-links',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}
 const draft=new NativeDraft(identity,localStorage)
 const api={file:async()=>new Uint8Array([1,2]).buffer,preview:async()=>({sourceSha256,model:{sourceSha256,pages:[0,1,2].map(index=>({pageId:`sha256:${sourceSha256}:page:${index}`,notesReadSafe:true}))}})} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:identity.documentId,revision:1,format:'pdf',scope:identity.scope,sourceFile:{path:'saved-links.pdf',size:2,sha256:sourceSha256}},editingEnabled} as NativeContextResponse
 const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
 if(waitForLinks)await vi.waitFor(()=>expect(root.querySelectorAll('.pdf-saved-links')).toHaveLength(3))
 return {root,draft,view,first:root.querySelector<HTMLElement>('.pdf-saved-links')!}
}
it.each([true,false])('saved links use native annotation geometry with isolated external browsing (editable=%s)',async editable=>{
 const f=await fixture([annotation('web',{url:'https://example.com/report'}),annotation('mail',{url:'mailto:review@example.com'})],editable)
 const links=[...f.first.querySelectorAll('a')]
 expect(links).toHaveLength(2);expect(f.first.classList.contains('annotationLayer')).toBe(true)
 expect(links[0].href).toBe('https://example.com/report');expect(links[0].target).toBe('_blank');expect(links[0].rel).toContain('noopener');expect(links[0].rel).toContain('noreferrer')
 expect(links.every(a=>!!a.getAttribute('aria-label'))).toBe(true)
 expect(links[0].parentElement?.style.left).toBe('10%');expect(links[0].parentElement?.style.top).toBe('10%')
 expect(f.draft.operations).toEqual([])
})
it.each([{destination:[{num:3,gen:0}]},{destination:[0]},{destination:['chapter']}])('saved page destination %j navigates without editing and focuses the page label',async({destination})=>{
 linkFixture.destination=[{num:3,gen:0}]
 const dest=destination[0]==='chapter'?'chapter':destination
 const f=await fixture([annotation('page',{dest})]);f.first.querySelector('a')!.click()
 const index=destination[0]===0?0:2
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(`sha256:${'a'.repeat(64)}:page:${index}`))
 expect(document.activeElement).toBe(f.root.querySelectorAll('.pdf-page-label')[index]);expect(f.draft.operations).toEqual([])
})
it('embedded script, launch, hidden and malformed URL actions do not become clickable links',async()=>{
 const f=await fixture([annotation('safe',{url:'https://example.com'}),annotation('script',{url:'javascript:alert(1)'}),annotation('data',{url:'data:text/html,unsafe'}),annotation('file',{url:'file:///secret'}),annotation('blank',{url:'https://example.com',hidden:true}),annotation('launch',{action:'Launch'}),annotation('malformed',{url:'https:// bad host'})])
 expect(f.first.querySelectorAll('a')).toHaveLength(1);expect(f.draft.operations).toEqual([])
})
it('drawing mode and saving suspend links, and selection mode restores them',async()=>{
 const f=await fixture();const before=structuredClone(f.draft.operations)
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.edit.objects.editLink"]')!.click()
 await vi.waitFor(()=>expect(f.first.inert).toBe(true));expect(f.first.querySelector('a')!.getAttribute('tabindex')).toBe('-1')
  ;[...f.root.querySelectorAll('button')].find(n=>n.textContent===pdfRibbonLabel('选择文字'))!.click()
 await vi.waitFor(()=>expect(f.first.inert).toBe(false));expect(f.first.querySelector('a')!.getAttribute('tabindex')).toBe('0')
 f.view.setSaving(true);expect(f.first.inert).toBe(true);f.view.setSaving(false);expect(f.first.inert).toBe(false);expect(f.draft.operations).toEqual(before)
})
it('focused links reveal their complete region without scrolling disabled or disposed layers',async()=>{
 const f=await fixture(),anchor=f.first.querySelector('a')!,scroll=vi.spyOn(anchor,'scrollIntoView')
 anchor.focus();expect(scroll).toHaveBeenCalledExactlyOnceWith({block:'nearest',inline:'nearest'})
 f.view.setSaving(true);anchor.dispatchEvent(new FocusEvent('focusin',{bubbles:true}));expect(scroll).toHaveBeenCalledTimes(1)
 f.view.setSaving(false);f.view.dispose();anchor.dispatchEvent(new FocusEvent('focusin',{bubbles:true}));expect(scroll).toHaveBeenCalledTimes(1);expect(f.draft.operations).toEqual([])
})
it('a late named destination cannot navigate after the host changes',async()=>{
 let resolve!:(value:unknown[])=>void
 linkFixture.resolveDestination=()=>new Promise(done=>{resolve=done})
 const f=await fixture([annotation('page',{dest:'chapter'})]);f.first.querySelector('a')!.click()
 await vi.waitFor(()=>expect(resolve).toBeTypeOf('function'));f.view.setSaving(true);resolve([{num:3,gen:0}]);await new Promise(done=>setTimeout(done,10))
 expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(`sha256:${'a'.repeat(64)}:page:0`);expect(f.draft.operations).toEqual([])
})
it('slow annotation reads do not block page drawing handlers, and late results are discarded after disposal',async()=>{
 let release!:(value:Record<string,unknown>[])=>void
 const pending=new Promise<Record<string,unknown>[]>(done=>{release=done});linkFixture.readAnnotations=()=>pending
 const f=await fixture(undefined,true,false)
 await vi.waitFor(()=>expect(f.root.querySelector<HTMLElement>('.pdf-page-content')?.onpointerup).toBeTypeOf('function'))
 expect(f.root.querySelector('.pdf-saved-links')).toBeNull();f.view.dispose();release([annotation('late',{url:'https://example.com'})]);await new Promise(done=>setTimeout(done,20));expect(f.root.children).toHaveLength(0);expect(f.draft.operations).toEqual([])
})
it('reordered pages retain source-bound destinations and navigation does not change the draft',async()=>{
 const f=await fixture([annotation('page',{dest:[{num:3,gen:0}]})]),ids=[2,1,0].map(index=>`sha256:${'a'.repeat(64)}:page:${index}`)
 f.draft.setOperations([{kind:'reorderPages',pageIds:ids}]);await f.view.refresh()
 await vi.waitFor(()=>expect(f.root.querySelectorAll('.pdf-saved-links')).toHaveLength(3))
 f.root.querySelector<HTMLAnchorElement>(`.pdf-page[data-page-id="${ids[2]}"] .pdf-saved-links a`)!.click()
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(ids[0]))
 expect(f.draft.operations).toEqual([{kind:'reorderPages',pageIds:ids}]);expect(document.activeElement).toBe(f.root.querySelector('.pdf-page-label'))
})
it('deleted target pages produce a specific reading warning without changing the draft',async()=>{
 const f=await fixture([annotation('page',{dest:[{num:3,gen:0}]})]),operation={kind:'deletePage',pageId:`sha256:${'a'.repeat(64)}:page:2`}
 f.draft.setOperations([operation]);await f.view.refresh()
 await vi.waitFor(()=>expect(f.root.querySelectorAll('.pdf-saved-links')).toHaveLength(2));f.root.querySelector<HTMLAnchorElement>('.pdf-saved-links a')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-editor-message')?.textContent).toContain('链接目标页不存在或已从当前草稿移除'))
 expect(f.draft.operations).toEqual([operation])
})
it('late annotation results after refresh mount only the current page generation',async()=>{
 let release!:(value:Record<string,unknown>[])=>void
 const pending=new Promise<Record<string,unknown>[]>(done=>{release=done});linkFixture.readAnnotations=()=>pending
 const f=await fixture(undefined,true,false);await f.view.refresh();release([annotation('current',{url:'https://example.com'})])
 await vi.waitFor(()=>expect(f.root.querySelectorAll('.pdf-saved-links')).toHaveLength(3));expect(f.draft.operations).toEqual([])
})
it('XYZ links apply destination zoom and focus the reading viewport without editing',async()=>{
 const f=await fixture([annotation('xyz',{dest:[2,{name:'XYZ'},80,230,2]})]);f.first.querySelector('a')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector<HTMLSelectElement>('.pdf-zoom')!.value).toBe('2'))
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(`sha256:${'a'.repeat(64)}:page:2`))
 expect(document.activeElement).toBe(f.root.querySelector('.pdf-document-pages'));expect(f.draft.operations).toEqual([])
})
it('a later link supersedes a pending named destination',async()=>{
 let release!:(value:unknown[])=>void
 linkFixture.resolveDestination=()=>new Promise(done=>{release=done})
 const f=await fixture([annotation('slow',{dest:'slow'}),annotation('fast',{dest:[1]})]);const links=f.first.querySelectorAll('a');links[0].click()
 await vi.waitFor(()=>expect(release).toBeTypeOf('function'));links[1].click()
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(`sha256:${'a'.repeat(64)}:page:1`));release([2])
 await new Promise(done=>setTimeout(done,20));expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(`sha256:${'a'.repeat(64)}:page:1`);expect(f.draft.operations).toEqual([])
})
it('invalid destination parameters warn without changing the reading page or zoom',async()=>{
 const f=await fixture([annotation('invalid',{dest:[2,{name:'XYZ'},80,230,-2]})]);f.first.querySelector('a')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-editor-message')?.textContent).toContain('链接目标参数无效'))
 expect(f.root.querySelector<HTMLSelectElement>('.pdf-zoom')!.value).toBe('1');expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(`sha256:${'a'.repeat(64)}:page:0`);expect(f.draft.operations).toEqual([])
})
it('saving cancels a pending destination even if saving finishes before it resolves',async()=>{
 let release!:(value:unknown[])=>void;linkFixture.resolveDestination=()=>new Promise(done=>{release=done})
 const f=await fixture([annotation('slow',{dest:'slow'})]);f.first.querySelector('a')!.click();await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
 f.view.setSaving(true);f.view.setSaving(false);release([2]);await new Promise(done=>setTimeout(done,20))
 expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(`sha256:${'a'.repeat(64)}:page:0`);expect(f.draft.operations).toEqual([])
})
it.each(['wheel','keydown','click'])('manual %s cancels a pending link instead of overriding subsequent reading',async event=>{
 let release!:(value:unknown[])=>void;linkFixture.resolveDestination=()=>new Promise(done=>{release=done})
 const f=await fixture([annotation('slow',{dest:'slow'})]);f.first.querySelector('a')!.click();await vi.waitFor(()=>expect(release).toBeTypeOf('function'))
 f.root.dispatchEvent(new Event(event,{bubbles:true}));release([2]);await new Promise(done=>setTimeout(done,20))
 expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(`sha256:${'a'.repeat(64)}:page:0`);expect(f.draft.operations).toEqual([])
})
