import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NativeDraft } from './native-draft'
import { createPdfEditorView, type PdfEditorHandle } from './pdf-main'
import type { EditorShell } from './shell'
import type { createNativeApi, NativeContextResponse } from './native-api'

vi.mock('./source-validation',()=>({bytesSha256:async()=>'a'.repeat(64)}))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs',()=>{
  const page={view:[0,0,300,400],rotate:0,userUnit:1,getViewport:({scale}:{scale:number})=>({width:300*scale,height:400*scale,viewBox:[0,0,300,400]}),getTextContent:async()=>({items:[]}),getAnnotations:async()=>[],render:()=>({promise:Promise.resolve(),cancel:vi.fn()})}
  const pdf={numPages:1,getPage:async()=>page,getMetadata:async()=>({info:{}}),getOutline:async()=>[],destroy:async()=>{}}
  return {AnnotationMode:{ENABLE:1},GlobalWorkerOptions:{},TextLayer:class {},getDocument:()=>({promise:Promise.resolve(pdf),destroy:async()=>{}})}
})
const views:PdfEditorHandle[]=[]
beforeEach(()=>{localStorage.clear();vi.stubGlobal('IntersectionObserver',class{observe(){}disconnect(){}unobserve(){}});vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({} as CanvasRenderingContext2D)})
afterEach(()=>{views.splice(0).forEach(view=>view.dispose());document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})

async function fixture(editingEnabled=true,restorePatch?:Record<string,unknown>,radio=false,textProperties=false,widgetProperties=false,choiceProperties=false,radioRename=false,radioRequired=false){
  const root=document.createElement('div');document.body.append(root)
  const sourceSha256='a'.repeat(64),pageId=`sha256:${sourceSha256}:page:0`
  const identity={documentId:'form-design-host',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}
  const draft=new NativeDraft(identity,localStorage)
  const widget={fieldName:'customer',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),pageIndex:0,rect:[20,20,120,44],removable:true,removalReason:null,...(textProperties?{designEditable:true,fieldKind:'text',textPropertiesEditable:true,textProperties:{multiLine:false,maxLen:null,textAlignment:'left',fontSize:12,fontName:'Helvetica',valueLength:5}}:{}),...(radio?{designEditable:true,fieldKind:'radio',radioOptions:['Yes'],radioValue:'Yes'}:{}),...(choiceProperties?{designEditable:true,fieldKind:'choice',choiceOptionsEditable:true,choiceOptionsReason:null,choiceOptions:['One','Two'],choiceValue:'Two',choiceDefaultValue:null}:{})}
  const widgets=radioRename||radioRequired?[{...widget,radioOptions:['Yes','No'],radioRenameEditable:true,radioRenameReason:null,...(radioRequired?{required:false,removable:false,radioRequiredEditable:true,radioRequiredReason:null}:{})},{...widget,radioOptions:['Yes','No'],widgetId:'8R',widgetIdentity:'9'.repeat(64),expectedWidgetSha256:'8'.repeat(64),rect:[150,20,174,44],radioRenameEditable:true,radioRenameReason:null,...(radioRequired?{required:false,removable:false,radioRequiredEditable:true,radioRequiredReason:null}:{})}]:[widget]
  if(restorePatch)draft.setOperations([{kind:textProperties?'editFormTextProperties':radio?'appendRadioWidget':'removeFormWidget',...(textProperties?{fontSize:18}:{}),...(radio&&!radioRename&&!radioRequired?{pageId,rect:[150,100,170,120],exportValue:'No'}:{}),sourceSha256,fieldName:widget.fieldName,widgetId:widget.widgetId,widgetIdentity:widget.widgetIdentity,expectedWidgetSha256:widget.expectedWidgetSha256,...restorePatch}])
  const api={file:async()=>new Uint8Array([1,2]).buffer,previewFile:vi.fn(async()=>new Uint8Array([3,4]).buffer),preview:vi.fn(async()=>({sourceSha256,previewDigest:'f'.repeat(64),appliedOperationIndices:[0],skippedOperations:[],model:{sourceSha256,pages:[{pageId,notesReadSafe:true}],formFields:[{name:'customer',kind:choiceProperties?'choice':'text',value:choiceProperties?'Two':'Alice',editable:choiceProperties,fieldId:'d'.repeat(64),expectedFieldSha256:'e'.repeat(64),...(choiceProperties?{options:['One','Two']}:{})}],formDesignWidgets:widgets,capabilities:{removeFormWidget:true,appendRadioWidget:radio,editFormTextProperties:textProperties,editFormWidget:widgetProperties}}}))} as unknown as ReturnType<typeof createNativeApi>
  const context={context:{documentId:identity.documentId,revision:1,format:'pdf',scope:identity.scope,sourceFile:{sha256:sourceSha256}},editingEnabled,pdfTextEnabled:false} as NativeContextResponse
  const view=await createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft});views.push(view)
  return{root,draft,view,sourceSha256,widget,api}
}

