import { afterEach, expect, it, vi } from 'vitest'
import { NativeDraft } from './native-draft'
import { bindPdfFormDesignPanel, stagePdfFormWidgetRemoval, type PdfFormDesignModel } from './pdf-form-design'
import { pdfPageState } from './pdf-operations'

afterEach(() => {document.body.replaceChildren();vi.restoreAllMocks()})

function model(): PdfFormDesignModel {
  return {sourceSha256:'a'.repeat(64),capabilities:{removeFormWidget:true},formDesignWidgets:[{fieldName:'customer',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),pageIndex:0,rect:[20,20,80,40],removable:true,removalReason:null}]}
}
function fixture() {
  const root=document.createElement('div');document.body.append(root)
  const draft=new NativeDraft({documentId:'doc',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:vi.fn(),removeItem:vi.fn()})
  let current=model(),reason:string|null=null
  const refresh=vi.fn(async()=>{})
  const panel=bindPdfFormDesignPanel({root,draft,model:()=>current,unavailable:()=>reason,refresh})
  return {root,draft,panel,refresh,setModel:(value:PdfFormDesignModel)=>{current=value},setReason:(value:string|null)=>{reason=value}}
}

it('stages one source-bound operation and existing NativeDraft undo/redo retains exact identity',()=>{
  const source=model(),next=stagePdfFormWidgetRemoval(source,[],source.formDesignWidgets![0]!.widgetIdentity)
  expect(next).toEqual([{kind:'removeFormWidget',sourceSha256:source.sourceSha256,fieldName:'customer',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64)}])
  expect(()=>stagePdfFormWidgetRemoval(source,next,'b'.repeat(64))).toThrow(/单独/)
  const f=fixture();f.draft.setOperations(next);f.draft.undo();expect(f.draft.operations).toEqual([]);f.draft.redo();expect(f.draft.operations).toEqual(next)
  const pages=[{pageId:'p',index:0,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:0,y:0,width:300,height:400},rotation:0}]
  expect(pdfPageState(pages,next)).toEqual(pages)
  expect(()=>pdfPageState(pages,[...next,{kind:'rotatePage',pageId:'p',delta:90}])).toThrow(/单独/)
})

it('field list stages through one actual NativeDraft transaction and refreshes',async()=>{
  const f=fixture();f.panel.open()
  const button=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!
  expect(button.disabled).toBe(false)
  button.click();await Promise.resolve()
  expect(f.draft.operations).toHaveLength(1);expect(f.refresh).toHaveBeenCalledTimes(1)
  expect(f.root.textContent).toContain('已加入草稿')
  f.draft.undo();f.panel.refresh();expect(f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!.disabled).toBe(false)
})

it('stale source/identity, blocked state and disposed callbacks never stage operations',()=>{
  for(const variant of ['source','identity','readonly','dispose']){
    const f=fixture();f.panel.open();const button=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!
    if(variant==='source')f.setModel({...model(),sourceSha256:'f'.repeat(64)})
    if(variant==='identity')f.setModel({...model(),formDesignWidgets:[{...model().formDesignWidgets![0]!,widgetIdentity:'f'.repeat(64)}]})
    if(variant==='readonly')f.setReason('只读修订')
    if(variant==='dispose')f.panel.dispose()
    button.dispatchEvent(new MouseEvent('click'))
    expect(f.draft.operations).toEqual([]);expect(f.refresh).not.toHaveBeenCalled()
  }
})

it('unsupported fields stay disabled and preview failure retains the staged draft',async()=>{
  const f=fixture();f.setModel({...model(),formDesignWidgets:[{...model().formDesignWidgets![0]!,removable:false,removalReason:'共享控件'}]});f.panel.open()
  expect(f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!.disabled).toBe(true)
  expect(f.root.textContent).toContain('共享控件')
  f.setModel(model());f.refresh.mockRejectedValueOnce(new Error('预览失败'));f.panel.refresh()
  f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!.click();await Promise.resolve();await Promise.resolve()
  expect(f.draft.operations).toHaveLength(1);expect(f.root.textContent).toContain('草稿已保留');expect(f.root.textContent).toContain('预览失败')
})
