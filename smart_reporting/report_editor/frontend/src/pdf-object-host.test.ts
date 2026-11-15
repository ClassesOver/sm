import {act} from 'react'
import {webcrypto} from 'node:crypto'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft,type NativeOperation} from './native-draft'
import {createPdfEditorView,type PdfEditorHandle} from './pdf-main'
import type {EditorShell} from './shell'
import type {createNativeApi,NativeContextResponse,NativeSaveResponse} from './native-api'
import {pdfReadingKey} from './pdf-reading-state'
import {saveViewState} from './genoffice-pdf-reading-state'
type TestAnnotation = { id:string;annotationType:number;subtype:string;contentsObj:{str:string};inReplyTo?:string;fieldType?:string;fieldName?:string;fieldValue?:string;required?:boolean;readOnly?:boolean;rect?:number[] }
const pdfMock=vi.hoisted(()=>({pages:1,detach:false,text:'',annotations:[] as TestAnnotation[],printed:[] as number[],widgetPages:undefined as TestAnnotation[][]|undefined}))
vi.mock('./source-validation',()=>({bytesSha256:async(bytes:Uint8Array)=>bytes[0]===91?'b'.repeat(64):'a'.repeat(64)}))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs',()=>{
 const page={view:[0,0,300,400],rotate:0,userUnit:1,getViewport:({scale}:{scale:number})=>({width:300*scale,height:400*scale,viewBox:[0,0,300,400],convertToPdfPoint:(x:number,y:number)=>[x,y],convertToViewportPoint:(x:number,y:number)=>[x,y]}),getTextContent:async()=>({items:pdfMock.text ? [{str:pdfMock.text,transform:[10,0,0,10,30,100],width:pdfMock.text.length*5,height:10}] : []}),streamTextContent:()=>({}),getAnnotations:async()=>pdfMock.annotations,render:()=>({promise:Promise.resolve(),cancel:vi.fn()})}
 const pdf={get numPages(){return pdfMock.pages},getPage:async(index:number)=>pdfMock.widgetPages?{...page,getAnnotations:async()=>pdfMock.widgetPages?.[index-1]??[]}:page,getMetadata:async()=>({info:{}}),getOutline:async()=>[{title:'章节',dest:[{num:1}],items:[]}],getPageIndex:async()=>0,getAttachments:async()=>new Map([['stored',{filename:'keep.txt',description:'保留附件'}]]),getAttachmentContent:async()=>new Uint8Array([1,2,3]),destroy:async()=>{}}
 return {AnnotationMode:{ENABLE:1},GlobalWorkerOptions:{},TextLayer:class{render(){return Promise.resolve()}},getDocument:({data}:{data:Uint8Array<ArrayBuffer>})=>{const fresh=data[0]===91; if(pdfMock.detach)structuredClone(data.buffer,{transfer:[data.buffer]});return {promise:Promise.resolve(fresh?{...pdf,numPages:2,getPage:async(index:number)=>({...page,rotate:index===1?90:0,render:()=>{pdfMock.printed.push(index);return {promise:Promise.resolve(),cancel:vi.fn()}}})}:pdf),destroy:async()=>{}}}}
})
const dialogDescriptors={showModal:Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype,'showModal'),close:Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype,'close')}
const views:PdfEditorHandle[]=[],sourceSha256='a'.repeat(64),pageId='sha256:'+sourceSha256+':page:0'
const widget={fieldName:'existing',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),pageIndex:0,rect:[20,20,120,44] as [number,number,number,number],removable:true,removalReason:null,required:true}
const image={pageId,pageIndex:0,rect:[20,60,120,160] as [number,number,number,number],imageId:'d'.repeat(64),expectedImageSha256:'e'.repeat(64),aboveText:false,editable:true}
function operation(kind:string):NativeOperation{
 if(kind==='createFormField')return {kind,sourceSha256,pageId,fieldName:'customer',fieldKind:'text',rect:[30,180,150,204],required:true}
 if(kind==='editFormFieldRequired')return {kind,sourceSha256,fieldName:widget.fieldName,widgetId:widget.widgetId,widgetIdentity:widget.widgetIdentity,expectedWidgetSha256:widget.expectedWidgetSha256,required:false}
 return {kind:'transformExistingImage',sourceSha256,pageId,imageId:image.imageId,expectedImageSha256:image.expectedImageSha256,rect:[30,70,130,170]}
}
beforeEach(()=>{localStorage.clear();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}unobserve(){}});vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({} as CanvasRenderingContext2D);Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:vi.fn(function(this:HTMLDialogElement){this.open=true})});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:vi.fn(function(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))})})})
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals();for(const name of ["showModal","close"] as const){const descriptor=dialogDescriptors[name];if(descriptor)Object.defineProperty(HTMLDialogElement.prototype,name,descriptor);else Reflect.deleteProperty(HTMLDialogElement.prototype,name)}})
async function fixture(options:{restored?:NativeOperation;capabilities?:Record<string,boolean>;editingEnabled?:boolean;pages?:number;detachSource?:boolean;sourceSize?:number;attachments?:boolean;staticFills?:boolean;digitalSignatures?:boolean;text?:string;savedThread?:boolean;exportPages?:number;requiredField?:boolean;navigationFields?:boolean;widgetNavigation?:boolean;signatureTargets?:boolean;flushForFileOperation?:()=>Promise<NativeSaveResponse|undefined>}={}){
 pdfMock.pages=options.exportPages??options.pages??1;pdfMock.detach=options.detachSource??false;pdfMock.text=options.text??'';pdfMock.printed=[]
 const notes=options.savedThread?[
  { annotationId:'4'.repeat(64), expectedAnnotationSha256:'5'.repeat(64), sourceRef:'10R', contents:'root', editable:true, removable:false, replyable:true, removalReason:'关联回复' },
  { annotationId:'6'.repeat(64), expectedAnnotationSha256:'7'.repeat(64), sourceRef:'11R', contents:'reply', editable:true, removable:true, parentAnnotationId:'4'.repeat(64), removalReason:null },
 ]:[]
 pdfMock.annotations=notes.map(note=>({ id:note.sourceRef, annotationType:1, subtype:'Text', contentsObj:{str:note.contents}, ...(note.parentAnnotationId?{inReplyTo:'10R'}:{}) }))
 if(options.requiredField)pdfMock.annotations.push({id:'20R',annotationType:20,subtype:'Widget',contentsObj:{str:''},fieldType:'Tx',fieldName:'existing',fieldValue:'',required:true,rect:[20,20,120,44]})
 const widgetAnnotation=(id:string,fieldName:string):TestAnnotation=>({id,annotationType:20,subtype:'Widget',contentsObj:{str:''},fieldType:'Tx',fieldName,rect:[20,20,110,44]})
 pdfMock.widgetPages=options.widgetNavigation?[[widgetAnnotation('30R','existing')],[widgetAnnotation('31R','secondary')],[widgetAnnotation('32R','existing')]]:undefined
 const root=document.createElement('div');document.body.append(root)
 const identity={documentId:'pdf-object-host',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}
 const seed=new NativeDraft(identity,localStorage);if(options.restored)seed.setOperations([options.restored]);const draft=new NativeDraft(identity,localStorage)
 const signatureFields=options.signatureTargets?['First signature','Second signature'].map((name,pageIndex)=>({
  fieldId:(pageIndex?'7':'6').repeat(64),expectedFieldSha256:(pageIndex?'9':'8').repeat(64),name,signed:false,visuallySigned:false,bindable:true,reason:null,
  widgets:[{pageIndex,rect:[30,200,150,230]}],
 })): []
 const model={sourceSha256,pages:Array.from({length:options.exportPages??1},(_,index)=>({pageId:'sha256:'+sourceSha256+':page:'+index,index,rotation:0,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:0,y:0,width:300,height:400},notesReadSafe:true,notes})),formFields:[{name:'existing',kind:'text',value:options.requiredField?'':'Alice',editable:true,fieldId:'f'.repeat(64),expectedFieldSha256:'1'.repeat(64)},...(options.navigationFields?[{name:'locked',kind:'text',value:'Locked',editable:false,fieldId:'2'.repeat(64),expectedFieldSha256:'3'.repeat(64)},{name:'secondary',kind:'text',value:'Second',editable:true,fieldId:'4'.repeat(64),expectedFieldSha256:'5'.repeat(64)}]:[]),...signatureFields.map(field=>({...field,kind:'signature',value:null,editable:false}))],signatureFields,formDesignWidgets:[widget],existingImages:[image],capabilities:{createFormField:true,editFormFieldRequired:true,editExistingImage:true,...options.capabilities}}
 const staticModel=options.staticFills?{staticFormFills:[{id:'saved-fill',kind:'text',pageIndex:0,rect:[30,100,150,124],text:'已保存填写',fontSize:14,color:'#111111',align:'left',editable:true,expectedImageSha256:'9'.repeat(64)}]}:{}
 const attachmentModel=options.attachments?{attachmentsEditable:true,attachments:[{key:'stored',name:'keep.txt',description:'保留附件',size:3,contentSha256:'b'.repeat(64),attachmentId:'c'.repeat(64),expectedAttachmentSha256:'d'.repeat(64)}]}:{}
 const api={exportImages:vi.fn(async()=>{throw new Error('test request observed')}),file:async()=>new Uint8Array(options.sourceSize??2).buffer,preview:vi.fn(async()=>({sourceSha256,model:{...model,...attachmentModel,...staticModel,...(options.digitalSignatures?{digitalSignatures:[],signatureVerification:{scope:"basic-integrity-only",trustPolicy:"none",readable:true,issues:[],revocationChecked:false,timestampsVerified:false}}:{})}})),previewFile:vi.fn(async()=>new Uint8Array([3,4]).buffer)} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:identity.documentId,revision:1,format:'pdf',scope:identity.scope,sourceFile:{sha256:sourceSha256,path:'source.pdf'}},editingEnabled:options.editingEnabled??true,pdfTextEnabled:false,capabilities:{}} as NativeContextResponse
 const saveButton=document.createElement('button')
 const create=async()=>{const view=await createPdfEditorView({editor:root,save:saveButton} as unknown as EditorShell,{api,context,draft,flushForFileOperation:options.flushForFileOperation});views.push(view);return view}
 return {root,draft,create,api,saveButton}
}
it('toggles the source Find bar and preserves the query and selected result after closing', async () => {
 const f=await fixture({text:'cat dog cat'});await f.create()
 const find=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.search.toggle"]')!
 const bar=f.root.querySelector<HTMLElement>('.pdf-find-bar')!
 const input=bar.querySelector<HTMLInputElement>('.pdf-search')!
 const count=bar.querySelector('.pdf-search-count')!
 const key=(target:EventTarget,key:string,extra:KeyboardEventInit={})=>target.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,...extra}))
 expect(bar.hidden).toBe(true)
 find.click()
 await vi.waitFor(()=>expect(document.activeElement).toBe(input))
 expect(find.getAttribute('aria-expanded')).toBe('true')
 input.value='cat';input.dispatchEvent(new Event('input',{bubbles:true}))
 await vi.waitFor(()=>expect(count.textContent).toBe('1 / 2'))
 key(input,'Enter');expect(count.textContent).toBe('2 / 2')
 bar.querySelector<HTMLButtonElement>('[aria-label="关闭搜索"]')!.click()
 await vi.waitFor(()=>expect(bar.hidden).toBe(true))
 expect(f.root.querySelector('.pdf-search-match')).toBeNull()
 expect(input.value).toBe('cat')
 key(f.root,'f',{metaKey:true})
 expect(document.activeElement).toBe(input)
 expect(count.textContent).toBe('2 / 2')
 key(input,'Escape');expect(bar.hidden).toBe(true)
 expect(document.activeElement).toBe(f.root.querySelector('.pdf-document-pages'))
 expect(f.draft.operations).toEqual([])
})
it.each(['composition','legacy','handled'])('PDF页码与搜索保留受保护按键，不清草稿或移走焦点：%s',async protection=>{
 const f=await fixture();await f.create()
 const key=(node:HTMLElement,key:string,extra:KeyboardEventInit={})=>{const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0,...extra});if(protection==='handled')event.preventDefault();node.dispatchEvent(event);return event}
 const search=f.root.querySelector<HTMLInputElement>('.pdf-search')!;document.dispatchEvent(new KeyboardEvent('keydown',{key:'f',ctrlKey:true,cancelable:true}));search.value='尚未确认的查询';search.focus()
 for(const name of ['Enter','Escape']){const event=key(search,name);expect(search.value).toBe('尚未确认的查询');expect(document.activeElement).toBe(search);expect(event.defaultPrevented).toBe(protection==='handled')}
 const jump=f.root.querySelector<HTMLInputElement>('.pdf-view-page-input')!;jump.value='9';jump.focus();key(jump,'Enter');expect(jump.value).toBe('9');expect(document.activeElement).toBe(jump)
 const tab=f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="view"]')!;tab.focus();key(tab,'f',{ctrlKey:true});expect(document.activeElement).toBe(tab)
 jump.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));expect(jump.value).toBe('1');expect(f.draft.operations).toEqual([])
})
it('stages detected email from the Annotate ribbon and clears it through the normal controls', async () => {
 const f=await fixture({text:'Email sample@example.com'});await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="annotate"]')!.click()
 const find=f.root.querySelector<HTMLSelectElement>('[data-source-command-id="genoffice.pdf.annotate.drawTools.redactFind"]')!
 expect(find.disabled).toBe(false)
 expect([...find.options].map(option=>option.value)).toEqual(['','phone','email','credit-card','ssn','date','iban','all'])
 find.value='email';find.dispatchEvent(new Event('change',{bubbles:true}))
 await vi.waitFor(()=>expect(f.draft.operations).toEqual([{kind:'redact',pageId,rect:[59,97.5,151,110.5]}]))
 expect(f.root.textContent).not.toContain('sample@example.com')
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.annotate.drawTools.clearRedaction"]')!.click()
 await vi.waitFor(()=>expect(f.draft.operations).toEqual([]))
})
it('deletes a saved thread from its ribbon sidebar in one undo step', async () => {
 const f=await fixture({savedThread:true,capabilities:{notes:true,noteReplies:true,savedReplyEdits:true,savedNoteThreadRemoval:true}});await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="view"]')!.click()
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.navigation.comments"]')!.click()
 const findDelete=()=>[...f.root.querySelectorAll<HTMLButtonElement>('.pdf-comments-sidebar button')].find(button=>button.textContent==='删除批注线程')
 await vi.waitFor(()=>expect(findDelete()?.disabled).toBe(false))
 findDelete()!.click()
 await vi.waitFor(()=>expect(f.draft.operations.map(op=>op.annotationId)).toEqual(['6'.repeat(64),'4'.repeat(64)]))
 f.draft.undo()
 expect(f.draft.operations).toEqual([])
})
it.each([['Png','png'],['Jpg','jpeg']])('PNG/JPG ribbon command opens all saved pages at 150 DPI: %s', async (suffix,format) => {
 const f=await fixture({exportPages:3});await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.convert.exportImages'+suffix+'"]')!.click()
 const dialog=f.root.querySelector<HTMLDialogElement>('dialog[aria-label="导出 PDF 页面图片"]')!
 await vi.waitFor(()=>expect(dialog.open).toBe(true))
 expect(dialog.querySelector<HTMLInputElement>('[aria-label="导出图片页码"]')?.value).toBe('1-3')
 dialog.querySelector<HTMLButtonElement>('[data-pdf-image-export-apply]')!.click()
 await vi.waitFor(()=>expect(f.api.exportImages).toHaveBeenCalledWith({expectedSha256:sourceSha256,pages:[1,2,3],format,dpi:150}))
 expect(f.draft.operations).toEqual([])
})
it('extracts the visible range from the authorized saved revision after a draft page deletion', async () => {
 const events:string[]=[]
 const nextSha='b'.repeat(64)
 const flush=vi.fn(async ():Promise<NativeSaveResponse> => {
  events.push('save')
  return {documentId:'pdf-object-host',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pdf:{sha256:nextSha}},editor:{openUrl:'/reports/v1/native/open/extract-save'},validation:{ok:false,issues:[]}}
 })
 const f=await fixture({exportPages:3,restored:{kind:'deletePage',pageId:'sha256:'+sourceSha256+':page:1'},flushForFileOperation:flush});await f.create()
 vi.stubGlobal('fetch',async (input:string|URL,init?:RequestInit) => {
  const path=new URL(String(input),window.location.href).pathname
  events.push(path)
  if(path==='/reports/v1/native/open/extract-save')return new Response('authorized')
  if(path.endsWith('/2/api/context'))return Response.json({csrfToken:'new-csrf',context:{documentId:'pdf-object-host',revision:2,format:'pdf',sourceFile:{sha256:nextSha},scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}})
  if(path.endsWith('/2/api/extract-pages')){
   expect(JSON.parse(String(init?.body))).toMatchObject({expectedSha256:nextSha,pages:[2]})
   expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('new-csrf')
   return Response.json({validation:{ok:false,issues:[{code:'review',message:'仍需验收'}]},artifacts:{pdf:{downloadUrl:'/reports/v1/download/verified/pdf'}}})
  }
  throw Error('Unexpected path '+path)
 })
 const button=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.page.extract"]')!
 expect(button.disabled).toBe(false)
 button.click()
 const dialog=f.root.querySelector<HTMLDialogElement>('dialog[aria-label="提取页面"]')!
 await vi.waitFor(()=>expect(dialog.open).toBe(true))
 const pageRange=dialog.querySelector<HTMLInputElement>('input')!,apply=dialog.querySelector<HTMLButtonElement>('[data-pdf-extract-apply]')!
 pageRange.value='3';apply.click();expect(flush).not.toHaveBeenCalled()
 pageRange.value='2';apply.click()
 await vi.waitFor(()=>expect(dialog.querySelector('a')?.getAttribute('href')).toBe('/reports/v1/download/verified/pdf'))
 expect(dialog.textContent).toContain('仍需验收')
 expect(events).toEqual(['save','/reports/v1/native/open/extract-save','/reports/v1/native/pdf-object-host/2/api/context','/reports/v1/native/pdf-object-host/2/api/extract-pages'])
})
it('exports all remaining pages via the newly saved revision from the PNG ribbon', async () => {
 const events:string[]=[]
 const nextSha='b'.repeat(64)
 const flush=vi.fn(async ():Promise<NativeSaveResponse> => {
  events.push('save')
  return {documentId:'pdf-object-host',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pdf:{sha256:nextSha}},editor:{openUrl:'/reports/v1/native/open/image-save'},validation:{ok:false,issues:[]}}
 })
 const f=await fixture({exportPages:3,restored:{kind:'deletePage',pageId:'sha256:'+sourceSha256+':page:1'},flushForFileOperation:flush});await f.create()
 const rendered=vi.fn()
 vi.stubGlobal('fetch',async (input:string|URL,init?:RequestInit) => {
  const path=new URL(String(input),window.location.href).pathname
  events.push(path)
  if(path==='/reports/v1/native/open/image-save')return new Response('authorized')
  if(path.endsWith('/2/api/context'))return Response.json({csrfToken:'new-csrf',context:{documentId:'pdf-object-host',revision:2,format:'pdf',sourceFile:{sha256:nextSha},scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}})
  if(path.endsWith('/2/api/export-images')){
   expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('new-csrf')
   rendered(JSON.parse(String(init?.body)));return new Response(null,{status:503})
  }
  throw Error('Unexpected path '+path)
 })
 const button=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.convert.exportImagesPng"]')!
 expect(button.disabled).toBe(false);button.click()
 const dialog=f.root.querySelector<HTMLDialogElement>('dialog[aria-label="导出 PDF 页面图片"]')!
 await vi.waitFor(()=>expect(dialog.open).toBe(true))
 expect(dialog.querySelector<HTMLInputElement>('[aria-label="导出图片页码"]')?.value).toBe('1-2')
 dialog.querySelector<HTMLButtonElement>('[data-pdf-image-export-apply]')!.click()
 await vi.waitFor(()=>expect(rendered).toHaveBeenCalledWith({expectedSha256:nextSha,pages:[1,2],format:'png',dpi:150}))
 expect(f.api.exportImages).not.toHaveBeenCalled()
 expect(events).toEqual(['save','/reports/v1/native/open/image-save','/reports/v1/native/pdf-object-host/2/api/context','/reports/v1/native/pdf-object-host/2/api/export-images'])
})
it.each(['verified','stale'])('prints the verified saved page bytes after saving a draft: %s', async mode => {
 const events:string[]=[]
 const nextSha='b'.repeat(64)
 const flush=vi.fn(async ():Promise<NativeSaveResponse> => {
  events.push('save')
  return {documentId:'pdf-object-host',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pdf:{sha256:nextSha}},editor:{openUrl:'/reports/v1/native/open/print-save'},validation:{ok:false,issues:[]}}
 })
 const f=await fixture({exportPages:3,restored:{kind:'deletePage',pageId:'sha256:'+sourceSha256+':page:1'},flushForFileOperation:flush});await f.create()
 const print=vi.spyOn(window,'print').mockImplementation(()=>{})
 vi.stubGlobal('fetch',async (input:string|URL) => {
  const path=new URL(String(input),window.location.href).pathname
  events.push(path)
  if(path==='/reports/v1/native/open/print-save')return new Response('authorized')
  if(path.endsWith('/2/api/context'))return Response.json({csrfToken:'new-csrf',context:{documentId:'pdf-object-host',revision:2,format:'pdf',sourceFile:{sha256:nextSha},scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}})
  if(path.endsWith('/2/api/file'))return new Response(new Uint8Array([mode==='verified'?91:0]))
  throw Error('Unexpected path '+path)
 })
 const button=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.print.print"]')!
 expect(button.disabled).toBe(false);button.click()
 const dialog=f.root.querySelector<HTMLDialogElement>('dialog[aria-label="打印 PDF"]')!
 expect(dialog.open).toBe(true)
 dialog.querySelector<HTMLSelectElement>('[aria-label="打印页面子集"]')!.value='odd'
 dialog.querySelector<HTMLButtonElement>('[data-pdf-print-confirm]')!.click()
 if(mode==='verified'){
  await vi.waitFor(()=>expect(print).toHaveBeenCalledOnce())
  expect(pdfMock.printed).toEqual([1]);expect(f.root.querySelectorAll('.pdf-print-page')).toHaveLength(1)
  window.dispatchEvent(new Event('afterprint'))
 } else {
  await vi.waitFor(()=>expect(f.root.textContent).toContain('打印来源身份校验失败'))
  expect(print).not.toHaveBeenCalled();expect(pdfMock.printed).toEqual([])
 }
 expect(events).toEqual(['save','/reports/v1/native/open/print-save','/reports/v1/native/pdf-object-host/2/api/context','/reports/v1/native/pdf-object-host/2/api/file'])
})
it.each([['insertPdf','insert'],['replace','replace']])('binds external pages to the authorized post-save revision: %s', async (command,action) => {
 const events:string[]=[]
 const nextSha='b'.repeat(64)
 const flush=vi.fn(async ():Promise<NativeSaveResponse> => {
  events.push('save')
  return {documentId:'pdf-object-host',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pdf:{sha256:nextSha}},editor:{openUrl:'/reports/v1/native/open/external-save'},validation:{ok:false,issues:[]}}
 })
 const f=await fixture({exportPages:3,restored:{kind:'deletePage',pageId:'sha256:'+sourceSha256+':page:1'},flushForFileOperation:flush});await f.create()
 vi.stubGlobal('crypto',webcrypto)
 vi.stubGlobal('fetch',async (input:string|URL,init?:RequestInit) => {
  const path=new URL(String(input),window.location.href).pathname
  events.push(path)
  if(path==='/reports/v1/native/open/external-save')return new Response('authorized')
  if(path.endsWith('/2/api/context'))return Response.json({csrfToken:'new-csrf',context:{documentId:'pdf-object-host',revision:2,format:'pdf',sourceFile:{sha256:nextSha},scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}})
  if(path.endsWith('/2/api/external-pages')){
   expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('new-csrf')
   expect(JSON.parse(String(init?.body))).toMatchObject({expectedSha256:nextSha,action,...(action==='insert'?{afterPage:2}:{pages:[2]})})
   return Response.json({validation:{ok:false,issues:[{code:'review',message:'仍需验收'}]},artifacts:{pdf:{downloadUrl:'/reviews/external.pdf'}}})
  }
  throw Error('Unexpected path '+path)
 })
 const button=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.page.'+command+'"]')!
 expect(button.disabled).toBe(false);button.click()
 const dialog=f.root.querySelector<HTMLDialogElement>('dialog[aria-label="外部 PDF 页面"]')!
 await vi.waitFor(()=>expect(dialog.open).toBe(true))
 const upload=dialog.querySelector<HTMLInputElement>('input[type="file"]')!
 const content=new TextEncoder().encode('%PDF-fixture')
 const file=new File([content],'fixture.pdf')
 Object.defineProperty(file,'arrayBuffer',{value:async()=>content.buffer})
 Object.defineProperty(upload,'files',{value:[file]})
 dialog.querySelector<HTMLInputElement>(action==='insert'?'[aria-label="插入父 PDF 页后"]':'[aria-label="替换父 PDF 页码"]')!.value='2'
 dialog.querySelector<HTMLButtonElement>('[data-pdf-external-pages-apply]')!.click()
 await vi.waitFor(()=>expect(dialog.querySelector('a')?.getAttribute('href')).toBe('/reviews/external.pdf'))
 expect(dialog.textContent).toContain('仍需验收')
 expect(events).toEqual(['save','/reports/v1/native/open/external-save','/reports/v1/native/pdf-object-host/2/api/context','/reports/v1/native/pdf-object-host/2/api/external-pages'])
})
it('requires permanent redaction confirmation before writing and preserves downloads on failed review', async () => {
 const op:NativeOperation={kind:'redact',pageId,rect:[20,20,80,90]}
 const f=await fixture({restored:op}),view=await f.create()
 const {bindNativeSession}=await import('./native-session')
 const statusLabel=document.createElement('span')
 const shell={editor:f.root,save:f.saveButton,exportWord:document.createElement('button'),exportPdf:document.createElement('button'),retry:document.createElement('button'),status:document.createElement('div'),statusLabel} as unknown as EditorShell
 const marker=document.createElement('div');marker.className='report-meta';f.root.append(marker)
 const save=vi.fn(async ():Promise<NativeSaveResponse> => ({documentId:'pdf-object-host',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pdf:{downloadUrl:'/redacted.pdf'}},validation:{ok:false,issues:[{code:'review',message:'待复核'}]}}))
 const session=bindNativeSession(shell,{draft:f.draft,api:{save,export:save},format:'pdf',view})
 try {
  f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="annotate"]')!.click()
  f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.annotate.drawTools.applyRedaction"]')!.click()
  const confirm=()=>f.root.querySelector<HTMLDialogElement>('dialog[aria-label="确认应用涂黑"]')
  await vi.waitFor(()=>expect(confirm()?.open).toBe(true))
  expect(save).not.toHaveBeenCalled()
  confirm()!.querySelector<HTMLButtonElement>('[data-pdf-redaction-cancel]')!.click()
  await vi.waitFor(()=>expect(session.preparing).toBe(false))
  expect(f.draft.operations).toEqual([op]);expect(save).not.toHaveBeenCalled()
  f.saveButton.click()
  await vi.waitFor(()=>expect(confirm()?.open).toBe(true))
  confirm()!.querySelector<HTMLButtonElement>('[data-pdf-redaction-confirm]')!.click()
  await vi.waitFor(()=>expect(f.root.querySelector('.native-delivery a')?.getAttribute('href')).toBe(new URL('/redacted.pdf',window.location.origin).href))
  expect(save).toHaveBeenCalledOnce(); expect(save).toHaveBeenCalledWith(expect.objectContaining({operations:[op]}))
  expect(f.root.querySelector('.native-delivery')?.textContent).toContain('待复核')
 } finally { views.splice(views.indexOf(view),1); session.dispose() }
})
it('watermark settings expose both source tabs and current slider values without changing the draft',async()=>{
 const f=await fixture();await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="edit"]')!.click()
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.edit.objects.watermark"]')!.click()
 await vi.waitFor(()=>expect(document.querySelector('.pdf-stamp-source-dialog input[type=range]')).not.toBeNull())
 const dialog=document.querySelector<HTMLDialogElement>('.pdf-stamp-source-dialog')!
 expect(dialog.open).toBe(true)
 expect([...dialog.querySelectorAll('.pdf-sign-tab')].map(node=>node.textContent)).toEqual(['水印','页眉页脚'])
 for(const [label,value,text] of [['角度','-30','-30°'],['不透明度','45','45%'],['字号','12','12%']] as const){
  const range=dialog.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!
  expect(range).not.toBeNull();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(range,value);range.dispatchEvent(new Event('input',{bubbles:true}));range.dispatchEvent(new Event('change',{bubbles:true}))})
  expect(range.value).toBe(value)
  expect(range.closest('label')!.querySelector('em')?.textContent).toBe(text)
 }
 expect(f.draft.operations).toEqual([])
})
it('watermark cancel returns to its Ribbon entry and discards only unsubmitted values',async()=>{
 const f=await fixture();await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="edit"]')!.click()
 const entry=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.edit.objects.watermark"]')!;entry.focus();entry.click()
 await vi.waitFor(()=>expect(document.querySelector('.pdf-stamp-source-dialog input.pdf-modal-input')).not.toBeNull())
 const dialog=document.querySelector<HTMLDialogElement>('.pdf-stamp-source-dialog')!,input=dialog.querySelector<HTMLInputElement>('input.pdf-modal-input')!
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'尚未提交的水印');input.dispatchEvent(new Event('input',{bubbles:true}))})
 expect(input.value).toBe('尚未提交的水印')
 const close=[...dialog.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='取消')!
 expect(close).not.toBeNull();close.focus();await act(async()=>close.click())
 expect(document.querySelector('.pdf-stamp-source-dialog')).toBeNull();expect(document.activeElement).toBe(entry);expect(f.draft.operations).toEqual([])
 entry.click();await vi.waitFor(()=>expect(document.querySelector<HTMLInputElement>('.pdf-stamp-source-dialog input.pdf-modal-input')?.value).toBe(''))
})
it.each(['createFormField','editFormFieldRequired','transformExistingImage'])('forced form change cannot mix setFormValue into exclusive %s draft',async kind=>{
 const f=await fixture(),view=await f.create(),op=operation(kind);f.draft.setOperations([op]);await view.refresh()
 const control=f.root.querySelector<HTMLInputElement>('.pdf-form-field input[aria-label="existing"]')!;expect(control.disabled).toBe(true);control.value='forced';control.dispatchEvent(new Event('change'))
 expect(f.draft.operations).toEqual([op])
})
it.each([['createFormField','createFormField'],['editFormFieldRequired','editFormFieldRequired'],['transformExistingImage','editExistingImage']])('restored %s requires current engine capability %s and retains original draft',async(kind,capability)=>{
 const op=operation(kind),f=await fixture({restored:op,capabilities:{[capability]:false}});await expect(f.create()).rejects.toThrow(/原草稿已保留/);expect(f.draft.operations).toEqual([op])
})
it('host passes actual source image census to its public edit image panel',async()=>{
 const f=await fixture();await f.create();const command=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.edit.objects.editImage"]')!;expect(command.disabled).toBe(false);command.click()
 const dialog=f.root.querySelector<HTMLDialogElement>('.pdf-existing-image-dialog')!;await vi.waitFor(()=>expect(dialog.open).toBe(true));expect(dialog.querySelector('select')!.options).toHaveLength(1);expect(dialog.querySelector<HTMLInputElement>('[aria-label="已有图像X"]')!.value).toBe('20')
})
it.each([
 ['createFormField',{sourceSha256:'0'.repeat(64)}],
 ['createFormField',{rect:[290,180,410,204]}],
 ['createFormField',{fieldName:'existing'}],
 ['editFormFieldRequired',{expectedWidgetSha256:'0'.repeat(64)}],
])('restored %s rejects stale source, geometry or widget identity without rewriting the draft',async(kind,patch)=>{
 const op={...operation(kind),...patch},f=await fixture({restored:op})
 await expect(f.create()).rejects.toThrow()
 expect(f.draft.operations).toEqual([op])
})