it('public form design ribbon stages exact deletion into the existing draft and public Undo restores it',async()=>{
  const f=await fixture()
  const tab=f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="formDesign"]')!
  expect(tab.hidden).toBe(false);tab.click()
  const open=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.deleteField"]')!
  expect(open).not.toBeNull();expect(open.disabled).toBe(false);open.click()
  await vi.waitFor(()=>expect(f.root.querySelector<HTMLElement>('[aria-label="表单字段设计"]')!.hidden).toBe(false))
  f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!.click()
  await vi.waitFor(()=>expect(f.draft.operations).toEqual([{kind:'removeFormWidget',sourceSha256:f.sourceSha256,fieldName:'customer',widgetId:'7R',widgetIdentity:f.widget.widgetIdentity,expectedWidgetSha256:f.widget.expectedWidgetSha256}]))
  f.root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab="home"]')!.click()
  f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.home.edit.undo"]')!.click()
  await vi.waitFor(()=>expect(f.draft.operations).toEqual([]))
})

it('forced form design dispatch while saving or readonly cannot stage field deletion',async()=>{
  const f=await fixture();f.view.setSaving(true)
  const open=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.deleteField"]')!
  open.dispatchEvent(new MouseEvent('click'))
  await Promise.resolve();expect(f.root.querySelector<HTMLElement>('[aria-label="表单字段设计"]')!.hidden).toBe(true)
  expect(f.draft.operations).toEqual([])
  const readonly=await fixture(false)
  readonly.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.deleteField"]')!.dispatchEvent(new MouseEvent('click'))
  await Promise.resolve();expect(readonly.root.querySelector<HTMLElement>('[aria-label="表单字段设计"]')!.hidden).toBe(true)
  expect(readonly.draft.operations).toEqual([])
})

it('field deletion prepares the actual PDF preview and requires confirmation of its digest before saving',async()=>{
  const f=await fixture()
  f.draft.setOperations([{kind:'removeFormWidget',sourceSha256:f.sourceSha256,fieldName:'customer',widgetId:'7R',widgetIdentity:f.widget.widgetIdentity,expectedWidgetSha256:f.widget.expectedWidgetSha256}])
  const reviewPanel=f.root.querySelector<HTMLElement>('.pdf-preview-review')!
  reviewPanel.scrollIntoView=vi.fn()
  await expect(f.view.prepareSave()).rejects.toThrow('请核对实际 PDF 预览')
  expect(f.api.previewFile).toHaveBeenCalledWith(expect.objectContaining({operations:f.draft.operations,expectedPreviewDigest:'f'.repeat(64)}),expect.any(AbortSignal))
  expect(f.root.dataset.pdfPreview).toBe('true')
  expect(reviewPanel.hidden).toBe(false)
  expect(reviewPanel.textContent).toContain('删除表单字段')
  const confirm=reviewPanel.querySelector<HTMLInputElement>('input[type="checkbox"]')!
  confirm.checked=true;confirm.dispatchEvent(new Event('change'))
  await expect(f.view.prepareSave()).resolves.toEqual({confirmedPreviewDigest:'f'.repeat(64)})
})

it('restored widget deletion validates source and all four widget identity components',async()=>{
  for(const patch of [{sourceSha256:'f'.repeat(64)},{fieldName:'missing-field'},{widgetId:'999R0'},{widgetIdentity:'f'.repeat(64)},{expectedWidgetSha256:'f'.repeat(64)}]){
    await expect(fixture(true,patch)).rejects.toThrow(/来源|身份|控件/)
  }
  const restored=await fixture(true,{});expect(restored.draft.operations[0]?.kind).toBe('removeFormWidget')
})


