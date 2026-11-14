import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft,type NativeOperation} from './native-draft'
import {createPdfEditorView,type PdfEditorHandle} from './pdf-main'
import type {EditorShell} from './shell'
import type {createNativeApi,NativeContextResponse} from './native-api'
import {samplePaperColor} from './pdf-paper-sample'

const renderState=vi.hoisted(()=>({hold:false,resolvers:[] as (()=>void)[],observerCallbacks:[] as ((entries:{target:Element;isIntersecting:boolean}[])=>void)[]}))

vi.mock('./source-validation',()=>({bytesSha256:async()=> 'a'.repeat(64)}))
vi.mock('./pdf-paper-sample',()=>({samplePaperColor:vi.fn(()=> '#fff2cc')}))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs',()=>{
 class Viewport {
  viewBox:number[];width:number;height:number;scale:number;rotation:number
  constructor({viewBox=[0,0,400,500],scale=1,rotation=0}:{viewBox?:number[];scale?:number;rotation?:number}){this.viewBox=viewBox;this.scale=scale;this.rotation=rotation;this.width=((rotation%180)?viewBox[3]!-viewBox[1]!:viewBox[2]!-viewBox[0]!)*scale;this.height=((rotation%180)?viewBox[2]!-viewBox[0]!:viewBox[3]!-viewBox[1]!)*scale}
  convertToViewportPoint(x:number,y:number){const [x0,y0,x1,y1]=this.viewBox;if(this.rotation===90)return [(y-y0)*this.scale,(x-x0)*this.scale];if(this.rotation===180)return [(x1-x)*this.scale,(y-y0)*this.scale];if(this.rotation===270)return [(y1-y)*this.scale,(x1-x)*this.scale];return [(x-x0)*this.scale,(y1-y)*this.scale]}
  convertToPdfPoint(x:number,y:number){const [x0,y0,x1,y1]=this.viewBox;if(this.rotation===90)return [x0+y/this.scale,y0+x/this.scale];if(this.rotation===180)return [x1-x/this.scale,y0+y/this.scale];if(this.rotation===270)return [x0+(y1-y/this.scale),y0+(x1-x/this.scale)];return [x0+x/this.scale,y0+(y1-y/this.scale)]}
 }
 const pages=[{view:[10,20,390,480],rotate:90},{view:[0,0,400,500],rotate:0}].map((page,index)=>({...page,userUnit:1,getViewport:({scale=1,rotation=page.rotate}:{scale?:number;rotation?:number})=>new Viewport({viewBox:page.view,scale,rotation}),getTextContent:async()=>({items:[{str:'Original',dir:'ltr',transform:index===0?[14,0,0,14,20,150]:[14,0,0,14,30,350],width:56,height:14,fontName:'f1'}],styles:{f1:{fontFamily:'Helvetica',ascent:.9,descent:-.1}}}),getAnnotations:async()=>[],render:()=>{if(!renderState.hold)return {promise:Promise.resolve(),cancel:vi.fn()};let resolve!:()=>void;const promise=new Promise<void>(next=>{resolve=next});renderState.resolvers.push(resolve);return {promise,cancel:()=>resolve()}}}))
 const source={numPages:2,getPage:async(index:number)=>pages[index-1],getMetadata:async()=>({info:{}}),getOutline:async()=>[],destroy:async()=>{}}
 return {AnnotationMode:{ENABLE:1},GlobalWorkerOptions:{},TextLayer:class{},getDocument:()=>({promise:Promise.resolve(source),destroy:async()=>{}})}
})

