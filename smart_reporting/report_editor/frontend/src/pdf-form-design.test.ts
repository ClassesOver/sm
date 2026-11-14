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

it('opens on the close control and returns focus to the opener without changing the draft',()=>{
  const f=fixture(),opener=document.createElement('button');f.root.prepend(opener);opener.focus();f.panel.open()
  const close=f.panel.element.querySelector<HTMLButtonElement>('header button')!
  expect(close).not.toBeNull();expect(document.activeElement).toBe(close)
  close.click();expect(f.panel.element.hidden).toBe(true);expect(document.activeElement).toBe(opener)
  expect(f.draft.operations).toEqual([])
})

it('Escape closes but composition Escape keeps the panel and focus',()=>{
  const f=fixture(),opener=document.createElement('button');f.root.prepend(opener);opener.focus();f.panel.open()
  const button=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!;button.focus()
  button.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true,cancelable:true}))
  expect(f.panel.element.hidden).toBe(false);expect(document.activeElement).toBe(button)
  const escape=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true});button.dispatchEvent(escape)
  expect(f.panel.element.hidden).toBe(true);expect(escape.defaultPrevented).toBe(true);expect(document.activeElement).toBe(opener)
})

it.each(['composing','legacy229','consumed'])('preserves field design and focus for %s Escape',mode=>{
  const f=fixture(),opener=document.createElement('button');f.root.prepend(opener);opener.focus();f.panel.open()
  const button=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!;button.focus()
  if(mode==='consumed')button.addEventListener('keydown',event=>event.preventDefault(),{once:true})
  const event=new KeyboardEvent('keydown',{key:'Escape',isComposing:mode==='composing',keyCode:mode==='legacy229'?229:0,bubbles:true,cancelable:true})
  button.dispatchEvent(event)
  expect(f.panel.element.hidden).toBe(false);expect(document.activeElement).toBe(button)
  expect(f.draft.operations).toEqual([]);expect(f.refresh).not.toHaveBeenCalled()
  if(mode!=='consumed')expect(event.defaultPrevented).toBe(false)
  button.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))
  expect(f.panel.element.hidden).toBe(true);expect(document.activeElement).toBe(opener)
})

it('refresh retains the focused widget and falls back to close only when it becomes unavailable',()=>{
  const f=fixture();f.panel.open();f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!.focus()
  f.panel.refresh();expect(document.activeElement).toBe(f.root.querySelector('[data-pdf-form-widget-remove]'))
  f.setReason('只读修订');f.panel.refresh()
  expect(f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!.disabled).toBe(true)
  expect(document.activeElement).toBe(f.panel.element.querySelector('header button'))
  expect(f.draft.operations).toEqual([])
})

it('refresh and async staging never steal external focus',async()=>{
  const f=fixture(),outside=document.createElement('button');f.root.append(outside);f.panel.open()
  let complete!:()=>void;f.refresh.mockImplementation(()=>new Promise<void>(resolve=>{complete=resolve}))
  f.root.querySelector<HTMLButtonElement>('[data-pdf-form-widget-remove]')!.click()
  outside.focus();complete();await Promise.resolve();f.panel.refresh()
  expect(document.activeElement).toBe(outside);expect(f.draft.operations).toHaveLength(1)
})

it('identifies each action by field and page while keeping unsupported reasons separate',()=>{
  const f=fixture(),source=model(),widget=source.formDesignWidgets![0]!
  f.setModel({...source,formDesignWidgets:[widget,{...widget,widgetId:'8R',widgetIdentity:'d'.repeat(64),pageIndex:1,removable:false,removalReason:'共享控件'}]});f.panel.open()
  const buttons=f.root.querySelectorAll('[data-pdf-form-widget-remove]')
  expect(buttons[0].getAttribute('aria-label')).toBe('删除字段：customer（第1页，7R）')
  expect(buttons[1].getAttribute('aria-label')).toBe('删除字段：customer（第2页，8R）')
  expect(f.panel.element.querySelector('.pdf-form-design-reason')?.textContent).toBe('共享控件')
})

it('does not restore focus to a hidden or removed opener',()=>{
  for(const mode of ['hidden','removed']){
    const f=fixture(),opener=document.createElement('button');f.root.prepend(opener);opener.focus();f.panel.open()
    if(mode==='hidden')opener.hidden=true;else opener.remove()
    const focus=vi.spyOn(opener,'focus');f.panel.element.querySelector<HTMLButtonElement>('button')!.click()
    expect(focus).not.toHaveBeenCalled();expect(f.panel.element.hidden).toBe(true)
  }
})
