import {afterEach,expect,it,vi} from 'vitest'
afterEach(()=>document.body.replaceChildren())
const captured=()=>({unitId:'book',sheetId:'sheet',workbookCore:{},sheetCore:{},range:{startRow:4,endRow:8,startColumn:2,endColumn:4},snapshotSignature:'snapshot',revision:1,fields:[{column:2,label:'地区'},{column:3,label:'金额'},{column:4,label:'<img src=x>'}]})
async function setup(apply=vi.fn().mockResolvedValue({addedRows:3})){
 const path='./workbook-subtotal-dialog'
 const {createSubtotalDialog}=await import(path)
 const dialog=createSubtotalDialog(document.body,apply)
 const target=captured();dialog.open(target)
 return {dialog,target,apply,overlay:document.querySelector<HTMLElement>('[role="dialog"]')!,form:document.querySelector('form')!}
}
it('shows captured column labels safely and submits absolute columns with aggregate',async()=>{
 const {dialog,target,apply,overlay,form}=await setup()
 target.fields[0].label='更改'
 expect(overlay.textContent).toContain('地区');expect(overlay.querySelector('img')).toBeNull()
 const group=overlay.querySelector<HTMLSelectElement>('[aria-label="分组列"]')!,value=overlay.querySelector<HTMLSelectElement>('[aria-label="汇总列"]')!,fn=overlay.querySelector<HTMLSelectElement>('[aria-label="汇总方式"]')!
 expect(group.value).toBe('2');expect(value.value).toBe('3')
 value.value='4';fn.value='count'
 form.dispatchEvent(new Event('submit',{cancelable:true}))
 await vi.waitFor(()=>expect(overlay.hidden).toBe(true))
 expect(apply).toHaveBeenCalledTimes(1)
 expect(apply.mock.calls[0][0].sheetCore).toBe(target.sheetCore)
 expect(apply.mock.calls[0][1]).toEqual({groupCol:2,valueCol:4,agg:'count'})
 dialog.dispose()
})
it('cancel, Escape and backdrop leave the captured sheet untouched',async()=>{
 const {dialog,target,apply,overlay}=await setup()
 overlay.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();expect(overlay.hidden).toBe(true)
 dialog.open(target);window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));expect(overlay.hidden).toBe(true)
 dialog.open(target);overlay.click();expect(overlay.hidden).toBe(true)
 expect(apply).not.toHaveBeenCalled();dialog.dispose()
})
it('keeps submission errors visible and blocks duplicate submits and dismissal during preflight',async()=>{
 let reject!:(error:Error)=>void
 const apply=vi.fn().mockImplementationOnce(()=>new Promise((_,fail)=>{reject=fail})).mockResolvedValue({addedRows:3})
 const {dialog,overlay,form}=await setup(apply)
 form.dispatchEvent(new Event('submit',{cancelable:true}));form.dispatchEvent(new Event('submit',{cancelable:true}))
 expect(apply).toHaveBeenCalledTimes(1);expect(overlay.getAttribute('aria-busy')).toBe('true')
 window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));overlay.click();expect(overlay.hidden).toBe(false)
 reject(new Error('来源已变化，请重新打开'))
 await vi.waitFor(()=>expect(overlay.querySelector('[role="alert"]')!.textContent).toContain('来源已变化'))
 expect(overlay.querySelector<HTMLButtonElement>('[type="submit"]')!.disabled).toBe(false)
 dialog.dispose();expect(document.querySelector('[role="dialog"]')).toBeNull()
})
it('refuses equal group and value columns before invoking execution',async()=>{
 const {dialog,apply,overlay,form}=await setup()
 overlay.querySelector<HTMLSelectElement>('[aria-label="汇总列"]')!.value='2'
 form.dispatchEvent(new Event('submit',{cancelable:true}))
 expect(apply).not.toHaveBeenCalled();expect(overlay.textContent).toContain('分组列与汇总列不能相同')
 dialog.dispose()
})
