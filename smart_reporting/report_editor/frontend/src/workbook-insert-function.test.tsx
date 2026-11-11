import {expect,it,vi} from 'vitest'
import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {InsertFunctionFlow} from './workbook-function-flow'

it('uses the full source fallback catalog, filters category, opens parameter rows and cancels without writing',async()=>{
 const container=document.createElement('div');document.body.append(container)
 const root=createRoot(container),onClose=vi.fn(),host={write:vi.fn(()=>null),cancel:vi.fn(),evaluate:vi.fn(async()=>[]),observeRangePick:vi.fn(()=>()=>{}),listExternalPickTargets:vi.fn(async()=>[]),pickExternalRange:vi.fn(()=>()=>{})}
 const target={workbookCore:{},sheetCore:{},unitId:'b',sheetId:'s',sheetName:'S',row:0,col:0,label:'A1',formula:'',caret:0,editorText:null}
 try{
  flushSync(()=>root.render(<InsertFunctionFlow functions={[]} target={target} initialCategory="All" host={host as any} onClose={onClose}/>))
  expect(container.querySelectorAll('[role="option"]').length).toBeGreaterThan(50)
  const select=container.querySelector('select')!;select.value='Financial';flushSync(()=>select.dispatchEvent(new Event('change',{bubbles:true})))
  expect([...container.querySelectorAll('[role="option"]')].every(node=>/PMT|FV|PV|RATE|NPER|NPV|IRR/.test(node.textContent??''))).toBe(true)
  const first=container.querySelector('[role="option"]')!;flushSync(()=>first.dispatchEvent(new MouseEvent('dblclick',{bubbles:true})))
  expect(container.querySelector('.function-args-dialog')).not.toBeNull();expect(container.querySelectorAll('.fn-args-row').length).toBeGreaterThan(0)
  const cancel=[...container.querySelectorAll('button')].find(b=>b.textContent==='取消')!;flushSync(()=>cancel.click())
  expect(host.write).not.toHaveBeenCalled();expect(host.cancel).toHaveBeenCalledWith(target);expect(onClose).toHaveBeenCalledOnce()
 }finally{root.unmount();container.remove()}
})

it('creates and disposes in a headless host without querying unavailable injector services',async()=>{
 const {createWorkbookInsertFunction}=await import('./workbook-insert-function')
 const element=document.createElement('div');document.body.append(element)
 const runtime={univer:{},univerAPI:{getActiveWorkbook:()=>null}}
 const dialog=createWorkbookInsertFunction(element,{runtime,editable:()=>true,protectedSheet:()=>false,onWrite:vi.fn()})
 await dialog.open();dialog.dispose();dialog.dispose();expect(element.children).toHaveLength(0);element.remove()
})
it('binds native fx once after its provider appears and releases the late subscription',async()=>{
 const {createWorkbookInsertFunction}=await import('./workbook-insert-function')
 const element=document.createElement('div');document.body.append(element)
 let ready=false
 const unsubscribe=vi.fn(),subscribe=vi.fn(()=>({unsubscribe})),injector={has:()=>ready,get:()=>({fxBtnClick$:{subscribe}})}
 const runtime={univer:{__getInjector:()=>injector},univerAPI:{getActiveWorkbook:()=>null}}
 const dialog=createWorkbookInsertFunction(element,{runtime,editable:()=>true,protectedSheet:()=>false,onWrite:vi.fn()})
 expect(subscribe).not.toHaveBeenCalled();ready=true
 dialog.refresh();dialog.refresh();expect(subscribe).toHaveBeenCalledOnce()
 dialog.dispose();dialog.refresh();expect(unsubscribe).toHaveBeenCalledOnce();expect(subscribe).toHaveBeenCalledOnce();element.remove()
})
it('owns the physical formula fx click before Univer opens its implicit document editor and releases capture',async()=>{
 const {createWorkbookInsertFunction}=await import('./workbook-insert-function')
 const element=document.createElement('div');element.innerHTML='<div data-u-comp="formula-bar"><span><svg class="univerjs-icon-fx-icon"><path/></svg></span></div>';document.body.append(element)
 const native=vi.fn(),getActiveWorkbook=vi.fn(()=>null)
 element.querySelector('span')!.addEventListener('click',native)
 const dialog=createWorkbookInsertFunction(element,{runtime:{univer:{},univerAPI:{getActiveWorkbook}},editable:()=>true,protectedSheet:()=>false,onWrite:vi.fn()})
 element.querySelector('span')!.dispatchEvent(new MouseEvent('click',{bubbles:true}));await Promise.resolve()
 expect(getActiveWorkbook).toHaveBeenCalledOnce();expect(native).not.toHaveBeenCalled()
 dialog.dispose();element.querySelector('path')!.dispatchEvent(new MouseEvent('click',{bubbles:true}));expect(native).toHaveBeenCalledOnce();element.remove()
})