it('measurement disarms before recalibration and clears a pending calibration when another tool is selected', async () => {
 const observers:Array<{targets:Element[];callback:(entries:Array<{target:Element;isIntersecting:boolean}>)=>void}>=[]
 vi.stubGlobal('IntersectionObserver',class{
  targets:Element[]=[]
  constructor(readonly callback:(entries:Array<{target:Element;isIntersecting:boolean}>)=>void){observers.push(this)}
  observe(target:Element){this.targets.push(target)}disconnect(){}unobserve(){}
 })
 const f=await fixture();await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="annotate"]')!.click()
 const measure=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.annotate.drawTools.measure"]')!
 const rect=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.annotate.drawTools.rectangle"]')!
 async function draw(y:number){
  const card=f.root.querySelector<HTMLElement>('.pdf-page')!,page=card.querySelector<HTMLElement>('.pdf-page-content')!
  page.getBoundingClientRect=()=>new DOMRect(0,0,300,400)
  observers.find(item=>item.targets.includes(card))!.callback([{target:card,isIntersecting:true}])
  await vi.waitFor(()=>expect(typeof page.onpointerdown).toBe('function'))
  page.onpointerdown!(new MouseEvent('pointerdown',{clientX:40,clientY:y}) as PointerEvent)
  page.onpointerup!(new MouseEvent('pointerup',{clientX:140,clientY:y}) as PointerEvent)
 }
 const calibration = ()=>document.querySelector<HTMLDialogElement>('.pdf-measure-source-dialog')
 measure.click();await vi.waitFor(()=>expect(measure.getAttribute('aria-pressed')).toBe('true'));await draw(130)
 await vi.waitFor(()=>expect(calibration()?.querySelector('input[type=number]')).toBeTruthy())
 const input=calibration()!.querySelector<HTMLInputElement>('input[type=number]')!
 await act(async()=>{
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'2')
  input.dispatchEvent(new Event('input',{bubbles:true})); input.dispatchEvent(new Event('change',{bubbles:true}))
 })
 await act(async()=>calibration()!.querySelector<HTMLButtonElement>('.primary')!.click())
 await vi.waitFor(()=>expect(f.draft.operations.at(-1)?.label).toBe('2.00 m'))
 measure.click();await vi.waitFor(()=>expect(measure.getAttribute('aria-pressed')).toBe('false'))
 measure.click();await vi.waitFor(()=>expect(measure.getAttribute('aria-pressed')).toBe('true'));await draw(155)
 await vi.waitFor(()=>expect(calibration()?.open).toBe(true))
 await act(async()=>[...calibration()!.querySelectorAll('button')].find(button=>button.textContent==='取消')!.click())
 expect(f.draft.operations).toHaveLength(1)
 measure.click();await vi.waitFor(()=>expect(measure.getAttribute('aria-pressed')).toBe('false'))
 rect.click();await vi.waitFor(()=>expect(rect.getAttribute('aria-pressed')).toBe('true'))
 measure.click();await vi.waitFor(()=>expect(measure.getAttribute('aria-pressed')).toBe('true'));await draw(181)
 await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(2))
 expect(calibration()).toBeNull()
 expect(f.draft.operations.map(op=>op.label)).toEqual(['2.00 m','2.00 m'])
 measure.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))
 expect(measure.getAttribute('aria-pressed')).toBe('false')
})
it('measurement crop warning remains separate from applied operations and preserves the draft',async()=>{
 const f=await fixture(),view=await f.create()
 const op:NativeOperation={kind:'addDrawing',pageId,shape:'measure',from:[230,200],to:[290,200],label:'W'.repeat(64),color:[1,0,0],width:1}
 f.draft.setOperations([op])
 const current=await f.api.preview({expectedSha256:sourceSha256,operations:[op]})
 const message='第 1 页的测量标签可能超出可见页框而被裁切；标签和生成文件已保留，请核对实际预览。'
 vi.mocked(f.api.preview).mockResolvedValue({...current,previewDigest:'f'.repeat(64),appliedOperationIndices:[0],skippedOperations:[],reviewIssues:[{operationIndex:0,kind:'addDrawing',fieldName:'',code:'pdf_measure_label_crop_clipping',message}]})
 const button=[...f.root.querySelectorAll('button')].find(button=>button.textContent==='校验当前修改')!
 button.click()
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-review-issue')?.textContent).toContain(message))
 const panel=f.root.querySelector<HTMLElement>('.pdf-preview-review')!
 expect(panel.textContent).toContain('已执行：第 1 项')
 expect(panel.textContent).not.toContain('未执行，保留原文')
 expect(f.draft.operations).toEqual([op])
 expect(f.api.previewFile).toHaveBeenCalledWith(expect.objectContaining({operations:[op],expectedPreviewDigest:'f'.repeat(64)}),expect.any(AbortSignal))
 view.dispose()
})