it('projects a validated replacement with an ink cover and source text geometry, then removes both in actual preview',async()=>{
 const root=document.createElement('div');document.body.append(root)
 const sourceSha256='a'.repeat(64),pageIds=[0,1].map(index=>`sha256:${sourceSha256}:page:${index}`),objectId='text-0',expectedTextSha256='b'.repeat(64)
 const identity={documentId:'replace-text-thumb',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},draft=new NativeDraft(identity,localStorage)
 draft.setOperations([{kind:'replaceText',sourceSha256,pageId:pageIds[1],objectId,expectedTextSha256,newText:'Replacement'}])
 const pages=pageIds.map((pageId,index)=>({...({rotation:index===1?0:90}),pageId,index,mediaBox:{x:0,y:0,width:400,height:500},cropBox:{x:0,y:0,width:400,height:500},textObjects:index===1?[{objectId,expectedTextSha256,text:'Original',rect:[30,346,86,360] as [number,number,number,number],fontSize:14,fontName:'Helvetica',fontSha256:null,fillColor:[20,40,60] as [number,number,number]}]:[]}))
 const api={file:async()=>new Uint8Array([1,2]).buffer,preview:async()=>({sourceSha256,previewDigest:'b'.repeat(64),appliedOperationIndices:[0],skippedOperations:[],model:{sourceSha256,pageCount:2,pages,capabilities:{}}}),previewFile:async()=>new Uint8Array([3,4]).buffer} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:'replace-text-thumb',revision:1,format:'pdf',scope:identity.scope,sourceFile:{sha256:sourceSha256,path:'/workspace/source.pdf'}},editingEnabled:true,pdfTextEnabled:true} as NativeContextResponse
 const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
 const thumbnail=root.querySelector<HTMLButtonElement>(`.pdf-thumbnail[data-page-id="${pageIds[1]}"]`)!
 expect(thumbnail.querySelector('[data-pdf-text-edit-thumb-cover="text-0"]')).not.toBeNull()
 const overlay=thumbnail.querySelector<HTMLElement>('[data-pdf-text-edit-thumb="text-0"]')!
 expect(overlay.textContent).toBe('Replacement');expect(overlay.style.background).toBe('rgb(255, 255, 255)');expect(overlay.style.pointerEvents).toBe('none')
 expect(root.querySelector(`.pdf-thumbnail[data-page-id="${pageIds[0]}"] [data-pdf-text-edit-thumb]`)).toBeNull()
 ;[...root.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='校验当前修改')!.click();await vi.waitFor(()=>expect(root.dataset.pdfPreview).toBe('true'))
 expect(root.querySelector('[data-pdf-text-edit-thumb]')).toBeNull();expect(root.querySelector('[data-pdf-text-edit-thumb-cover]')).toBeNull()
})

