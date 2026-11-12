import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft,type NativeOperation} from './native-draft'
import {createPdfEditorView,type PdfEditorHandle} from './pdf-main'
import type {EditorShell} from './shell'
import type {createNativeApi,NativeContextResponse} from './native-api'
vi.mock('./source-validation',()=>({bytesSha256:async()=>'a'.repeat(64)}))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs',()=>{
 const page={view:[0,0,300,400],rotate:0,userUnit:1,getViewport:({scale}:{scale:number})=>({width:300*scale,height:400*scale,viewBox:[0,0,300,400]}),getTextContent:async()=>({items:[]}),getAnnotations:async()=>[],render:()=>({promise:Promise.resolve(),cancel:vi.fn()})}
 const pdf={numPages:1,getPage:async()=>page,getMetadata:async()=>({info:{}}),getOutline:async()=>[],destroy:async()=>{}}
 return {AnnotationMode:{ENABLE:1},GlobalWorkerOptions:{},TextLayer:class{},getDocument:()=>({promise:Promise.resolve(pdf),destroy:async()=>{}})}
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
beforeEach(()=>{localStorage.clear();vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}unobserve(){}});vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({} as CanvasRenderingContext2D);Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:vi.fn(function(this:HTMLDialogElement){this.open=true})});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:vi.fn(function(this:HTMLDialogElement){this.open=false})})})
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals();for(const name of ["showModal","close"] as const){const descriptor=dialogDescriptors[name];if(descriptor)Object.defineProperty(HTMLDialogElement.prototype,name,descriptor);else Reflect.deleteProperty(HTMLDialogElement.prototype,name)}})
async function fixture(options:{restored?:NativeOperation;capabilities?:Record<string,boolean>}={}){
 const root=document.createElement('div');document.body.append(root)
 const identity={documentId:'pdf-object-host',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}
 const seed=new NativeDraft(identity,localStorage);if(options.restored)seed.setOperations([options.restored]);const draft=new NativeDraft(identity,localStorage)
 const model={sourceSha256,pages:[{pageId,notesReadSafe:true}],formFields:[{name:'existing',kind:'text',value:'Alice',editable:true,fieldId:'f'.repeat(64),expectedFieldSha256:'1'.repeat(64)}],formDesignWidgets:[widget],existingImages:[image],capabilities:{createFormField:true,editFormFieldRequired:true,editExistingImage:true,...options.capabilities}}
 const api={file:async()=>new Uint8Array([1,2]).buffer,preview:vi.fn(async()=>({sourceSha256,model})),previewFile:vi.fn(async()=>new Uint8Array([3,4]).buffer)} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:identity.documentId,revision:1,format:'pdf',scope:identity.scope,sourceFile:{sha256:sourceSha256}},editingEnabled:true,pdfTextEnabled:false} as NativeContextResponse
 const create=async()=>{const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view);return view}
 return {root,draft,create,api}
}
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
