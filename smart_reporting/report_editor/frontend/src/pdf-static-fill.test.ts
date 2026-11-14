import {expect,it,vi} from 'vitest'
import {pdfPageState,type PdfPageIdentity} from './pdf-operations'
import {NativeDraft} from './native-draft'
import {bindPdfStaticFill,missingRequiredFormFields,staticFillsForDraft} from './pdf-static-fill'
import {createPdfRibbon} from './pdf-ribbon'
const sha='a'.repeat(64),pageId=`sha256:${sha}:page:0`
const pages:PdfPageIdentity[]=[0,1].map(index=>({pageId:`sha256:${sha}:page:${index}`,index,rotation:0,cropBox:{x:10,y:20,width:300,height:400},mediaBox:{x:0,y:0,width:400,height:500}}))
const op={kind:'setStaticFill',sourceSha256:sha,pageId,id:'static-1',fillKind:'text',rect:[50,100,150,130],image:'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAGElEQVR4nAXBAQEAAAjDIN7c5hNEciOlBz3iB3usnU7kAAAAAElFTkSuQmCC',text:'中文',fontSize:14,color:'#111111',align:'left'}
it('static fills participate in real draft undo redo and page order mapping',()=>{
 expect(pdfPageState(pages,[op])).toEqual(pages)
 const draft=new NativeDraft({documentId:'d',revision:1,sourceSha256:sha,scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:()=>{},removeItem:()=>{}})
 draft.setOperations([op]);draft.undo();expect(draft.operations).toEqual([]);draft.redo();expect(draft.operations).toEqual([op])
 expect(pdfPageState(pages,[op,{kind:'reorderPages',pageIds:pages.map(p=>p.pageId).reverse()}]).map(p=>p.index)).toEqual([1,0])
})
it.each([{sourceSha256:'b'.repeat(64)},{rect:[0,0,50,60]},{fillKind:'signature'},{fontSize:0},{text:''},{align:'justify'},{extra:true}])('rejects invalid static filling %j',patch=>{expect(()=>pdfPageState(pages,[{...op,...patch}])).toThrow()})
it('exposes static Fill Form for a PDF without native AcroForm fields',()=>{const root=document.createElement('main'),ribbon=createPdfRibbon(root);ribbon.setHasForms(false,false,true);expect(root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=fillForm]')!.hidden).toBe(false);expect(root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=formDesign]')!.hidden).toBe(true);ribbon.dispose()})
it('required fields are a soft completion message and never discard the existing draft',()=>{
 const root=document.createElement('main');document.body.append(root);let message='',focused='';const model={sourceSha256:sha,pageCount:2,pages,formFields:[{name:'customer',kind:'text' as const,value:'',editable:true,fieldId:'f',expectedFieldSha256:'e'}],formDesignWidgets:[{fieldName:'customer',required:true,widgetId:'x',widgetIdentity:'x',expectedWidgetSha256:'x',pageIndex:0,rect:[20,20,30,30] as [number,number,number,number],removable:true,removalReason:null}],capabilities:{staticFill:true}}
 const draft=new NativeDraft({documentId:'d',revision:1,sourceSha256:sha,scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:()=>{},removeItem:()=>{}});draft.setOperations([op])
 const panel=bindPdfStaticFill({root,draft,model:()=>model,pages:()=>pages,getPage:async()=>{throw Error('unused')},unavailable:()=>null,start:()=>{},stop:()=>{},refresh:async()=>{},status:text=>message=text,focusField:name=>focused=name})
 panel.complete();expect(message).toContain('仍可保存/下载');expect(focused).toBe('customer');expect(draft.operations).toEqual([op]);expect(missingRequiredFormFields(model,[{kind:'setFormValue',name:'customer',value:'完成'}])).toEqual([]);panel.dispose();root.remove()
})
it('saved static fills preserve edit identity and disappear from the current view when their source page is deleted',()=>{
 const saved={id:'static-1',kind:'text' as const,pageIndex:0,rect:[50,100,150,130] as [number,number,number,number],text:'原值',fontSize:14,color:'#111111',align:'left' as const,editable:true,expectedImageSha256:'b'.repeat(64)},model={pages,staticFormFills:[saved]}
 expect(staticFillsForDraft(model,[{...op,expectedImageSha256:saved.expectedImageSha256}])[0]).toMatchObject({text:'中文',expectedImageSha256:saved.expectedImageSha256})
 expect(staticFillsForDraft(model,[{kind:'deletePage',pageId}])).toEqual([])
})
it('manager exposes explicit position and size editing for saved static marks',()=>{
 HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')};HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');this.dispatchEvent(new Event('close'))}
 const root=document.createElement('main');document.body.append(root);const model={sourceSha256:sha,pageCount:2,pages,staticFormFills:[{id:'saved-check',kind:'check' as const,pageIndex:0,rect:[40,100,52,112] as [number,number,number,number],editable:true,expectedImageSha256:'b'.repeat(64)}]}
 const draft=new NativeDraft({documentId:'geometry',revision:1,sourceSha256:sha,scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:()=>{},removeItem:()=>{}})
 const panel=bindPdfStaticFill({root,draft,model:()=>model,pages:()=>pages,getPage:async()=>{throw Error('unused')},unavailable:()=>null,start:()=>{},stop:()=>{},refresh:async()=>{},status:()=>{},focusField:()=>{}});panel.openManager();expect([...root.querySelectorAll('button')].some(button=>button.textContent==='调整位置/大小')).toBe(true);panel.dispose();root.remove()
})
it.each(['check','cross'] as const)('%s on an editable checkbox stages checked=true without a static mark',async kind=>{
 const root=document.createElement('main');document.body.append(root)
 const field={name:'accepted',kind:'checkbox' as const,value:false,editable:true,fieldId:'field-1',expectedFieldSha256:'f'.repeat(64)}
 const model={sourceSha256:sha,pageCount:2,pages,formFields:[field],formDesignWidgets:[{fieldName:field.name,fieldKind:'checkbox',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),pageIndex:0,rect:[20,20,30,30] as [number,number,number,number],removable:true,removalReason:null}],capabilities:{staticFill:true}}
 const draft=new NativeDraft({documentId:`checkbox-${kind}`,revision:1,sourceSha256:sha,scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:()=>{},removeItem:()=>{}})
 const context={scale(){},beginPath(){},moveTo(){},lineTo(){},stroke(){}} as unknown as CanvasRenderingContext2D
 const getContext=vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(context),toDataURL=vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,cG5n')
 const panel=bindPdfStaticFill({root,draft,model:()=>model,pages:()=>pages,getPage:async()=>{throw Error('checkbox hit must not inspect page content')},unavailable:()=>null,start:()=>{},stop:()=>{},refresh:async()=>{},status:()=>{},focusField:()=>{}})
 try{
  panel.mark(kind);await panel.place(pages[0]!,[25,25])
  expect(draft.operations).toEqual([{kind:'setFormValue',fieldId:field.fieldId,expectedFieldSha256:field.expectedFieldSha256,name:field.name,fieldKind:'checkbox',checked:true}])
  expect(draft.operations.some(operation=>operation.kind==='setStaticFill')).toBe(false)
 }finally{panel.dispose();root.remove();getContext.mockRestore();toDataURL.mockRestore()}
})
