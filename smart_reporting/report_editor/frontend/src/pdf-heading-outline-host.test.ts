import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {createPdfEditorView,type PdfEditorHandle} from './pdf-main'
import type {EditorShell} from './shell'
import type {createNativeApi,NativeContextResponse} from './native-api'
import type {ResolvedPdfOutlineItem} from './pdf-view-ribbon'

const reading=vi.hoisted(()=>({cancelled:undefined as (()=>boolean)|undefined,resolve:undefined as ((value:{items:ResolvedPdfOutlineItem[];generated:boolean}|null)=>void)|undefined}))
vi.mock('./source-validation',()=>({bytesSha256:async()=>'a'.repeat(64)}))
vi.mock('./pdf-heading-outline',()=>({readPdfNavigationOutline:(_document:unknown,cancelled:()=>boolean)=>{reading.cancelled=cancelled;return new Promise(resolve=>{reading.resolve=resolve})}}))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs',()=>{
 class Viewport{
  width:number;height:number;viewBox=[0,0,300,400];userUnit=1;rotation=0;rawDims={pageWidth:300,pageHeight:400,pageX:0,pageY:0}
  constructor(public scale=1){this.width=300*scale;this.height=400*scale}
  clone(){return new Viewport(this.scale)}
  convertToViewportPoint(x:number,y:number){return[x*this.scale,(400-y)*this.scale]}
 }
 const page={view:[0,0,300,400],rotate:0,userUnit:1,getViewport:({scale}:{scale:number})=>new Viewport(scale),getTextContent:async()=>({items:[]}),streamTextContent:()=>({}),getAnnotations:async()=>[],render:()=>({promise:Promise.resolve(),cancel(){}})}
 const pdf={numPages:3,getPage:async()=>page,getMetadata:async()=>({info:{}})}
 return{AnnotationMode:{ENABLE:1},GlobalWorkerOptions:{},TextLayer:class{render=async()=>{};cancel(){}},getDocument:()=>({promise:Promise.resolve(pdf),destroy:async()=>{}})}
})
const views:PdfEditorHandle[]=[]
beforeEach(()=>{
 reading.cancelled=reading.resolve=undefined;localStorage.clear();vi.stubGlobal('IntersectionObserver',undefined)
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({} as CanvasRenderingContext2D)
 Object.defineProperty(HTMLElement.prototype,'scrollIntoView',{configurable:true,value(){}})
 Object.defineProperty(HTMLElement.prototype,'scrollTo',{configurable:true,value(){}})
})
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})
async function fixture(){
 const root=document.body.appendChild(document.createElement('div')),sha='a'.repeat(64)
 const identity={documentId:'heading-host',revision:1,sourceSha256:sha,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'}}
 const draft=new NativeDraft(identity,localStorage)
 const api={file:async()=>new Uint8Array([1,2]).buffer} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:identity.documentId,revision:1,format:'pdf',scope:identity.scope,sourceFile:{path:'source.pdf',size:2,sha256:sha}},editingEnabled:false} as NativeContextResponse
 const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
 return{root,draft,view}
}
it('renders pages while headings are pending, then navigates a read-only inferred result without a draft edit',async()=>{
 const f=await fixture();expect(f.root.querySelectorAll('.pdf-page')).toHaveLength(3)
 expect(f.root.querySelector('[data-pdf-heading-status]')?.getAttribute('data-state')).toBe('loading')
 expect(reading.cancelled?.()).toBe(false)
 reading.resolve!({items:[{title:'Chapter',depth:0,pageIndex:1}],generated:true})
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-outline-link')?.textContent).toBe('Chapter'))
 const edit=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.outline.edit"]')!
 expect(edit.disabled).toBe(true);expect(edit.title).toContain('未写入文档书签')
 f.root.querySelector<HTMLButtonElement>('.pdf-outline-link')!.click()
 expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(`sha256:${'a'.repeat(64)}:page:1`)
 expect(f.draft.operations).toEqual([])
 await f.view.refresh();expect(f.root.querySelector('.pdf-outline-link')?.textContent).toBe('Chapter');expect(f.draft.operations).toEqual([])
})
it('cancels the heading scan on host disposal and ignores its late result',async()=>{
 const f=await fixture();expect(reading.cancelled?.()).toBe(false)
 f.view.dispose();views.pop();expect(reading.cancelled?.()).toBe(true)
 reading.resolve!({items:[{title:'Late heading',depth:0,pageIndex:2}],generated:true})
 await Promise.resolve();await Promise.resolve()
 expect(f.root.childElementCount).toBe(0);expect(f.draft.operations).toEqual([])
})