it('radio append ribbon stages exact identities and preserves existing selection',async()=>{
 const f=await fixture(true,undefined,true)
 const open=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.addRadioOption"]')!
 expect(open).not.toBeNull();expect(open.disabled).toBe(false);open.click()
 const panel=f.root.querySelector<HTMLElement>('.pdf-form-radio-extension-panel')!
 await vi.waitFor(()=>expect(panel.hidden).toBe(false))
 const value=panel.querySelector<HTMLInputElement>('[aria-label="新增选项值"]')!;value.value='No'
 panel.querySelector<HTMLButtonElement>('[data-pdf-radio-extension-apply]')!.click()
 await vi.waitFor(()=>expect(f.draft.operations).toEqual([expect.objectContaining({kind:'appendRadioWidget',sourceSha256:f.sourceSha256,fieldName:f.widget.fieldName,widgetId:f.widget.widgetId,widgetIdentity:f.widget.widgetIdentity,expectedWidgetSha256:f.widget.expectedWidgetSha256,exportValue:'No'})]))
})

it('restored radio append rejects stale widget identities',async()=>{
 for(const patch of [{fieldName:'foreign'},{widgetId:'999R'},{widgetIdentity:'f'.repeat(64)},{expectedWidgetSha256:'f'.repeat(64)}]){
  await expect(fixture(true,patch,true)).rejects.toThrow()
 }
})

it('restored valid radio append survives source and widget revalidation',async()=>{
 const f=await fixture(true,{},true)
 expect(f.draft.operations[0]?.kind).toBe('appendRadioWidget')
})