it('retains paper sampling readiness across thumbnail hide and show while a render is cancelled',async()=>{
 const root=document.createElement('div');document.body.append(root)
 const sourceSha256='a'.repeat(64),pageIds=[0,1].map(index=>`sha256:${sourceSha256}:page:${index}`),objectId='text-0',expectedTextSha256='b'.repeat(64),identity={documentId:'replace-text-thumb-life',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},draft=new NativeDraft(identity,localStorage)
 draft.setOperations([{kind:'replaceText',pageId:pageIds[1],objectId,expectedTextSha256,newText:'Replacement'}])
 const pages=pageIds.map((pageId,index)=>({...({rotation:index===1?0:90}),pageId,index,mediaBox:{x:0,y:0,width:400,height:500},cropBox:{x:0,y:0,width:400,height:500},textObjects:index===1?[{objectId,expectedTextSha256,text:'Original',rect:[30,346,86,360] as [number,number,number,number],fontSize:14,fontName:'Helvetica',fontSha256:null,fillColor:[255,255,255] as [number,number,number]}]:[]}))
 const api={file:async()=>new Uint8Array([1,2]).buffer,preview:async()=>({sourceSha256,previewDigest:'b'.repeat(64),appliedOperationIndices:[0],skippedOperations:[],model:{sourceSha256,pageCount:2,pages,capabilities:{}}})} as unknown as ReturnType<typeof createNativeApi>,context={context:{documentId:identity.documentId,revision:1,format:'pdf',scope:identity.scope,sourceFile:{sha256:sourceSha256,path:'/workspace/source.pdf'}},editingEnabled:true,pdfTextEnabled:true} as NativeContextResponse
 renderState.hold=true
 const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
 const canvas=root.querySelector<HTMLCanvasElement>(`.pdf-thumbnail[data-page-id="${pageIds[1]}"] canvas`)!,thumbnailObserver=renderState.observerCallbacks[0]
 expect(thumbnailObserver).toBeDefined();thumbnailObserver!([{target:canvas,isIntersecting:true}]);thumbnailObserver!([{target:canvas,isIntersecting:false}]);thumbnailObserver!([{target:canvas,isIntersecting:true}]);renderState.hold=false;for(const resolve of renderState.resolvers.splice(0))resolve()
 await vi.waitFor(()=>expect(samplePaperColor).toHaveBeenCalled());const thumbnail=root.querySelector<HTMLButtonElement>(`.pdf-thumbnail[data-page-id="${pageIds[1]}"]`)!;expect(thumbnail.querySelector<HTMLElement>('[data-pdf-text-edit-thumb]')?.style.background).toBe('rgb(255, 242, 204)');expect(thumbnail.querySelector<HTMLElement>('[data-pdf-text-edit-thumb-cover]')?.style.background).toBe('rgb(255, 242, 204)');expect(thumbnail.querySelector<HTMLElement>('[data-pdf-text-edit-thumb]')?.style.color).toBe('rgb(17, 17, 17)');expect(root.querySelector('.pdf-editor-message')?.textContent).not.toMatch(/is not defined|PDF 操作失败/)
})

const views:PdfEditorHandle[]=[]
beforeEach(()=>{localStorage.clear();renderState.hold=false;renderState.resolvers.length=0;renderState.observerCallbacks.length=0;vi.mocked(samplePaperColor).mockClear();vi.stubGlobal('IntersectionObserver',class{constructor(callback:(entries:{target:Element;isIntersecting:boolean}[])=>void){renderState.observerCallbacks.push(callback)}observe(){}disconnect(){}unobserve(){}});vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({} as CanvasRenderingContext2D)})
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})