const objectDialogs=[
 {kind:'note',title:'编辑便签正文',entry:'编辑便签'},
 {kind:'rect',title:'移动待保存绘图',entry:'移动所选绘图'},
 {kind:'image',title:'缩放待保存图像',entry:'缩放所选图像'},
]
it('pending drawing selection keeps keyboard focus on the selected record after refreshing the list',async()=>{
 const restored:NativeOperation={kind:'addDrawing',pageId,shape:'rect',rect:[40,60,100,140],color:[1,0,0],width:1.6}
 const f=await fixture({restored});await f.create()
 ;[...f.root.querySelectorAll('button')].find(button=>button.textContent==='待保存绘图')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector('[data-pdf-pending-drawing] button')).not.toBeNull())
 const select=f.root.querySelector<HTMLButtonElement>('[data-pdf-pending-drawing] button')!;select.focus();select.click()
 const selected=f.root.querySelector<HTMLButtonElement>('[data-pdf-pending-drawing] button[aria-pressed="true"]')!
 expect(selected).not.toBeNull();expect(document.activeElement).toBe(selected);expect(f.draft.operations).toEqual([restored])
})
it.each(['comments','attachments','thumbnails','outline'])('closing %s sidebar returns focus to its visible Ribbon entry',async kind=>{
 const f=await fixture();await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="view"]')!.click()
 const entry=f.root.querySelector<HTMLButtonElement>(`[data-source-command-id="genoffice.pdf.view.navigation.${kind}"]`)!
 const selector=kind==='comments'||kind==='attachments'?`.pdf-${kind}-sidebar`:`.pdf-${kind}`
 if(kind!=='thumbnails')entry.click();await vi.waitFor(()=>expect(f.root.querySelector<HTMLElement>(selector)!.hidden).toBe(false))
 const close=f.root.querySelector<HTMLButtonElement>(`${selector} header button:last-child`)!;expect(close).not.toBeNull();close.focus();close.click()
 expect(f.root.querySelector<HTMLElement>(selector)!.hidden).toBe(true)
 expect(document.activeElement).toBe(entry);expect(f.draft.operations).toEqual([])
})
it.each(['comments','attachments','thumbnails','outline'])('closing %s sidebar after changing Ribbon tab focuses the current tab',async kind=>{
 const f=await fixture();await f.create()
 if(kind!=='thumbnails')f.root.querySelector<HTMLButtonElement>(`[data-source-command-id="genoffice.pdf.view.navigation.${kind}"]`)!.click()
 const tab=f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="home"]')!;tab.click()
 const selector=kind==='comments'||kind==='attachments'?`.pdf-${kind}-sidebar`:`.pdf-${kind}`
 const close=f.root.querySelector<HTMLButtonElement>(`${selector} header button:last-child`)!;expect(close).not.toBeNull();close.focus();close.click()
 expect(document.activeElement).toBe(tab);expect(f.draft.operations).toEqual([])
})
it.each([false,true])('document properties close restores a visible entry or current tab (tab changed: %s)',async changed=>{
 const f=await fixture();await f.create()
 const entry=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.properties.documentProperties"]')!;entry.focus();entry.click()
 const panel=f.root.querySelector<HTMLDialogElement>('.pdf-metadata-dialog')!;await vi.waitFor(()=>expect(panel.open).toBe(true))
 const tab=f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="view"]')!;if(changed)tab.click()
 const close=panel.querySelector<HTMLButtonElement>('[data-metadata-cancel]');expect(close).not.toBeNull();close!.focus();close!.click()
 expect(panel.open).toBe(false);expect(document.activeElement).toBe(changed?tab:entry);expect(f.draft.operations).toEqual([])
})
it('navigation shows current page identity after refresh without changing the draft',async()=>{
 const f=await fixture(),view=await f.create();await view.refresh()
 expect(f.root.querySelector('.pdf-thumbnail')?.getAttribute('aria-current')).toBe('page')
 expect(f.root.querySelector('.pdf-outline-link')?.getAttribute('aria-current')).toBe('page')
 expect(f.root.querySelectorAll('.pdf-thumbnails header button')).toHaveLength(1)
 expect(f.root.querySelectorAll('.pdf-outline header button[aria-label="关闭目录大纲"]')).toHaveLength(1)
 expect(f.root.querySelectorAll('.pdf-outline header button[data-pdf-outline-editable]')).toHaveLength(1)
 expect(f.draft.operations).toEqual([])
})
it('switches between the source single and double page controls while keeping fit width and selection', async () => {
 const f=await fixture({pages:3,editingEnabled:false});await f.create()
 const viewport=f.root.querySelector<HTMLElement>('.pdf-document-pages')!
 Object.defineProperty(viewport,'clientWidth',{value:650})
 Object.defineProperty(viewport,'clientHeight',{value:800})
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="view"]')!.click()
 const spread=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.navigation.pageSpread"]')!
 const fit=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.pageZoom.fitWidth"]')!
 const zoom=f.root.querySelector<HTMLSelectElement>('.pdf-zoom')!
 const readout=f.root.querySelector<HTMLOutputElement>('[data-pdf-view-zoom]')!
 const rows=()=>[...viewport.querySelectorAll('.pdf-page-row')].map(row=>row.children.length)
 expect(spread.getAttribute('aria-pressed')).toBe('false')
 expect(spread.querySelector('svg')?.children).toHaveLength(2)
 expect(rows()).toEqual([1,1,1])
 const cards=[...viewport.querySelectorAll<HTMLElement>('.pdf-page')]
 cards[1].scrollIntoView=vi.fn()
 cards[1].querySelector<HTMLButtonElement>('.pdf-page-label')!.click()
 const selected=cards[1].dataset.pageId
 fit.click()
 await vi.waitFor(()=>expect(Number(zoom.value)).toBeGreaterThan(1.5))
 const singleZoom=Number(zoom.value)
 expect(readout.textContent).toBe(`${Math.round(singleZoom*100)}%`)
 spread.click()
 await vi.waitFor(()=>expect(rows()).toEqual([2,1]))
 expect(spread.getAttribute('aria-pressed')).toBe('true')
 expect(spread.querySelector('svg')?.children).toHaveLength(1)
 expect(Number(zoom.value)).toBeLessThan(singleZoom)
 expect(readout.textContent).toBe(`${Math.round(Number(zoom.value)*100)}%`)
 expect(viewport.querySelector<HTMLElement>('.pdf-page.is-active')?.dataset.pageId).toBe(selected)
 spread.click()
 await vi.waitFor(()=>expect(rows()).toEqual([1,1,1]))
 expect(spread.getAttribute('aria-pressed')).toBe('false')
 expect(spread.querySelector('svg')?.children).toHaveLength(2)
 expect(Number(zoom.value)).toBeCloseTo(singleZoom)
 expect(readout.textContent).toBe(`${Math.round(singleZoom*100)}%`)
 expect(viewport.querySelector<HTMLElement>('.pdf-page.is-active')?.dataset.pageId).toBe(selected)
 expect(f.draft.operations).toEqual([])
})
it('places the PDF zoom readout between the View controls and shares manual zoom with the status bar',async()=>{
 const f=await fixture({editingEnabled:false});await f.create()
 const readout=f.root.querySelector<HTMLOutputElement>('[data-pdf-view-zoom]')!
 const out=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.pageZoom.zoomOut"]')!
 const plus=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.pageZoom.zoomIn"]')!
 const slider=f.root.querySelector<HTMLInputElement>('.pdf-view-status input[type=range]')!
 expect(readout.previousElementSibling).toBe(out)
 expect(readout.nextElementSibling).toBe(plus)
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="view"]')!.click()
 const start=Number(slider.value)
 plus.click()
 await vi.waitFor(()=>expect(Number(slider.value)).toBeGreaterThan(start))
 expect(readout.textContent).toBe(slider.value+'%')
 out.click()
 await vi.waitFor(()=>expect(Number(slider.value)).toBe(start))
 expect(readout.textContent).toBe(slider.value+'%')
 expect(f.draft.operations).toEqual([])
})
it('thumbnail selection and outline navigation keep the paper selection on the same page identity',async()=>{
 const f=await fixture({pages:2});await f.create()
 f.root.querySelectorAll<HTMLElement>('.pdf-page').forEach(card=>{card.scrollIntoView=vi.fn()})
 const thumbnails=f.root.querySelectorAll<HTMLButtonElement>('.pdf-thumbnail');expect(thumbnails).toHaveLength(2)
 thumbnails[1].click()
 expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(thumbnails[1].dataset.pageId)
 expect(thumbnails[1].getAttribute('aria-current')).toBe('page');expect(thumbnails[0].hasAttribute('aria-current')).toBe(false)
 f.root.querySelector<HTMLButtonElement>('.pdf-outline-link')!.click()
 expect(f.root.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')).toBe(thumbnails[0].dataset.pageId)
 expect(thumbnails[0].getAttribute('aria-current')).toBe('page');expect(thumbnails[1].hasAttribute('aria-current')).toBe(false)
 expect(f.draft.operations).toEqual([])
})
it('thumbnail drag-and-drop reorders by source identity and leaves external drops untouched',async()=>{
 const f=await fixture({pages:2}),view=await f.create();await view.refresh()
 const [first,second]=[...f.root.querySelectorAll<HTMLButtonElement>('.pdf-thumbnail')]
 const transfer={effectAllowed:'',dropEffect:'',setData:vi.fn(),getData:vi.fn()}
 const start=new Event('dragstart',{bubbles:true,cancelable:true});Object.defineProperty(start,'dataTransfer',{value:transfer});first!.dispatchEvent(start)
 const over=new Event('dragover',{bubbles:true,cancelable:true});Object.defineProperty(over,'dataTransfer',{value:transfer});second!.dispatchEvent(over)
 expect(over.defaultPrevented).toBe(true);expect(second!.classList.contains('pdf-thumbnail-drop-before')).toBe(true)
 const drop=new Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(drop,'dataTransfer',{value:transfer});second!.dispatchEvent(drop)
 await vi.waitFor(()=>expect(f.draft.operations).toContainEqual({kind:'reorderPages',pageIds:[second!.dataset.pageId,first!.dataset.pageId]}))
 expect(second!.classList.contains('pdf-thumbnail-drop-before')).toBe(false)
 const external=new Event('dragover',{bubbles:true,cancelable:true});second!.dispatchEvent(external);expect(external.defaultPrevented).toBe(false)
 view.dispose()
})
it('thumbnail context menu edits its stable page identity and inserts blank pages at thumbnail gaps',async()=>{
 const f=await fixture({pages:2}),view=await f.create()
 const [first,second]=[...f.root.querySelectorAll<HTMLButtonElement>('.pdf-thumbnail')]
 const pageMenu=new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:40,clientY:50})
 first!.dispatchEvent(pageMenu)
 expect(pageMenu.defaultPrevented).toBe(true)
 const menu=f.root.querySelector<HTMLElement>('[data-pdf-thumbnail-menu]')!
 expect(menu).not.toBeNull()
 const firstItem=menu.querySelector<HTMLButtonElement>('button:not(:disabled)')!,secondItem=firstItem.nextElementSibling as HTMLButtonElement
 const down=new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true});firstItem.dispatchEvent(down)
 expect(down.defaultPrevented).toBe(true);expect(document.activeElement).toBe(secondItem)
 const escape=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true});document.activeElement!.dispatchEvent(escape)
 expect(escape.defaultPrevented).toBe(true);expect(f.root.querySelector('[data-pdf-thumbnail-menu]')).toBeNull();expect(document.activeElement).toBe(first)
 first!.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:40,clientY:50}))
 const reopened=f.root.querySelector<HTMLElement>('[data-pdf-thumbnail-menu]')!
 const rotate=[...reopened.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='向右旋转')!
 rotate.click()
 await vi.waitFor(()=>expect(f.draft.operations).toContainEqual({kind:'rotatePage',pageId:first!.dataset.pageId,delta:90}))
 expect(f.root.querySelector('[data-pdf-thumbnail-menu]')).toBeNull()
 const thumbs=f.root.querySelector<HTMLElement>('.pdf-thumbnails')!
 const current=[...f.root.querySelectorAll<HTMLButtonElement>('.pdf-thumbnail')]
 current[0]!.getBoundingClientRect=()=>new DOMRect(0,20,100,120);current[1]!.getBoundingClientRect=()=>new DOMRect(0,180,100,120)
 const gap=new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:35,clientY:160})
 thumbs.dispatchEvent(gap)
 expect(gap.defaultPrevented).toBe(true)
 const gapMenu=f.root.querySelector<HTMLElement>('[data-pdf-thumbnail-menu]')!
 expect(gapMenu).not.toBeNull()
 ;[...gapMenu.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='插入空白页')!.click()
 await vi.waitFor(()=>expect(f.draft.operations.some(operation=>operation.kind==='insertBlankPage')).toBe(true))
 const pageOrder=f.draft.operations.find(operation=>operation.kind==='reorderPages')?.pageIds as string[]
 expect(pageOrder[0]).toBe(first!.dataset.pageId);expect(pageOrder[1]).toMatch(/^blank:/);expect(pageOrder[2]).toBe(second!.dataset.pageId)
 expect(f.root.querySelector('[data-pdf-thumbnail-menu]')).toBeNull()
 view.dispose()
})
it('works on a pending blank page from its thumbnail context menu', async () => {
 let completeSave!: () => void
 const flush=vi.fn(() => new Promise<undefined>(resolve => {completeSave=()=>resolve(undefined)}))
 const f=await fixture({flushForFileOperation:flush});await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.page.insertBlank"]')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-thumbnail[data-page-id^="blank:"]')).not.toBeNull())
 const first=f.root.querySelector<HTMLElement>('.pdf-thumbnail[data-page-id^="blank:"]')!.dataset.pageId!
 function choose(label:string){
  const current=f.root.querySelector<HTMLButtonElement>('.pdf-thumbnail[data-page-id="'+first+'"]')!
  current.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:25,clientY:50}))
  const control=[...f.root.querySelectorAll<HTMLButtonElement>('[data-pdf-thumbnail-menu] button')].find(button=>button.textContent===label)
  expect(control?.disabled).toBe(false)
  control!.click()
 }
 choose('提取页面')
 const extract=f.root.querySelector<HTMLDialogElement>('dialog[aria-label="提取页面"]')!
 await vi.waitFor(()=>expect(extract.open).toBe(true))
 expect(extract.querySelector('input')?.value).toBe('2')
 expect(flush).toHaveBeenCalledOnce()
 extract.close(); completeSave()
 choose('向左旋转')
 await vi.waitFor(()=>expect(f.draft.operations).toContainEqual({kind:'rotatePage',pageId:first,delta:270}))
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-thumbnail[data-page-id="'+first+'"]')).not.toBeNull())
 choose('插入空白页')
 await vi.waitFor(()=>expect(f.root.querySelectorAll('.pdf-thumbnail[data-page-id^="blank:"]')).toHaveLength(2))
 const order=f.draft.operations.find(op=>op.kind==='reorderPages')!.pageIds as string[]
 expect(order).toEqual([pageId,first,expect.stringMatching(/^blank:/)])
 choose('删除页面')
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-thumbnail[data-page-id="'+first+'"]')).toBeNull())
 expect(f.draft.operations.some(op=>op.pageId===first || op.kind==='deletePage')).toBe(false)
 f.draft.undo()
 expect(f.draft.operations).toContainEqual({kind:'rotatePage',pageId:first,delta:270})
})
it('extracts the thumbnail page without a second click and retains the result link', async () => {
 const f=await fixture({exportPages:3})
 const extractPages=vi.fn(async ():Promise<NativeSaveResponse> => ({
  documentId:'child',revision:1,parentRevision:null,revisionRegistered:true,
  artifacts:{pdf:{downloadUrl:'/reviews/single-page.pdf'}},
  validation:{ok:false,issues:[{code:'review',message:'待复核'}]},
 }))
 Object.assign(f.api,{extractPages});await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="page"]')!.click()
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.page.extract"]')!.click()
 const dialog=f.root.querySelector<HTMLDialogElement>('dialog[aria-label="提取页面"]')!
 await vi.waitFor(()=>expect(dialog.open).toBe(true))
 expect(extractPages).not.toHaveBeenCalled();dialog.close()
 const thumbnail=f.root.querySelectorAll<HTMLButtonElement>('.pdf-thumbnail')[1]!
 thumbnail.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:25,clientY:35}))
 const command=[...f.root.querySelectorAll<HTMLButtonElement>('[data-pdf-thumbnail-menu] button')].find(button=>button.textContent==='提取页面')!
 command.click()
 await vi.waitFor(()=>expect(dialog.querySelector('a')?.getAttribute('href')).toBe('/reviews/single-page.pdf'))
 expect(extractPages).toHaveBeenCalledOnce()
 expect(extractPages).toHaveBeenCalledWith(expect.objectContaining({expectedSha256:sourceSha256,pages:[2]}))
 expect(dialog.textContent).toContain('待复核')
})
it('picks, cancels, and places an image from the Fill Form ribbon using the shared image tool', async () => {
 const observers:Array<{targets:Element[];callback:(entries:Array<{target:Element;isIntersecting:boolean}>)=>void}>=[]
 vi.stubGlobal('IntersectionObserver',class{
  targets:Element[]=[]
  constructor(readonly callback:(entries:Array<{target:Element;isIntersecting:boolean}>)=>void){observers.push(this)}
  observe(target:Element){this.targets.push(target)}disconnect(){}unobserve(){}
 })
 const f=await fixture();await f.create()
 vi.stubGlobal('createImageBitmap',vi.fn(async()=>({width:200,height:100,close:vi.fn()})))
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgoAAA==')
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="fillForm"]')!.click()
 const insert=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.fillForm.insertImage"]')!
 const edit=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.edit.objects.insertImage"]')!
 expect(insert).toBeTruthy()
 const fileInput=f.root.querySelector<HTMLInputElement>('[aria-label="选择要插入的图像"]')!
 const pick=vi.spyOn(fileInput,'click').mockImplementation(()=>{})
 const selectImage=async()=>{
  const count=pick.mock.calls.length
  insert.click()
  await vi.waitFor(()=>expect(pick).toHaveBeenCalledTimes(count+1))
  Object.defineProperty(fileInput,'files',{configurable:true,value:[new File(['data'],'form.png',{type:'image/png'})]})
  fileInput.dispatchEvent(new Event('change'))
  await vi.waitFor(()=>expect(insert.getAttribute('aria-pressed')).toBe('true'))
 }
 await selectImage();expect(edit.getAttribute('aria-pressed')).toBe('true')
 insert.click()
 await vi.waitFor(()=>expect(insert.getAttribute('aria-pressed')).toBe('false'))
 expect(edit.getAttribute('aria-pressed')).toBe('false');expect(pick).toHaveBeenCalledOnce();expect(f.draft.operations).toEqual([])
 await selectImage()
 const viewport=f.root.querySelector<HTMLElement>('.pdf-document-pages')!
 const escape=(options:KeyboardEventInit={})=>viewport.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true,...options}))
 expect(escape({isComposing:true})).toBe(true)
 expect(escape({keyCode:229})).toBe(true)
 expect(insert.getAttribute('aria-pressed')).toBe('true')
 const modal=document.createElement('dialog');f.root.append(modal);modal.showModal()
 expect(escape()).toBe(true)
 expect(insert.getAttribute('aria-pressed')).toBe('true')
 modal.close();modal.remove()
 expect(escape()).toBe(false)
 expect(insert.getAttribute('aria-pressed')).toBe('false')
 expect(edit.getAttribute('aria-pressed')).toBe('false')
 expect(f.draft.operations).toEqual([])
 await selectImage()
 const card=f.root.querySelector<HTMLElement>('.pdf-page')!,page=card.querySelector<HTMLElement>('.pdf-page-content')!
 page.getBoundingClientRect=()=>new DOMRect(0,0,300,400)
 observers.find(observer=>observer.targets.includes(card))!.callback([{target:card,isIntersecting:true}])
 await vi.waitFor(()=>expect(typeof page.onpointerdown).toBe('function'))
 page.onpointerdown!(new MouseEvent('pointerdown',{clientX:150,clientY:200}) as PointerEvent)
 page.onpointerup!(new MouseEvent('pointerup',{clientX:150,clientY:200}) as PointerEvent)
 await vi.waitFor(()=>expect(f.draft.operations).toEqual([expect.objectContaining({kind:'addDrawing',shape:'image',pageId,rect:[75,162.5,225,237.5]})]))
 expect(insert.getAttribute('aria-pressed')).toBe('false')
})
it('ignores an older image decode after a newer selection has armed placement',async()=>{
 const f=await fixture();await f.create()
 const closeOlder=vi.fn(),closeNewer=vi.fn()
 let resolveOlder!: (value:{width:number;height:number;close:()=>void})=>void
 vi.stubGlobal('createImageBitmap',vi.fn((file:File)=>file.name==='older.png'
  ?new Promise(resolve=>{resolveOlder=resolve})
  :Promise.resolve({width:180,height:90,close:closeNewer})))
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgoAAA==')
 const input=f.root.querySelector<HTMLInputElement>('[aria-label="选择要插入的图像"]')!
 for(const name of ['older.png','newer.png']){
  Object.defineProperty(input,'files',{configurable:true,value:[new File(['png'],name,{type:'image/png'})]})
  input.dispatchEvent(new Event('change'))
 }
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-editor-message')?.textContent).toContain('newer.png（180×90）'))
 resolveOlder({width:100,height:100,close:closeOlder})
 await vi.waitFor(()=>expect(closeOlder).toHaveBeenCalledOnce())
 expect(closeNewer).toHaveBeenCalledOnce()
 expect(f.root.querySelector('.pdf-editor-message')?.textContent).toContain('newer.png（180×90）')
})
it('signs the active visible form signature field without asking for a placement again', async () => {
 const f=await fixture({exportPages:2,signatureTargets:true});await f.create()
 const targetPage=pageId.replace(/:0$/,':1')
 f.root.querySelector<HTMLElement>('.pdf-page[data-page-id="'+targetPage+'"]')!.scrollIntoView=vi.fn()
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({clearRect:vi.fn(),measureText:()=>({actualBoundingBoxLeft:0,actualBoundingBoxRight:100,actualBoundingBoxAscent:80,actualBoundingBoxDescent:20}),fillText:vi.fn()} as unknown as CanvasRenderingContext2D)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgoAAA==')
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="fillForm"]')!.click()
 const field=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-signature-target="'+('7'.repeat(64))+'"]')!
 expect(field).toBeTruthy();field.focus()
 const sign=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.fillForm.sign"]')!
 expect(sign.disabled).toBe(false);sign.click()
 const dialog=()=>document.querySelector<HTMLDialogElement>('.pdf-signature-source-dialog')!
 await vi.waitFor(()=>expect(dialog()?.querySelector('.pdf-sign-tab')).toBeTruthy())
 await act(async()=>[...dialog().querySelectorAll<HTMLButtonElement>('.pdf-sign-tab')].find(button=>button.textContent==='输入')!.click())
 const input=dialog().querySelector<HTMLInputElement>('.pdf-modal-input')!
 await act(async()=>{
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'Sample')
  input.dispatchEvent(new Event('input',{bubbles:true}))
 })
 await act(async()=>dialog().querySelector<HTMLButtonElement>('.pdf-modal-btn.primary')!.click())
 await vi.waitFor(()=>expect(f.draft.operations).toContainEqual(expect.objectContaining({
  kind:'addDrawing',pageId:targetPage,shape:'image',signatureField:{fieldId:'7'.repeat(64),expectedFieldSha256:'9'.repeat(64)},
 })))
 expect(document.querySelector('.pdf-sign-target-dialog')).toBeNull()
 expect(f.root.querySelector('.pdf-editor-message')?.textContent).toContain('Second signature')
})
it.each(['ribbon','Escape'])('visual signature image belongs to the Sign command until placement or %s cancellation',async(cancelWith)=>{
 const close=vi.fn(),drawImage=vi.fn(),f=await fixture();await f.create()
 vi.stubGlobal('createImageBitmap',vi.fn(async()=>({width:3200,height:800,close})))
 vi.stubGlobal('Image',class{naturalWidth=3200;naturalHeight=800;onload:(()=>void)|null=null;onerror:(()=>void)|null=null;set src(_value:string){queueMicrotask(()=>this.onload?.())}})
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage,clearRect:vi.fn()} as unknown as CanvasRenderingContext2D)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgoAAA==')
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="annotate"]')!.click()
 const sign=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.annotate.signature.sign"]')!;expect(sign.disabled).toBe(false);sign.click()
 await vi.waitFor(()=>expect(document.querySelector('.pdf-signature-source-dialog')).not.toBeNull())
 const dialog=document.querySelector<HTMLDialogElement>('.pdf-signature-source-dialog')!
 await vi.waitFor(()=>expect(dialog.open).toBe(true))
 const imageMode=[...dialog.querySelectorAll<HTMLButtonElement>('.pdf-sign-tab')].find(button=>button.textContent==='图片')!;await act(async()=>imageMode.click())
 const input=dialog.querySelector<HTMLInputElement>('input[type="file"]')!
 expect(input.accept).toBe('image/*')
 const file=new File([new Uint8Array([1])],'signature.png',{type:'image/png'});Object.defineProperty(input,'files',{configurable:true,value:[file]});await act(async()=>input.dispatchEvent(new Event('change',{bubbles:true})))
 await vi.waitFor(()=>expect(dialog.querySelector<HTMLImageElement>('.pdf-sign-img')?.src).toContain('iVBORw0KGgo'))
 expect(dialog.querySelectorAll<HTMLInputElement>('.pdf-sign-bw input')[0]!.disabled).toBe(false)
 await act(async()=>dialog.querySelector<HTMLButtonElement>('.pdf-modal-btn.primary')!.click())
 expect(document.querySelector('.pdf-signature-source-dialog')).toBeNull();expect(f.root.dataset.pdfMode).toBe('draw')
 expect(f.root.querySelector('.pdf-editor-message')?.textContent).toContain('请在页面上拖出签名放置区域');expect(close).toHaveBeenCalledOnce()
 expect(sign.getAttribute('aria-pressed')).toBe('true')
 expect(f.root.querySelector<HTMLButtonElement>('[data-pdf-draw-shape="image"]')?.getAttribute('aria-pressed')).toBe('false')
 if (cancelWith === 'ribbon') sign.click()
 else f.root.querySelector<HTMLElement>('.pdf-document-pages')!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))
 await vi.waitFor(()=>expect(f.root.dataset.pdfMode).toBe('select'))
 expect(sign.getAttribute('aria-pressed')).toBe('false')
 expect(document.querySelector('.pdf-signature-source-dialog')).toBeNull()
 expect(f.draft.operations).toEqual([])
})
it('signature image ignores stale decoder completions and reports current decode errors',async()=>{
 const f=await fixture();await f.create();const pending=new Map<string,{resolve:(value:{width:number;height:number;close:()=>void})=>void;reject:(reason?:unknown)=>void}>()
 vi.stubGlobal('createImageBitmap',vi.fn((file:File)=>new Promise((resolve,reject)=>pending.set(file.name,{resolve:resolve as (value:{width:number;height:number;close:()=>void})=>void,reject}))))
 vi.stubGlobal('Image',class{naturalWidth=200;naturalHeight=100;onload:(()=>void)|null=null;onerror:(()=>void)|null=null;set src(_value:string){queueMicrotask(()=>this.onload?.())}})
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn(),clearRect:vi.fn()} as unknown as CanvasRenderingContext2D)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgoAAA==')
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="annotate"]')!.click();const sign=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.annotate.signature.sign"]')!;expect(sign.disabled).toBe(false);sign.click()
 await vi.waitFor(()=>expect(document.querySelector('.pdf-signature-source-dialog')).not.toBeNull())
 const dialog=document.querySelector<HTMLDialogElement>('.pdf-signature-source-dialog')!
 await vi.waitFor(()=>expect(dialog.open).toBe(true))
 await act(async()=>[...dialog.querySelectorAll<HTMLButtonElement>('.pdf-sign-tab')].find(button=>button.textContent==='图片')!.click())
 const input=dialog.querySelector<HTMLInputElement>('input[type="file"]')!
 const choose=async(name:string)=>{const file=new File(['image'],name,{type:'image/webp'});Object.defineProperty(input,'files',{configurable:true,value:[file]});await act(async()=>input.dispatchEvent(new Event('change',{bubbles:true})))}
 await choose('old.webp');await choose('new.webp')
 pending.get('new.webp')!.resolve({width:200,height:100,close:vi.fn()});await vi.waitFor(()=>expect(dialog.querySelector<HTMLImageElement>('.pdf-sign-img')?.src).toContain('iVBORw0KGgo'))
 pending.get('old.webp')!.resolve({width:80,height:40,close:vi.fn()});await new Promise(resolve=>setTimeout(resolve,0))
 expect(dialog.querySelector<HTMLImageElement>('.pdf-sign-img')?.src).toContain('iVBORw0KGgo')
 await choose('broken.webp');pending.get('broken.webp')!.reject(new Error('图片无法读取'));await vi.waitFor(()=>expect(dialog.querySelector('[role=alert]')?.textContent).toContain('图片无法读取'))
 expect(dialog.querySelector<HTMLImageElement>('.pdf-sign-img')?.src).toContain('iVBORw0KGgo')
 expect(input.accept).toBe('image/*')
 expect(f.draft.operations).toEqual([])
})
it('insert image accepts fixed-source WebP input and normalizes it for PNG placement',async()=>{
 const close=vi.fn(),decode=vi.fn(async()=>({width:3200,height:800,close})),f=await fixture();await f.create()
 vi.stubGlobal('createImageBitmap',decode)
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgoAAA==')
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="edit"]')!.click()
 const imageInput=f.root.querySelector<HTMLInputElement>('[aria-label="选择要插入的图像"]')!
 expect(imageInput.accept).toBe('image/png,image/jpeg,image/webp,image/gif,image/bmp')
 const file=new File(['image'],'diagram.webp',{type:'image/webp'});Object.defineProperty(imageInput,'files',{configurable:true,value:[file]});imageInput.dispatchEvent(new Event('change'))
 await vi.waitFor(()=>expect(f.root.dataset.pdfMode).toBe('draw'))
 expect(decode).toHaveBeenCalledWith(file);expect(close).toHaveBeenCalledOnce()
 expect(f.root.querySelector<HTMLButtonElement>('[data-pdf-draw-shape="image"]')?.getAttribute('aria-pressed')).toBe('true')
 expect(f.root.querySelector('.pdf-editor-message')?.textContent).toContain('diagram.webp（2400×600）')
 expect(f.draft.operations).toEqual([])
})
it('click image placement uses image and signature sizing rules while drag keeps the selected rectangle',async()=>{
 const observers:Array<{targets:Element[];callback:(entries:Array<{target:Element;isIntersecting:boolean}>)=>void}> = []
 vi.stubGlobal('IntersectionObserver',class{
  targets:Element[]=[]
  constructor(readonly callback:(entries:Array<{target:Element;isIntersecting:boolean}>)=>void){observers.push(this)}
  observe(target:Element){this.targets.push(target)}disconnect(){}unobserve(){}
 })
 const f=await fixture(),view=await f.create();vi.stubGlobal('createImageBitmap',vi.fn(async()=>({width:1000,height:500,close:vi.fn()})))
 vi.stubGlobal('Image',class{naturalWidth=1000;naturalHeight=500;onload:(()=>void)|null=null;onerror:(()=>void)|null=null;set src(_value:string){queueMicrotask(()=>this.onload?.())}})
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn(),clearRect:vi.fn()} as unknown as CanvasRenderingContext2D)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgoAAA==')
 const readyPage=async()=>{
  const card=f.root.querySelector<HTMLElement>('.pdf-page')!,page=card.querySelector<HTMLElement>('.pdf-page-content')!
  page.getBoundingClientRect=()=>new DOMRect(0,0,300,400)
  const observer=observers.find(item=>item.targets.includes(card))!;observer.callback([{target:card,isIntersecting:true}])
  await vi.waitFor(()=>expect(typeof page.onpointerdown,f.root.querySelector('.pdf-editor-message')?.textContent).toBe('function'))
  return page
 }
 const place=async(x1:number,y1:number,x2:number,y2:number)=>{const page=await readyPage();page.onpointerdown!(new MouseEvent('pointerdown',{clientX:x1,clientY:y1}) as PointerEvent);page.onpointerup!(new MouseEvent('pointerup',{clientX:x2,clientY:y2}) as PointerEvent);await vi.waitFor(()=>expect(f.draft.operations.at(-1)?.kind).toBe('addDrawing'));return f.draft.operations.at(-1)!}
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="edit"]')!.click()
 const fileInput=f.root.querySelector<HTMLInputElement>('[aria-label="选择要插入的图像"]')!,file=new File(['image'],'insert.png',{type:'image/png'})
 Object.defineProperty(fileInput,'files',{configurable:true,value:[file]});fileInput.dispatchEvent(new Event('change'));await vi.waitFor(()=>expect(f.root.dataset.pdfMode).toBe('draw'))
 expect(await place(150,200,150,200)).toMatchObject({pageId,shape:'image',rect:[75,162.5,225,237.5]})
 await view.refresh()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="annotate"]')!.click()
 const sign=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.annotate.signature.sign"]')!;sign.click()
 await vi.waitFor(()=>expect(document.querySelector('.pdf-signature-source-dialog .pdf-sign-tab')).not.toBeNull())
 const dialog=document.querySelector<HTMLDialogElement>('.pdf-signature-source-dialog')!
 await act(async()=>[...dialog.querySelectorAll<HTMLButtonElement>('.pdf-sign-tab')].find(button=>button.textContent==='图片')!.click())
 const signatureInput=dialog.querySelector<HTMLInputElement>('input[type=file]')!
 const signatureFile=new File(['image'],'signature.png',{type:'image/png'});Object.defineProperty(signatureInput,'files',{configurable:true,value:[signatureFile]});await act(async()=>signatureInput.dispatchEvent(new Event('change',{bubbles:true})))
 await vi.waitFor(()=>expect(dialog.querySelector<HTMLImageElement>('.pdf-sign-img')?.src).toContain('iVBORw0KGgo'))
 await act(async()=>dialog.querySelector<HTMLButtonElement>('.pdf-modal-btn.primary')!.click())
 expect(await place(150,200,150,200)).toMatchObject({pageId,shape:'image',rect:[100,175,200,225]})
 await view.refresh()
 Object.defineProperty(fileInput,'files',{configurable:true,value:[file]});fileInput.dispatchEvent(new Event('change'));await vi.waitFor(()=>expect(f.root.dataset.pdfMode).toBe('draw'))
 expect(await place(20,30,120,130)).toMatchObject({pageId,shape:'image',rect:[20,30,120,130]})
 expect(f.draft.operations).toHaveLength(3)
})
it('document properties retains actual source size after PDF.js transfers the source buffer',async()=>{
 const f=await fixture({detachSource:true,sourceSize:4096});await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.properties.documentProperties"]')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector<HTMLDialogElement>('.pdf-metadata-dialog')!.open,f.root.querySelector('.pdf-editor-message')?.textContent).toBe(true))
 const size=[...f.root.querySelectorAll('.pdf-metadata-readonly dt')].find(term=>term.textContent==='文件大小')!
 expect(size.nextElementSibling?.textContent).toBe('4 KB')
 expect(f.draft.operations).toEqual([])
})
it('dispose saves reading position before the AI workspace reparents and resets its scrolling layout',async()=>{
 const f=await fixture({pages:2}),view=await f.create(),viewport=f.root.querySelector<HTMLElement>('.pdf-document-pages')!
 viewport.getBoundingClientRect=()=>new DOMRect(0,0,300,200);viewport.scrollTop=600
 f.root.querySelectorAll<HTMLElement>('.pdf-page').forEach((card,index)=>{card.getBoundingClientRect=()=>new DOMRect(0,index*500-viewport.scrollTop,300,400)})
 const before=Element.prototype.before
 vi.spyOn(Element.prototype,'before').mockImplementation(function(this:Element,...nodes:(Node|string)[]){if(this.classList.contains('pdf-ai-workspace'))viewport.scrollTop=0;before.apply(this,nodes)})
 view.dispose()
 const saved=Object.values(JSON.parse(localStorage.getItem('genoffice-pdf-view-state')??'{}')) as {page:number;frac:number}[]
 expect(saved).toHaveLength(1);expect(saved[0]).toMatchObject({page:2,frac:.25});expect(f.draft.operations).toEqual([])
})
it('opening the AI workspace preserves the restored reading position before rendering is declared ready',async()=>{
 const f=await fixture({pages:2});saveViewState(pdfReadingKey(f.draft.identity),{page:2,frac:.25,scale:1,fitMode:null},localStorage)
 const bounds=HTMLElement.prototype.getBoundingClientRect,append=Element.prototype.append
 vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockImplementation(function(this:HTMLElement){
  if(this.classList.contains('pdf-document-pages'))return new DOMRect(0,0,300,200)
  if(this.classList.contains('pdf-page'))return new DOMRect(0,Number(this.dataset.pageId!.split(':').at(-1))*500-this.closest<HTMLElement>('.pdf-document-pages')!.scrollTop,300,400)
  return bounds.call(this)
 })
 vi.spyOn(Element.prototype,'append').mockImplementation(function(this:Element,...nodes:(Node|string)[]){
  for(const node of nodes)if(node instanceof HTMLElement&&node.classList.contains('pdf-layout')){const viewport=node.querySelector<HTMLElement>('.pdf-document-pages');if(viewport)viewport.scrollTop=0}
  append.apply(this,nodes)
 })
 await f.create();expect(f.root.querySelector<HTMLElement>('.pdf-document-pages')!.scrollTop).toBe(600)
 expect(f.root.querySelector('.pdf-thumbnail[aria-current="page"]')?.getAttribute('data-page-id')).toMatch(/:page:1$/)
 expect(f.draft.operations).toEqual([])
})
it('overflowing outline text supports Home and End while modifier keys retain their default',async()=>{
 const f=await fixture();await f.create();const link=f.root.querySelector<HTMLButtonElement>('.pdf-outline-link')!
 Object.defineProperties(link,{scrollHeight:{configurable:true,value:1000},clientHeight:{configurable:true,value:96}})
 const end=new KeyboardEvent('keydown',{key:'End',bubbles:true,cancelable:true});link.dispatchEvent(end);expect(end.defaultPrevented).toBe(true);expect(link.scrollTop).toBe(904)
 const home=new KeyboardEvent('keydown',{key:'Home',bubbles:true,cancelable:true});link.dispatchEvent(home);expect(home.defaultPrevented).toBe(true);expect(link.scrollTop).toBe(0)
 const modified=new KeyboardEvent('keydown',{key:'End',ctrlKey:true,bubbles:true,cancelable:true});link.dispatchEvent(modified);expect(modified.defaultPrevented).toBe(false);expect(link.scrollTop).toBe(0);expect(f.draft.operations).toEqual([])
})
it('readonly saved drawings explains unloaded edit metadata without claiming the source has no drawings',async()=>{
 const f=await fixture({editingEnabled:false});await f.create()
 ;[...f.root.querySelectorAll('button')].find(button=>button.textContent==='已保存绘图')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-saved-drawings')?.textContent).toMatch(/只读.*未加载绘图编辑信息/))
 expect(f.api.preview).not.toHaveBeenCalled();expect(f.root.querySelectorAll('[data-pdf-saved-drawing]')).toHaveLength(0);expect(f.draft.operations).toEqual([])
})
it('long comment rows handle Home and End without changing their thread or draft',async()=>{
 const restored:NativeOperation={kind:'addTextAnnotation',pageId,rect:[40,60,64,84],text:'长正文'.repeat(200)}
 const f=await fixture({restored});await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.navigation.comments"]')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-comment-row')).not.toBeNull())
 const row=f.root.querySelector<HTMLButtonElement>('.pdf-comment-row')!;Object.defineProperties(row,{scrollHeight:{value:1000},clientHeight:{value:100}})
 row.scrollTop=50
 const home=new KeyboardEvent('keydown',{key:'Home',cancelable:true,bubbles:true});row.dispatchEvent(home)
 expect(home.defaultPrevented).toBe(true);expect(row.scrollTop).toBe(0)
 const end=new KeyboardEvent('keydown',{key:'End',cancelable:true,bubbles:true});row.dispatchEvent(end)
 expect(end.defaultPrevented).toBe(true);expect(row.scrollTop).toBe(900);expect(f.draft.operations).toEqual([restored])
 const modified=new KeyboardEvent('keydown',{key:'Home',ctrlKey:true,cancelable:true,bubbles:true});row.dispatchEvent(modified)
 expect(modified.defaultPrevented).toBe(false);expect(row.scrollTop).toBe(900)
})
for(const spec of objectDialogs)it.each(['cancel','nativeCancel','title'])(`${spec.title} closes with %s and restores its product entry without changing the draft`,async action=>{
 const restored:NativeOperation=spec.kind==='note'?{kind:'addTextAnnotation',pageId,rect:[40,60,64,84],text:'原始便签'}:{kind:'addDrawing',pageId,shape:spec.kind,rect:[40,60,100,140],color:[1,0,0],width:1.6,...(spec.kind==='image'?{image:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='}:{})}
 const f=await fixture({restored});await f.create()
 if(spec.kind!=='note'){
  const toggle=[...f.root.querySelectorAll('button')].find(button=>button.textContent==='待保存绘图')!;toggle.click()
  await vi.waitFor(()=>expect(f.root.querySelector('.pdf-pending-drawings-panel')?.getAttribute('hidden')).toBeNull())
  f.root.querySelector<HTMLButtonElement>('[data-pdf-pending-drawing] button')!.click()
 }
 const opener=[...f.root.querySelectorAll('button')].find(button=>button.textContent===spec.entry)!
 expect(opener.disabled).toBe(false);opener.focus();opener.click()
 await vi.waitFor(()=>expect(f.root.querySelector<HTMLDialogElement>(`dialog[aria-label="${spec.title}"]`)?.open).toBe(true))
 const dialog=f.root.querySelector<HTMLDialogElement>(`dialog[aria-label="${spec.title}"]`)!,input=dialog.querySelector<HTMLInputElement|HTMLTextAreaElement>('input,textarea')!
 input.focus();input.value=spec.kind==='note'?'尚未提交的文字':'12'
 if(action==='nativeCancel')dialog.dispatchEvent(new Event('cancel',{cancelable:true}))
 else if(action==='title'){
  expect(dialog.querySelector('h2')?.textContent).toBe(spec.title)
  const close=dialog.querySelector<HTMLButtonElement>(`[aria-label="关闭${spec.title}"]`);expect(close).not.toBeNull();close!.click()
 }else [...dialog.querySelectorAll('button')].find(button=>button.textContent==='取消')!.click()
 await vi.waitFor(()=>expect(dialog.isConnected).toBe(false))
 expect(document.activeElement).toBe(opener);expect(f.draft.operations).toEqual([restored])
})


it('binary refresh PDF flush commits pending form input before dirty inspection and leaves unchanged controls clean',async()=>{
 const f=await fixture(),view=await f.create()
 expect(typeof (view as any).flushPendingEdits).toBe('function')
 ;(view as any).flushPendingEdits();expect(f.draft.dirty).toBe(false)
 const field=f.root.querySelector<HTMLInputElement>('.pdf-form-field input[aria-label="existing"]')!
 field.focus();field.value='Unblurred form value'
 expect(f.draft.dirty).toBe(false)
 ;(view as any).flushPendingEdits()
 expect(f.draft.dirty).toBe(true)
 expect(f.draft.operations).toEqual([expect.objectContaining({kind:'setFormValue',name:'existing',value:'Unblurred form value'})])
})

it('binary refresh PDF actual session save uses flushed pending form input',async()=>{
 const f=await fixture(),view=await f.create()
 const {bindNativeSession}=await import('./native-session')
 const field=f.root.querySelector<HTMLInputElement>('.pdf-form-field input[aria-label="existing"]')!
 field.focus();field.value='Saved pending value'
 const shell={editor:f.root,save:document.createElement('button'),exportPdf:document.createElement('button'),exportWord:document.createElement('button'),status:document.createElement('div'),statusLabel:document.createElement('span'),retry:document.createElement('button')} as unknown as EditorShell
 const save=vi.fn(async()=>({documentId:f.draft.identity.documentId,parentRevision:1,revision:2,revisionRegistered:false,artifacts:{},validation:{ok:false,issues:[]}}))
 const session=bindNativeSession(shell,{draft:f.draft,api:{save,export:save},format:'pdf',view})
 try{await session.save('save');expect(save).toHaveBeenCalledWith(expect.objectContaining({operations:[expect.objectContaining({kind:'setFormValue',value:'Saved pending value'})]}))}finally{session.dispose()}
})

it('names attachment actions and exposes the loading result to keyboard readers',async()=>{
 const f=await fixture({attachments:true});await f.create();f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="view"]')!.click();f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.navigation.attachments"]')!.click()
 const panel=f.root.querySelector<HTMLElement>('.pdf-attachments-sidebar')!,status=panel.querySelector<HTMLElement>('[role=status]')!
 await vi.waitFor(()=>expect(status.textContent).toBe('1 个附件'))
 expect(status.getAttribute('aria-label')).toBe('附件读取状态');expect(status.tabIndex).toBe(0)
 expect(panel.querySelector<HTMLButtonElement>('li button')!.getAttribute('aria-label')).toContain('keep.txt')
})
it('keeps keyboard focus on the matching attachment action after removal and undo',async()=>{
 const f=await fixture({attachments:true});await f.create();f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="view"]')!.click();f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.navigation.attachments"]')!.click()
 const panel=f.root.querySelector<HTMLElement>('.pdf-attachments-sidebar')!,button=(label:string)=>Array.from(panel.querySelectorAll<HTMLButtonElement>('button')).find(b=>b.textContent===label)!
 await vi.waitFor(()=>expect(button('移除附件')).toBeDefined());button('移除附件').focus();button('移除附件').click()
 await vi.waitFor(()=>expect(panel.querySelector('[role=status]')!.textContent).toContain('待移除 1'))
 expect(f.draft.operations).toHaveLength(1);expect(document.activeElement).toBe(button('撤销移除附件'))
 button('撤销移除附件').click();await vi.waitFor(()=>expect(panel.querySelector('[role=status]')!.textContent).toBe('1 个附件'))
 expect(f.draft.operations).toEqual([]);expect(document.activeElement).toBe(button('移除附件'))
})
it('returns keyboard focus to add after cancelling the last pending attachment',async()=>{
 const f=await fixture({attachments:true,restored:{kind:'addAttachment',name:'new.txt',bytesBase64:'eA=='}});await f.create();f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="view"]')!.click();f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.navigation.attachments"]')!.click()
 const panel=f.root.querySelector<HTMLElement>('.pdf-attachments-sidebar')!,button=(label:string)=>Array.from(panel.querySelectorAll<HTMLButtonElement>('button')).find(b=>b.textContent===label)!
 await vi.waitFor(()=>expect(button('取消新增附件')).toBeDefined());button('取消新增附件').focus();button('取消新增附件').click()
 await vi.waitFor(()=>expect(panel.querySelector('[role=status]')!.textContent).toBe('1 个附件'))
 expect(f.draft.operations).toEqual([]);expect(document.activeElement).toBe(button('新增附件'))
})
it('does not restore attachment focus after the user moves to another control during refresh',async()=>{
 const f=await fixture({attachments:true}),view=await f.create();f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="view"]')!.click();f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.view.navigation.attachments"]')!.click()
 const panel=f.root.querySelector<HTMLElement>('.pdf-attachments-sidebar')!
 await vi.waitFor(()=>expect(panel.querySelector('[role=status]')!.textContent).toBe('1 个附件'));panel.querySelector<HTMLButtonElement>('li button')!.focus()
 const pending=view.refresh(),close=panel.querySelector<HTMLButtonElement>('header button')!;close.focus();await pending
 await vi.waitFor(()=>expect(panel.querySelector('[role=status]')!.textContent).toBe('1 个附件'));expect(document.activeElement).toBe(close)
})

