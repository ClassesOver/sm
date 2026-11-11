import {afterEach,expect,it,vi} from 'vitest'
const path='./workbook-print-scale'
const product=():Promise<any>=>import(/* @vite-ignore */path)
const disposables:{dispose():void}[]=[]
afterEach(()=>{disposables.splice(0).forEach(x=>x.dispose());document.body.replaceChildren()})
it('accepts only integer print percentages and preserves unrelated fit and page settings',async()=>{
 const p=await product();for(const value of ['','9','401','12.5','NaN','85%'])expect(()=>p.parsePrintScale(value)).toThrow(/10–400/)
 for(const n of [10,85,100,400])expect(p.parsePrintScale(String(n))).toBe(n)
 const baseline={scale:85,fitToPage:true,fitToWidth:2,fitToHeight:3,orientation:'landscape'},patch={margins:'wide',scale:90}
 expect(p.printScaleState(baseline,patch)).toEqual({scale:90,fitToPage:true})
 expect(p.printScalePatch(baseline,patch,90)).toEqual({...patch,scale:90,fitToPage:false})
 expect(p.printScalePatch(baseline,{...patch,fitToPage:false},90)).toBeUndefined()
 expect(p.printScaleState(undefined,undefined)).toEqual({scale:100,fitToPage:false})
 expect(baseline).toEqual({scale:85,fitToPage:true,fitToWidth:2,fitToHeight:3,orientation:'landscape'})
})
it('opens from trusted state, confirms once and leaves cancel invalid inputs and disposed forms inert',async()=>{
 const p=await product(),apply=vi.fn(),dialog=p.createPrintScaleDialog(document.body,apply);disposables.push(dialog)
 const target={book:{},sheet:{},sheetId:'s'};dialog.open({scale:85,fitToPage:true},target)
 const form=document.querySelector<HTMLFormElement>('.workbook-print-scale-dialog form')!,input=form.querySelector<HTMLInputElement>('input')!,submit=()=>form.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))
 expect(input.value).toBe('85');expect(form.textContent).toMatch(/打印|合适/);input.value='125.5';submit();expect(apply).not.toHaveBeenCalled();expect(form.querySelector('[role="alert"]')!.textContent).toMatch(/10–400/)
 input.value='400';submit();expect(apply).toHaveBeenCalledExactlyOnceWith(400,target)
 dialog.open({scale:90,fitToPage:false},target);document.querySelector<HTMLButtonElement>('[data-print-scale-cancel]')!.click();expect(apply).toHaveBeenCalledTimes(1)
 dialog.open({scale:100,fitToPage:false},target);window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));expect(apply).toHaveBeenCalledTimes(1)
 dialog.dispose();submit();dialog.open({scale:100,fitToPage:false},target);expect(apply).toHaveBeenCalledTimes(1);expect(document.querySelector('.workbook-print-scale-dialog')).toBeNull()
})
