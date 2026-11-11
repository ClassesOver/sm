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
