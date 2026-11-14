import {afterEach,expect,it,vi} from 'vitest'
afterEach(()=>document.body.replaceChildren())
const captured=()=>({unitId:'book',sheetId:'sheet',workbookCore:{},sheetCore:{},range:{startRow:4,endRow:9,startColumn:2,endColumn:4},snapshotSignature:'snapshot',selectionSignature:'selection',filterSignature:'null',revision:1,fields:[{colId:0,label:'地区'},{colId:1,label:'<img src=x>'}]})
async function setup(apply=vi.fn().mockResolvedValue({})){
 const path='./workbook-advanced-filter-dialog';const {createAdvancedFilterDialog}=await import(path),dialog=createAdvancedFilterDialog(document.body,apply),target=captured();dialog.open(target)
 return {dialog,target,apply,overlay:document.querySelector<HTMLElement>('[role="dialog"]')!,form:document.querySelector('form')!}
}
it('uses safe captured labels and preserves untrimmed string conditions',async()=>{
 const {dialog,target,apply,overlay,form}=await setup();target.fields[0].label='changed'
 expect(overlay.textContent).toContain('地区');expect(overlay.querySelector('img')).toBeNull()
 overlay.querySelector<HTMLSelectElement>('[aria-label="高级筛选字段"]')!.value='1'
 overlay.querySelector<HTMLInputElement>('[aria-label="第一条件值"]')!.value=' A '
 form.dispatchEvent(new Event('submit',{cancelable:true}));await vi.waitFor(()=>expect(overlay.hidden).toBe(true))
 expect(apply).toHaveBeenCalledTimes(1);expect(apply.mock.calls[0][0].sheetCore).toBe(target.sheetCore)
 expect(apply.mock.calls[0][1]).toEqual({colId:1,operator1:'equal',value1:' A ',operator2:'equal',value2:'',and:true});dialog.dispose()
})
it('cancel Escape and backdrop are read-only and an empty first value is refused',async()=>{
 const {dialog,target,apply,overlay,form}=await setup();form.dispatchEvent(new Event('submit',{cancelable:true}));expect(overlay.textContent).toContain('第一筛选条件');expect(apply).not.toHaveBeenCalled()
 overlay.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();expect(overlay.hidden).toBe(true)
 dialog.open(target);window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));expect(overlay.hidden).toBe(true)
 dialog.open(target);overlay.click();expect(overlay.hidden).toBe(true);expect(apply).not.toHaveBeenCalled();dialog.dispose()
})
it('busy blocks duplicate/dismiss, failure stays open and allows retry',async()=>{
 let reject!:(error:Error)=>void;const apply=vi.fn().mockImplementationOnce(()=>new Promise((_,fail)=>{reject=fail})).mockResolvedValue({})
 const {dialog,overlay,form}=await setup(apply);overlay.querySelector<HTMLInputElement>('[aria-label="第一条件值"]')!.value='A'
 form.dispatchEvent(new Event('submit',{cancelable:true}));form.dispatchEvent(new Event('submit',{cancelable:true}));expect(apply).toHaveBeenCalledTimes(1)
 window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));overlay.click();expect(overlay.hidden).toBe(false)
 reject(new Error('筛选失败'));await vi.waitFor(()=>expect(overlay.querySelector('[role="alert"]')!.textContent).toContain('筛选失败'))
 expect(overlay.hidden).toBe(false);form.dispatchEvent(new Event('submit',{cancelable:true}));await vi.waitFor(()=>expect(overlay.hidden).toBe(true));expect(apply).toHaveBeenCalledTimes(2);dialog.dispose()
})
it('keeps the heading and actions outside the scrollable fields and names reading regions',async()=>{
 const {dialog,overlay}=await setup(),card=overlay.querySelector('.modal-card')!
 expect(card.querySelector(':scope > header h2')?.textContent).toBe('高级筛选')
 expect(card.querySelector(':scope > form > footer button[type="submit"]')).not.toBeNull()
 for(const label of ['高级筛选说明','高级筛选范围','高级筛选状态','高级筛选错误']){
  const region=card.querySelector<HTMLElement>(`[aria-label="${label}"]`)
  expect(region,`${label}须可单独聚焦阅读`).not.toBeNull();expect(region?.tabIndex).toBe(0)
 }
 dialog.dispose()
})
it('focuses readable busy status and carries focus to failure while preserving the condition',async()=>{
 let reject!:(error:Error)=>void
 const {dialog,overlay,form}=await setup(vi.fn(()=>new Promise((_,fail)=>{reject=fail})))
 const value=overlay.querySelector<HTMLInputElement>('[aria-label="第一条件值"]')!,status=overlay.querySelector<HTMLElement>('[role="status"]')!,error=overlay.querySelector<HTMLElement>('[role="alert"]')!
 value.value=' A ';form.dispatchEvent(new Event('submit',{cancelable:true}))
 expect(status).not.toBeNull();expect(status?.textContent).toContain('正在筛选');expect(document.activeElement).toBe(status)
 reject(new Error('范围已变化'));await vi.waitFor(()=>expect(error.textContent).toBe('范围已变化'))
 expect(document.activeElement).toBe(error);expect(status.textContent).toBe('');expect(value.value).toBe(' A ');expect(value.disabled).toBe(false)
 dialog.dispose()
})
it('reveals validation feedback without stealing the input focus',async()=>{
 const {dialog,overlay,form,apply}=await setup(),value=overlay.querySelector<HTMLInputElement>('[aria-label="第一条件值"]')!,error=overlay.querySelector<HTMLElement>('[role="alert"]')!
 const reveal=vi.fn();error.scrollIntoView=reveal;value.focus();form.dispatchEvent(new Event('submit',{cancelable:true}))
 expect(error.textContent).toBe('请填写第一筛选条件');expect(reveal).toHaveBeenCalledWith({block:'nearest'});expect(document.activeElement).toBe(value);expect(apply).not.toHaveBeenCalled()
 dialog.dispose()
})