it('reopened host passes saved static fills into the management dialog',async()=>{
 const f=await fixture({staticFills:true,capabilities:{staticFill:true}});await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="fillForm"]')!.click()
 const entry=f.root.querySelector<HTMLButtonElement>('[data-pdf-static-fill-action="manage"]')!;expect(entry.disabled,entry.title).toBe(false);entry.click()
 await vi.waitFor(()=>expect(f.root.querySelector('[data-pdf-static-fill-id="saved-fill"]')?.textContent).toContain('已保存填写'))
 expect(f.draft.operations).toEqual([])
})

it('数字签名真实宿主入口只读展示原生清单，关闭不改草稿',async()=>{
 const f=await fixture({digitalSignatures:true});await f.create();f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="annotate"]')!.click()
 const button=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.annotate.signature.signaturePanel"]')!;expect(button.disabled).toBe(false);button.focus();await act(async()=>{button.click();await vi.dynamicImportSettled()})
 await vi.waitFor(()=>expect(document.querySelector('.pdf-digital-signatures-dialog')?.textContent).toContain('没有已赋值的数字签名'))
 await act(async()=>document.querySelector('dialog.pdf-digital-signatures-dialog')!.dispatchEvent(new Event('cancel',{cancelable:true})));expect(f.draft.operations).toEqual([]);expect(document.activeElement).toBe(button)
})
it('编辑关闭时数字签名入口仍可只读加载，且不调用修改预览',async()=>{
 const f=await fixture({digitalSignatures:true,editingEnabled:false});const source=await f.api.preview({expectedSha256:sourceSha256,operations:[]});vi.mocked(f.api.preview).mockClear()
 const readModel=vi.fn(async()=>source);Object.assign(f.api,{readModel});await act(async()=>{await f.create()});f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="annotate"]')!.click()
 const button=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.annotate.signature.signaturePanel"]')!;expect(button.disabled).toBe(false)
 await act(async()=>{button.click();await vi.dynamicImportSettled()});await vi.waitFor(()=>expect(document.querySelector('.pdf-digital-signatures-dialog')).not.toBeNull())
 expect(readModel).toHaveBeenCalledOnce();expect(f.api.preview).not.toHaveBeenCalled();expect(f.draft.operations).toEqual([])
 await act(async()=>document.querySelector('dialog.pdf-digital-signatures-dialog')!.dispatchEvent(new Event('cancel',{cancelable:true})))
})
it('steps through editable PDF fields after navigation button focus and after a draft redraw', async () => {
 const f=await fixture({navigationFields:true});await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="fillForm"]')!.click()
 const next=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-navigation="next"]')!
 const previous=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-navigation="previous"]')!
 async function step(button:HTMLButtonElement,name:string){
  button.focus();expect(document.activeElement).toBe(button);button.click()
  await vi.waitFor(()=>expect(document.activeElement?.getAttribute('aria-label')).toBe(name))
 }
 const progress=f.root.querySelector('[aria-label="表单字段位置"]')!
 expect(progress.textContent).toBe('0 / 2')
 await step(next,'existing');expect(progress.textContent).toBe('1 / 2')
 await step(next,'secondary');expect(progress.textContent).toBe('2 / 2')
 const second=document.activeElement as HTMLInputElement
 second.value='Changed';second.dispatchEvent(new Event('change'))
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-form-controls input[aria-label="secondary"]')).not.toBe(second))
 expect(progress.textContent).toBe('2 / 2')
 await step(next,'existing');expect(progress.textContent).toBe('1 / 2')
 await step(previous,'secondary')
 await step(previous,'existing')
 expect(f.draft.operations).toEqual([expect.objectContaining({kind:'setFormValue',name:'secondary',value:'Changed'})])
})
it('navigates actual repeated form widgets in visible page order and skips a deleted page', async () => {
 const f=await fixture({exportPages:3,navigationFields:true,widgetNavigation:true})
 const [first,second,third]=[0,1,2].map(page=>pageId.replace(/:0$/,':'+page))
 f.draft.setOperations([{kind:'deletePage',pageId:second},{kind:'reorderPages',pageIds:[third,first]}])
 await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="fillForm"]')!.click()
 const next=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-navigation="next"]')!
 const progress=f.root.querySelector('[aria-label="表单字段位置"]')!
 const card=(id:string)=>f.root.querySelector<HTMLElement>('.pdf-page[data-page-id="'+id+'"]')!
 card(first).scrollIntoView=vi.fn();card(third).scrollIntoView=vi.fn()
 next.focus();next.click()
 await vi.waitFor(()=>expect(progress.textContent).toBe('1 / 2'))
 expect(card(third).classList.contains('is-active')).toBe(true)
 expect(document.activeElement?.getAttribute('aria-label')).toBe('existing')
 next.focus();next.click()
 await vi.waitFor(()=>expect(progress.textContent).toBe('2 / 2'))
 expect(card(first).scrollIntoView).toHaveBeenCalled()
 expect(card(first).classList.contains('is-active')).toBe(true)
 expect(document.activeElement?.getAttribute('aria-label')).toBe('existing')
})
it('checks required form fields, focuses the missing value and exits after a staged fill', async () => {
 const f=await fixture({requiredField:true});await f.create()
 const fill=f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="fillForm"]')!
 const home=f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="home"]')!
 fill.click()
 const complete=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.fillForm.complete"]')!
 expect(complete).toBeTruthy()
 complete.click()
 await vi.waitFor(()=>expect(f.root.textContent).toContain('还有 1 个必填字段未填写'))
 const field=f.root.querySelector<HTMLInputElement>('.pdf-form-controls input[aria-label="existing"]')!
 expect(document.activeElement).toBe(field)
 expect(fill.getAttribute('aria-selected')).toBe('true')
 expect(f.draft.operations).toEqual([])
 field.value='Alice'
 field.dispatchEvent(new Event('change'))
 await vi.waitFor(()=>expect(f.draft.operations).toEqual([expect.objectContaining({kind:'setFormValue',name:'existing',value:'Alice'})]))
 complete.click()
 await vi.waitFor(()=>expect(home.getAttribute('aria-selected')).toBe('true'))
 expect(f.root.textContent).toContain('表单填写检查完成')
 expect(f.draft.operations).toHaveLength(1)
})
it('locates the first missing field on its visible page and keeps navigation on that widget', async () => {
 const f=await fixture({exportPages:3,navigationFields:true,widgetNavigation:true})
 const [first,deleted,last]=[0,1,2].map(page=>pageId.replace(/:0$/,':'+page))
 for(const annotations of pdfMock.widgetPages!.slice(1))for(const field of annotations){
  field.fieldName='secondary';field.required=true;field.fieldValue=''
 }
 f.draft.setOperations([{kind:'deletePage',pageId:deleted}])
 await f.create()
 const card=(id:string)=>f.root.querySelector<HTMLElement>('.pdf-page[data-page-id="'+id+'"]')!
 const scroll=vi.fn();card(last).scrollIntoView=scroll
 expect(card(first).classList.contains('is-active')).toBe(true)
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="fillForm"]')!.click()
 f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.fillForm.complete"]')!.click()
 await vi.waitFor(()=>expect(f.root.textContent).toContain('还有 1 个必填字段未填写'))
 expect(scroll).toHaveBeenCalled()
 expect(card(last).classList.contains('is-active')).toBe(true)
 expect(document.activeElement?.getAttribute('aria-label')).toBe('secondary')
 expect(f.root.querySelector('[aria-label="表单字段位置"]')?.textContent).toBe('2 / 2')
 expect(f.draft.operations).toEqual([{kind:'deletePage',pageId:deleted}])
})
it('keeps the form placement tool armed across multiple clicks until Keep adding is turned off',async()=>{
 const observers:Array<{targets:Element[];callback:(entries:Array<{target:Element;isIntersecting:boolean}>)=>void}>=[]
 vi.stubGlobal('IntersectionObserver',class{
  targets:Element[]=[]
  constructor(readonly callback:(entries:Array<{target:Element;isIntersecting:boolean}>)=>void){observers.push(this)}
  observe(target:Element){this.targets.push(target)}disconnect(){}unobserve(){}
 })
 const f=await fixture();await f.create()
 f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="formDesign"]')!.click()
 const keep=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.keepTool"]')!
 const text=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.addTextField"]')!
 expect(keep?.getAttribute('aria-pressed')).toBe('false')
 await act(async()=>keep.click())
 expect(keep.getAttribute('aria-pressed')).toBe('true')
 await act(async()=>text.click())
 const card=f.root.querySelector<HTMLElement>('.pdf-page')!
 await act(async()=>observers.find(observer=>observer.targets.includes(card))!.callback([{target:card,isIntersecting:true}]))
 await vi.waitFor(()=>expect(f.root.querySelector('.pdf-formdesign-layer')).not.toBeNull())
 async function place(y:number){
  const layer=f.root.querySelector<HTMLElement>('.pdf-formdesign-layer')!
  layer.getBoundingClientRect=()=>new DOMRect(0,0,300,400)
  layer.setPointerCapture=vi.fn()
  for(const type of ['pointerdown','pointerup']){
   await act(async()=>{layer.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,clientX:35,clientY:y}))})
  }
 }
 await place(80);await place(150)
 expect(f.draft.operations.map(op=>op.fieldName)).toEqual(['Field1','Field2'])
 expect(keep.disabled).toBe(false)
 await act(async()=>keep.click())
 expect(keep.getAttribute('aria-pressed')).toBe('false')
 await place(220);await place(290)
 expect(f.draft.operations.map(op=>op.fieldName)).toEqual(['Field1','Field2','Field3'])
})
it('creation commands remain available for a pure creation draft and settings append another field',async()=>{
 const first=operation('createFormField'),f=await fixture({restored:first});await f.create()
 const create=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.addTextField"]')!,settings=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.fieldSettings"]')!
 expect(create.disabled).toBe(false);expect(settings.disabled).toBe(false);settings.click()
 await vi.waitFor(()=>expect(f.root.querySelector<HTMLElement>('.pdf-form-create-panel')?.hidden).toBe(false))
 f.root.querySelector<HTMLInputElement>('[data-pdf-form-create-name]')!.value='second_field'
 f.root.querySelector<HTMLButtonElement>('[data-pdf-form-create-apply]')!.click()
 await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(2));expect(f.draft.operations[0]).toEqual(first);expect(f.draft.operations[1]).toMatchObject({kind:'createFormField',fieldName:'second_field'})
})