it('text properties ribbon opens only when source capability is advertised',async()=>{
 const f=await fixture(true,undefined,false,true)
 const open=f.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.textProperties"]')!
 expect(open).not.toBeNull();expect(open.disabled).toBe(false);open.click()
 await vi.waitFor(()=>expect(f.root.querySelector<HTMLElement>('.pdf-form-text-properties-panel')!.hidden).toBe(false))
 const readonly=await fixture(false,undefined,false,true)
 expect(readonly.root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.formDesign.textProperties"]')!.disabled).toBe(true)
})

it('restored text properties require source and all four widget identity components',async()=>{
 for(const patch of [{sourceSha256:'f'.repeat(64)},{fieldName:'foreign'},{widgetId:'999R'},{widgetIdentity:'f'.repeat(64)},{expectedWidgetSha256:'f'.repeat(64)}]){
  await expect(fixture(true,patch,false,true)).rejects.toThrow()
 }
 const f=await fixture(true,{},false,true);expect(f.draft.operations[0]?.kind).toBe('editFormTextProperties')
})

it('actual PDF preview keeps an applied field change and displays independent overflow review issues',async()=>{
 const f=await fixture(true,{},false,true)
 const preview=await f.api.preview({expectedSha256:f.sourceSha256,operations:f.draft.operations})
 const message='字段 customer 的文本超出控件可见范围，实际内容与下载已保留。'
 vi.mocked(f.api.preview).mockResolvedValue({...preview,reviewIssues:[{operationIndex:0,kind:'editFormTextProperties',fieldName:'customer',code:'pdf_form_text_overflow',message}]})
 const panel=f.root.querySelector<HTMLElement>('.pdf-preview-review')!
 panel.scrollIntoView=vi.fn()
 await expect(f.view.prepareSave()).rejects.toThrow('请核对实际 PDF 预览')
 expect(panel.textContent).toContain('已执行：第 1 项')
 expect(panel.textContent).toContain(message)
 expect(panel.textContent).not.toContain('未执行，保留原文')
 expect(panel.textContent).toContain('1 项内容或版式复核告警')
 const confirm=panel.querySelector<HTMLInputElement>('input[type="checkbox"]')!
 confirm.checked=true;confirm.dispatchEvent(new Event('change'))
 await expect(f.view.prepareSave()).resolves.toEqual({confirmedPreviewDigest:'f'.repeat(64)})
 expect(f.draft.operations[0]?.kind).toBe('editFormTextProperties')
})

it('fill-only validation presents a layout warning without declaring the applied value skipped',async()=>{
 const f=await fixture()
 const preview=await f.api.preview({expectedSha256:f.sourceSha256,operations:[]})
 const message='字段 customer 的文本超出可见宽度；值和字体已保留。'
 vi.mocked(f.api.preview).mockResolvedValue({...preview,reviewIssues:[{operationIndex:0,kind:'setFormValue',fieldName:'customer',code:'pdf_form_text_overflow',message}]})
 f.draft.setOperations([{kind:'setFormValue',fieldId:'d'.repeat(64),expectedFieldSha256:'e'.repeat(64),name:'customer',fieldKind:'text',value:'Alice Updated'}])
 const button=[...f.root.querySelectorAll('button')].find(button=>button.textContent==='校验当前修改')!
 button.click()
 await vi.waitFor(()=>expect(f.root.textContent).toContain(message))
 expect(f.draft.operations[0]?.value).toBe('Alice Updated')
 expect(f.root.textContent).not.toContain('未执行，保留原文')
})

it('restored field rename keeps its full operation through source revalidation and confirmed actual preview',async()=>{
 const f=await fixture(true,{kind:'editFormWidget',newFieldName:'customer_full'},false,false,true)
 expect(f.draft.operations[0]).toMatchObject({kind:'editFormWidget',fieldName:'customer',newFieldName:'customer_full'})
 const review=f.root.querySelector<HTMLElement>('.pdf-preview-review')!
 review.scrollIntoView=vi.fn()
 await expect(f.view.prepareSave()).rejects.toThrow('请核对实际 PDF 预览')
 expect(review.hidden).toBe(false)
 const confirm=review.querySelector<HTMLInputElement>('input[type="checkbox"]')!
 confirm.checked=true;confirm.dispatchEvent(new Event('change'))
 await expect(f.view.prepareSave()).resolves.toEqual({confirmedPreviewDigest:'f'.repeat(64)})
 expect(f.draft.operations[0]?.newFieldName).toBe('customer_full')
})


it('restored dropdown options keep their full operation through source revalidation and confirmed actual preview',async()=>{
 const f=await fixture(true,{kind:'editFormWidget',choiceOptions:['Three','Two']},false,false,true,true)
 expect(f.draft.operations[0]).toMatchObject({kind:'editFormWidget',fieldName:'customer',choiceOptions:['Three','Two']})
 const review=f.root.querySelector<HTMLElement>('.pdf-preview-review')!
 review.scrollIntoView=vi.fn()
 await expect(f.view.prepareSave()).rejects.toThrow('请核对实际 PDF 预览')
 expect(review.hidden).toBe(false)
 const confirm=review.querySelector<HTMLInputElement>('input[type="checkbox"]')!
 confirm.checked=true;confirm.dispatchEvent(new Event('change'))
 await expect(f.view.prepareSave()).resolves.toEqual({confirmedPreviewDigest:'f'.repeat(64)})
 expect(f.draft.operations[0]?.choiceOptions).toEqual(['Three','Two'])
})


it('restored safe radio group rename keeps all sibling identities through source revalidation and actual preview confirmation',async()=>{
 const f=await fixture(true,{kind:'editFormWidget',newFieldName:'customer_full'},true,false,true,false,true)
 expect(f.draft.operations).toEqual([expect.objectContaining({kind:'editFormWidget',fieldName:'customer',widgetId:'7R',newFieldName:'customer_full'})])
 const review=f.root.querySelector<HTMLElement>('.pdf-preview-review')!
 review.scrollIntoView=vi.fn()
 await expect(f.view.prepareSave()).rejects.toThrow('请核对实际 PDF 预览')
 expect(review.hidden).toBe(false)
 const confirm=review.querySelector<HTMLInputElement>('input[type="checkbox"]')!
 confirm.checked=true;confirm.dispatchEvent(new Event('change'))
 await expect(f.view.prepareSave()).resolves.toEqual({confirmedPreviewDigest:'f'.repeat(64)})
 expect(f.draft.operations[0]?.newFieldName).toBe('customer_full')
})


it('restored whole radio required revalidates source siblings identities and preview confirmation',async()=>{
 const patch={kind:'editFormWidget',required:true}
 const f=await fixture(true,patch,true,false,true,false,false,true)
 expect(f.draft.operations).toEqual([expect.objectContaining({kind:'editFormWidget',required:true,fieldName:'customer',widgetId:'7R'})])
 const panel=f.root.querySelector<HTMLElement>('.pdf-preview-review')!;panel.scrollIntoView=vi.fn()
 await expect(f.view.prepareSave()).rejects.toThrow('请核对实际 PDF 预览')
 const confirm=panel.querySelector<HTMLInputElement>('input[type="checkbox"]')!;confirm.checked=true;confirm.dispatchEvent(new Event('change'))
 await expect(f.view.prepareSave()).resolves.toEqual({confirmedPreviewDigest:'f'.repeat(64)})
 for(const bad of [{sourceSha256:'f'.repeat(64)},{fieldName:'foreign'},{widgetId:'999R'},{widgetIdentity:'f'.repeat(64)},{expectedWidgetSha256:'f'.repeat(64)},{required:false},{rect:[25,25,125,49]},{newFieldName:'renamed'}]){
  await expect(fixture(true,{...patch,...bad},true,false,true,false,false,true)).rejects.toThrow()
 }
 await expect(fixture(true,patch,true,false,true,false,true,false)).rejects.toThrow()
})
