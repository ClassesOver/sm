import {expect,it,vi} from 'vitest'
import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {InsertFunctionFlow} from './workbook-function-flow'
import {InsertFunctionDialog} from './workbook-function-catalog-dialog'

it('函数列表只有一个Tab入口，方向键与Home/End移动选择，分类变化清除旧选择',()=>{
 const container=document.createElement('div');document.body.append(container)
 const root=createRoot(container),pick=vi.fn()
 const catalog=['SUM','SUMIF','COUNT'].map((name,index)=>({name,category:index===2?'Statistical' as const:'Math' as const,syntax:name+'()',abstract:name,description:name,params:[]}))
 try{
  flushSync(()=>root.render(<InsertFunctionDialog targetLabel="A1" catalog={catalog} recent={[]} initialCategory="All" onPick={pick} onClose={vi.fn()}/>))
  const rows=()=>[...container.querySelectorAll<HTMLButtonElement>('[role="option"]')]
  expect(rows().map(node=>node.tabIndex)).toEqual([0,-1,-1])
  flushSync(()=>rows()[0]!.focus())
  const description=container.querySelector<HTMLElement>('.fn-syntax')!
  expect(description.getAttribute('role')).toBe('region');expect(description.getAttribute('aria-label')).toBe('函数说明');expect(description.tabIndex).toBe(0)
  const press=(key:string)=>flushSync(()=>document.activeElement!.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true})))
  press('ArrowDown');expect(document.activeElement).toBe(rows()[1]);expect(rows()[1]!.getAttribute('aria-selected')).toBe('true')
  press('End');expect(document.activeElement).toBe(rows()[2])
  press('ArrowDown');expect(document.activeElement).toBe(rows()[2])
  press('Home');expect(document.activeElement).toBe(rows()[0])
  press('ArrowUp');expect(document.activeElement).toBe(rows()[0])
  expect(pick).not.toHaveBeenCalled()
  const category=container.querySelector('select')!
  category.value='Statistical';flushSync(()=>category.dispatchEvent(new Event('change',{bubbles:true})))
  expect(rows()).toHaveLength(1);expect(rows()[0]!.tabIndex).toBe(0)
  const ok=container.querySelector<HTMLButtonElement>('.primary-action')!
  expect(ok.disabled).toBe(true)
  flushSync(()=>ok.click());expect(pick).not.toHaveBeenCalled()
  flushSync(()=>rows()[0]!.focus());expect(ok.disabled).toBe(false)
  flushSync(()=>ok.click());expect(pick).toHaveBeenCalledWith(catalog[2])
 }finally{root.unmount();container.remove()}
})

it.each([false,true])('函数目录提供具名结果区，空结果 %s 使用状态提示而非空列表框',empty=>{
 const container=document.createElement('div');document.body.append(container)
 const root=createRoot(container)
 const catalog=empty?[]:[{name:'SUM',category:'Math' as const,syntax:'SUM(number1)',abstract:'求和',description:'求和',params:[]}]
 try{
  flushSync(()=>root.render(<InsertFunctionDialog targetLabel="A1" catalog={catalog} recent={[]} initialCategory="All" onPick={vi.fn()} onClose={vi.fn()}/>))
  expect(container.querySelector('input')!.getAttribute('aria-label')).toBe('搜索函数')
  const results=container.querySelector('.fn-list')!
  expect(results.getAttribute('aria-label')).toBe('函数搜索结果')
  expect(results.getAttribute('role')).toBe(empty?'region':'listbox')
  if(empty){expect(results.querySelector('[role="status"]')!.textContent).toBe('没有匹配的函数。');expect(results.querySelector('[role="option"]')).toBeNull()}
  else {
   expect(results.querySelectorAll('[role="option"]')).toHaveLength(1)
   const category=container.querySelector('select')!
   category.value='Financial';flushSync(()=>category.dispatchEvent(new Event('change',{bubbles:true})))
   expect(results.getAttribute('role')).toBe('region');expect(results.querySelector('[role="status"]')!.textContent).toBe('没有匹配的函数。')
   category.value='All';flushSync(()=>category.dispatchEvent(new Event('change',{bubbles:true})))
   expect(results.getAttribute('role')).toBe('listbox');expect(results.querySelectorAll('[role="option"]')).toHaveLength(1)
  }
 }finally{root.unmount();container.remove()}
})

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
  const rangeToggle=container.querySelector<HTMLButtonElement>('.fn-args-pick')!
  expect(rangeToggle.getAttribute('aria-expanded')).toBe('true')
  expect(document.getElementById(rangeToggle.getAttribute('aria-controls')!)).not.toBeNull()
  flushSync(()=>rangeToggle.click());expect(rangeToggle.getAttribute('aria-expanded')).toBe('false')
  flushSync(()=>rangeToggle.click());expect(rangeToggle.getAttribute('aria-expanded')).toBe('true')
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