it('projects only the matching pending fill over its reordered, rotated thumbnail without intercepting input',async()=>{
 const root=document.createElement('div');document.body.append(root)
 const sourceSha256='a'.repeat(64),pageIds=[0,1].map(index=>`sha256:${sourceSha256}:page:${index}`)
 const identity={documentId:'static-thumb',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}
 const draft=new NativeDraft(identity,localStorage),fill={kind:'setStaticFill',sourceSha256,pageId:pageIds[0],id:'thumb-fill',fillKind:'check',rect:[30,50,70,90],image:'iVBORw0KGgoAAA'}
 const markups=['highlight','underline','squiggly','strikeout'].map((markupType,index)=>({kind:'addMarkup',pageId:pageIds[0],markupType,quads:[[30,90,70,90,30,50,70,50]],color:[index/3,0,1-index/3]})) as NativeOperation[]
 const drawing:NativeOperation={kind:'addDrawing',pageId:pageIds[0],shape:'rect',rect:[100,100,150,140],color:[1,0,0],width:2}
 const drawingImage:NativeOperation={kind:'addDrawing',pageId:pageIds[0],shape:'image',rect:[150,100,190,140],image:'iVBORw0KGgoIMAGE',color:[1,0,0],width:2}
 draft.setOperations([fill,...markups,drawing,drawingImage,{kind:'reorderPages',pageIds:[pageIds[1]!,pageIds[0]!]}])
 const pages=pageIds.map((pageId,index)=>({pageId,index,rotation:index===0?90:0,mediaBox:{x:0,y:0,width:400,height:500},cropBox:{x:10,y:20,width:380,height:460}}))
 const api={file:async()=>new Uint8Array([1,2]).buffer,preview:async()=>({sourceSha256,previewDigest:'b'.repeat(64),appliedOperationIndices:[],skippedOperations:[],model:{sourceSha256,pageCount:2,pages,capabilities:{}}})} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:'static-thumb',revision:1,format:'pdf',scope:identity.scope,sourceFile:{sha256:sourceSha256,path:'/workspace/source.pdf'}},editingEnabled:true,pdfTextEnabled:false} as NativeContextResponse
 const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
 const thumbnails=[...root.querySelectorAll<HTMLButtonElement>('.pdf-thumbnail')]
 expect(thumbnails.map(button=>button.dataset.pageId)).toEqual([pageIds[1],pageIds[0]])
 expect(thumbnails[0]!.querySelector('[data-pdf-static-fill-thumb]')).toBeNull()
 const image=thumbnails[1]!.querySelector<HTMLImageElement>('[data-pdf-static-fill-thumb="thumb-fill"]')!
 expect(image.getAttribute('src')).toBe('data:image/png;base64,iVBORw0KGgoAAA')
 expect(image.style.pointerEvents).toBe('none')
 expect(image.style.left).toBe(`${30/460*100}%`);expect(image.style.top).toBe(`${20/380*100}%`)
 expect(image.parentElement?.classList.contains('pdf-thumbnail-page')).toBe(true)
 const markupOverlays=[...thumbnails[1]!.querySelectorAll<HTMLElement>('[data-pdf-markup-thumb]')]
 expect(markupOverlays.map(overlay=>overlay.dataset.pdfMarkupThumb)).toEqual(['highlight','underline','squiggly','strikeout'])
 expect(markupOverlays[0]!.style.left).toBe(`${30/460*100}%`);expect(markupOverlays[0]!.style.top).toBe(`${20/380*100}%`)
 expect(markupOverlays.every(overlay=>overlay.style.pointerEvents==='none')).toBe(true)
 const drawingSvg=thumbnails[1]!.querySelector<SVGSVGElement>('[data-pdf-drawing-thumb]')!
 expect(drawingSvg.style.pointerEvents).toBe('none')
 const drawnRect=drawingSvg.querySelector<SVGRectElement>('[data-pdf-drawing="rect"]')!
 expect([drawnRect.getAttribute('x'),drawnRect.getAttribute('y'),drawnRect.getAttribute('width'),drawnRect.getAttribute('height')]).toEqual(['80','90','40','50'])
 expect(drawingSvg.querySelector('image')?.getAttribute('href')).toBe('data:image/png;base64,iVBORw0KGgoIMAGE')
})

it('projects reordered pending stamp images by page identity and removes the overlay in the actual PDF preview',async()=>{
 const root=document.createElement('div');document.body.append(root)
 const sourceSha256='a'.repeat(64),pageIds=[0,1].map(index=>`sha256:${sourceSha256}:page:${index}`)
 const identity={documentId:'stamp-thumb',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}
 const draft=new NativeDraft(identity,localStorage),images=['iVBORw0KGgoAAA','iVBORw0KGgoBBB']
 const stamps={kind:'setStamps',watermark:{text:'draft'},headerFooter:null,images,stamps:[{pageId:pageIds[0],image:0,rect:[30,50,70,90],opacity:.35},{pageId:pageIds[1],image:1,rect:[30,50,70,90]}]}
 draft.setOperations([{kind:'reorderPages',pageIds:[pageIds[1]!,pageIds[0]!]},stamps])
 const pages=pageIds.map((pageId,index)=>({pageId,index,rotation:index===0?90:0,mediaBox:{x:0,y:0,width:400,height:500},cropBox:{x:10,y:20,width:380,height:460}}))
 const api={file:async()=>new Uint8Array([1,2]).buffer,preview:async()=>({sourceSha256,previewDigest:'b'.repeat(64),appliedOperationIndices:[1],skippedOperations:[],model:{sourceSha256,pageCount:2,pages,capabilities:{}}}),previewFile:async()=>new Uint8Array([3,4]).buffer} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:'stamp-thumb',revision:1,format:'pdf',scope:identity.scope,sourceFile:{sha256:sourceSha256,path:'/workspace/source.pdf'}},editingEnabled:true,pdfTextEnabled:false} as NativeContextResponse
 const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
 const thumbnails=[...root.querySelectorAll<HTMLButtonElement>('.pdf-thumbnail')]
 expect(thumbnails.map(button=>button.dataset.pageId)).toEqual([pageIds[1],pageIds[0]])
 expect(thumbnails[0]!.querySelector<HTMLImageElement>('[data-pdf-stamp-thumb]')!.src).toContain(images[1])
 expect(thumbnails[1]!.querySelector<HTMLImageElement>('[data-pdf-stamp-thumb]')!.src).toContain(images[0])
 expect(thumbnails[1]!.querySelector<HTMLImageElement>('[data-pdf-stamp-thumb]')!.style.opacity).toBe('0.35')
 ;[...root.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='校验当前修改')!.click()
 await vi.waitFor(()=>expect(root.dataset.pdfPreview).toBe('true'))
 expect(root.querySelector('[data-pdf-stamp-thumb]')).toBeNull()
})

