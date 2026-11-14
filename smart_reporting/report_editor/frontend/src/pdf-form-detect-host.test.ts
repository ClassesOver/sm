import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {createPdfEditorView,type PdfEditorHandle} from './pdf-main'
import type {EditorShell} from './shell'
import type {createNativeApi,NativeContextResponse} from './native-api'
vi.mock('./source-validation',()=>({bytesSha256:async()=>'a'.repeat(64)}))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs',()=>{
 const page={pageNumber:1,view:[0,0,300,400],rotate:0,userUnit:1,getViewport:({scale}:{scale:number})=>({width:300*scale,height:400*scale,viewBox:[0,0,300,400]}),getTextContent:async()=>({items:[{str:'Name: ________',transform:[12,0,0,12,30,300],width:140,height:12}]}),getOperatorList:async()=>({fnArray:[],argsArray:[]}),getAnnotations:async()=>[],render:()=>({promise:Promise.resolve(),cancel(){}})}
 const pdf={numPages:1,getPage:async()=>page,getMetadata:async()=>({info:{}}),getOutline:async()=>[],destroy:async()=>{}}
 return {OPS:{},AnnotationMode:{ENABLE:1},GlobalWorkerOptions:{},TextLayer:class{},getDocument:()=>({promise:Promise.resolve(pdf),destroy:async()=>{}})}
})
const views:PdfEditorHandle[]=[]
beforeEach(()=>{localStorage.clear();vi.stubGlobal('IntersectionObserver',undefined);vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({} as CanvasRenderingContext2D);Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}});Object.defineProperty(HTMLElement.prototype,'scrollIntoView',{configurable:true,value(){}})})
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})
async function fixture(editingEnabled=true,capability=true){
 const root=document.body.appendChild(document.createElement('div')),sourceSha256='a'.repeat(64),pageId=`sha256:${sourceSha256}:page:0`,identity={documentId:'detect-host',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},draft=new NativeDraft(identity,localStorage)
 const api={file:async()=>new Uint8Array([1,2]).buffer,previewFile:vi.fn(async()=>new Uint8Array([3,4]).buffer),preview:vi.fn(async()=>({sourceSha256,previewDigest:'f'.repeat(64),appliedOperationIndices:[0],skippedOperations:[],model:{sourceSha256,pages:[{pageId,notesReadSafe:true}],formFields:[],formDesignWidgets:[],capabilities:{createFormField:capability}}}))} as unknown as ReturnType<typeof createNativeApi>
 const context={context:{documentId:identity.documentId,revision:1,format:'pdf',scope:identity.scope,sourceFile:{sha256:sourceSha256,path:'/fixture/form.pdf'}},editingEnabled,pdfTextEnabled:false} as NativeContextResponse
 const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
 return {root,draft,view,api,sourceSha256,pageId,open:root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.detectFields"]')}
}
it('公开自动检测入口复用单字段草稿与实际预览确认流程',async()=>{
 const f=await fixture();f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="formDesign"]')!.click();expect(f.open).not.toBeNull();expect(f.open!.disabled).toBe(false);f.open!.click()
 await vi.waitFor(()=>expect(f.root.querySelector('input[type=radio]')).not.toBeNull());expect(f.draft.operations).toEqual([]);f.root.querySelector<HTMLInputElement>('input[type=radio]')!.click();f.root.querySelector<HTMLButtonElement>('[data-pdf-form-detect-apply]')!.click();await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1));expect(f.draft.operations[0]).toMatchObject({kind:'createFormField',sourceSha256:f.sourceSha256,pageId:f.pageId,fieldName:'name',fieldKind:'text'})
 await expect(f.view.prepareSave()).rejects.toThrow('请核对实际 PDF 预览');expect(f.api.previewFile).toHaveBeenCalledWith(expect.objectContaining({operations:f.draft.operations,expectedPreviewDigest:'f'.repeat(64)}),expect.any(AbortSignal));const confirm=f.root.querySelector<HTMLInputElement>('.pdf-preview-review input[type=checkbox]')!;confirm.checked=true;confirm.dispatchEvent(new Event('change'));await expect(f.view.prepareSave()).resolves.toEqual({confirmedPreviewDigest:'f'.repeat(64)})
})
it.each(['readonly','capability','saving'] as const)('公开入口 %s 禁用，强制分发也不启动检测',async state=>{
 const f=await fixture(state!=='readonly',state!=='capability');if(state==='saving')f.view.setSaving(true);expect(f.open).not.toBeNull();expect(f.open!.disabled).toBe(true);f.open!.dispatchEvent(new MouseEvent('click'));await Promise.resolve();expect(f.root.querySelector('dialog[aria-label="自动检测表单字段"]')).toBeNull();expect(f.draft.operations).toEqual([])
})
