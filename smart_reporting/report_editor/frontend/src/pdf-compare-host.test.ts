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
 const api={file:async()=>new Uint8Array([1,2]).buffer,preview:async()=>({sourceSha256:sha,model:{sourceSha256:sha,pages:[0,1,2].map(index=>({pageId:`sha256:${sha}:page:${index}`,textObjects:[{objectId:'text-0',text:'Original',rect:[10,10,100,20],expectedTextSha256:'b'.repeat(64),fontSize:12,fontName:'Arial',fontSha256:null}]}))}})} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:identity.documentId,revision:1,format:'pdf',scope:identity.scope,sourceFile:{path:'source.pdf',size:2,sha256:sha}},editingEnabled:true,pdfTextEnabled:true} as NativeContextResponse
 const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
 return{root,draft,view}
}
it('loads before source model initialization and warns before comparison when text is edited outside the staged operations',async()=>{
 const f=await fixture()
 expect(f.root.querySelectorAll('.pdf-page')).toHaveLength(3)
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.edit.editText"]')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector<HTMLTextAreaElement>('.pdf-text-editor textarea')!.value).toBe('Original'))
 const replacement=f.root.querySelector<HTMLTextAreaElement>('.pdf-text-editor textarea')!
 replacement.value='Unsaved local text';replacement.dispatchEvent(new Event('input',{bubbles:true}))
 expect(f.draft.operations).toEqual([])
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.navigation.compare"]')!.click()
 await Promise.resolve();await Promise.resolve()
 const input=f.root.querySelector<HTMLInputElement>('.pdf-compare-sidebar input[type=file]')!,clicked=vi.spyOn(input,'click')
 f.root.querySelector<HTMLButtonElement>('.pdf-compare-pick')!.click()
 expect(f.root.querySelector('.pdf-compare-notice')!.textContent).toContain('先保存')
 expect(clicked).not.toHaveBeenCalled();expect(f.draft.operations).toEqual([])
})