it('projects source-bound pending inserted text through a rotated thumbnail and removes it for the actual PDF preview',async()=>{
 const root=document.createElement('div');document.body.append(root)
 const sourceSha256='a'.repeat(64),pageIds=[0,1].map(index=>`sha256:${sourceSha256}:page:${index}`)
 const identity={documentId:'text-thumb',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}
 const draft=new NativeDraft(identity,localStorage),insert={kind:'insertText',sourceSha256,pageId:pageIds[0],origin:[30,40],text:'待保存文字\n第二行',fontSize:14,color:[.2,.4,.6],align:'center',font:'times',bold:true,italic:true,lineLeading:18}
 draft.setOperations([insert])
 const pages=pageIds.map((pageId,index)=>({pageId,index,rotation:index===0?90:0,mediaBox:{x:0,y:0,width:400,height:500},cropBox:{x:10,y:20,width:380,height:460}}))
 const api={file:async()=>new Uint8Array([1,2]).buffer,preview:async()=>({sourceSha256,previewDigest:'b'.repeat(64),appliedOperationIndices:[0],skippedOperations:[],model:{sourceSha256,pageCount:2,pages,capabilities:{insertText:true}}}),previewFile:async()=>new Uint8Array([3,4]).buffer} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:'text-thumb',revision:1,format:'pdf',scope:identity.scope,sourceFile:{sha256:sourceSha256,path:'/workspace/source.pdf'}},editingEnabled:true,pdfTextEnabled:true} as NativeContextResponse
 const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
 const thumbnail=root.querySelector<HTMLButtonElement>(`.pdf-thumbnail[data-page-id="${pageIds[0]}"]`)!
 const overlay=thumbnail.querySelector<HTMLElement>('[data-pdf-static-text-thumb]')!
 expect(overlay.textContent).toBe(insert.text)
 expect(overlay.dataset.pdfStaticTextThumb).toBe(pageIds[0])
 expect(overlay.style.left).toBe(`${20/460*100}%`)
 expect(overlay.style.top).toBe(`${6/380*100}%`)
 expect(overlay.style.pointerEvents).toBe('none')
 expect(overlay.style.textAlign).toBe('center')
 expect(overlay.style.fontSize).toMatch(/cqw$/)
 expect(overlay.style.fontFamily).toContain('Times New Roman')
 expect(overlay.style.fontWeight).toBe('700')
 expect(root.querySelector(`[data-pdf-static-text-thumb="${pageIds[1]}"]`)).toBeNull()
 ;[...root.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='校验当前修改')!.click()
 await vi.waitFor(()=>expect(root.dataset.pdfPreview).toBe('true'))
 expect(root.querySelector('[data-pdf-static-text-thumb]')).toBeNull()
})

