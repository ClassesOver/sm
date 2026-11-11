import { afterEach, expect, it, vi } from 'vitest'
const path='./workbook-zoom-dialog'
async function product():Promise<any>{return import(/* @vite-ignore */ path)}
const disposables:{dispose():void}[]=[]
afterEach(()=>{disposables.splice(0).forEach(x=>x.dispose());document.body.replaceChildren()})
async function setup(percent=132){const p=await product(),command=vi.fn(),dialog=p.createWorkbookZoomDialog(document.body,command);disposables.push(dialog);dialog.open(percent);return {p,command,dialog,overlay:document.querySelector<HTMLElement>('.workbook-zoom-overlay')!,input:document.querySelector<HTMLInputElement>('[data-zoom-custom]')!}}
it('exposes all five source presets, fit and custom initialized from current percent',async()=>{
 const c=await setup();expect([...document.querySelectorAll<HTMLInputElement>('[name="workbook-zoom-choice"]')].map(x=>x.value)).toEqual(['200','100','75','50','25','fit','custom'])
 expect(c.input.value).toBe('132');expect(document.querySelector<HTMLInputElement>('[value="custom"]')!.checked).toBe(true)
 c.dialog.open(75);expect(document.querySelector<HTMLInputElement>('[value="75"]')!.checked).toBe(true)
 expect(c.command).not.toHaveBeenCalled()
})
it('dispatches preset or fit only on confirmation, and custom accepts only source integer range',async()=>{
 const c=await setup(100),apply=()=>document.querySelector<HTMLButtonElement>('[data-zoom-apply]')!.click()
 document.querySelector<HTMLInputElement>('[value="25"]')!.click();expect(c.command).not.toHaveBeenCalled();apply();expect(c.command).toHaveBeenLastCalledWith('zoom:25',undefined);expect(c.overlay.hidden).toBe(true)
 c.dialog.open(100);document.querySelector<HTMLInputElement>('[value="fit"]')!.click();apply();expect(c.command).toHaveBeenLastCalledWith('zoom-to-selection',undefined)
 for(const value of ['','9','401','125.5']){c.dialog.open(132);c.input.focus();c.input.value=value;c.input.dispatchEvent(new Event('input'));apply();expect(c.overlay.hidden).toBe(false);expect(document.querySelector('[role="alert"]')!.textContent).toContain('10–400')}
 c.input.value='137';c.input.dispatchEvent(new Event('input'));c.input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));expect(c.command).toHaveBeenLastCalledWith('zoom:137',undefined)
})
it('cancel, Escape, backdrop and Enter on Cancel never dispatch or mutate view state',async()=>{
 const c=await setup();document.querySelector<HTMLButtonElement>('[data-zoom-cancel]')!.click();expect(c.overlay.hidden).toBe(true)
 c.dialog.open(132);window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));expect(c.overlay.hidden).toBe(true)
 c.dialog.open(132);c.overlay.click();expect(c.overlay.hidden).toBe(true);expect(c.command).not.toHaveBeenCalled()
 c.dialog.open(132);const cancel=document.querySelector<HTMLButtonElement>('[data-zoom-cancel]')!;cancel.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));expect(c.command).not.toHaveBeenCalled()
})
it('source custom parser tolerates trailing percent and rejects fractional/outside values',async()=>{
 const {parseWorkbookZoomPercent:parse}=await product();for(const [raw,value]of [[' 125% ',125],['10',10],['400',400]])expect(parse(raw)).toBe(value)
 for(const raw of ['','NaN','0','401','12.5','100%%'])expect(()=>parse(raw)).toThrow()
})

function runtime() {
 let zoom=1;const core={},sheetCore={},sheet={getSheet:()=>sheetCore,getSheetId:()=> 's',getZoom:()=>zoom}
 const book={getWorkbook:()=>core,getId:()=> 'b',getActiveSheet:()=>sheet}
 const executeCommand=vi.fn(async(_id:string,params:any)=>{zoom=params.zoomRatio;return true})
 const r:any={univerAPI:{getActiveWorkbook:()=>book,executeCommand}}
 return {r,book,sheet,executeCommand,setZoom:(value:number)=>{zoom=value}}
}
it('captures native workbook/sheet identities and rejects late dialog callbacks before applying to another target',async()=>{
 const c=runtime(),p=await product(),target=p.captureWorkbookZoomTarget(c.r)
 expect(p.isWorkbookZoomTargetCurrent(c.r,target)).toBe(true)
 c.r.univerAPI.getActiveWorkbook=()=>({...c.book,getActiveSheet:()=>({...c.sheet,getSheet:()=>({})})})
 expect(await p.applyWorkbookZoomPercent(c.r,125,target)).toMatchObject({changed:false})
 expect(c.executeCommand).not.toHaveBeenCalled()
 const d=await setup();d.dialog.open(100,target);document.querySelector<HTMLInputElement>('[value="50"]')!.click();document.querySelector<HTMLButtonElement>('[data-zoom-apply]')!.click()
 expect(d.command).toHaveBeenLastCalledWith('zoom:50',target)
})
it('applies observed percent regardless of protection and reports same value without dirtying',async()=>{
 const c=runtime(),p=await product()
 expect(await p.applyWorkbookZoomPercent(c.r,125)).toMatchObject({changed:true,percent:125})
 expect(c.executeCommand).toHaveBeenCalledWith('sheet.command.set-zoom-ratio',{unitId:'b',subUnitId:'s',zoomRatio:1.25})
 expect(await p.applyWorkbookZoomPercent(c.r,125)).toMatchObject({changed:false,percent:125})
 c.executeCommand.mockImplementation(async()=>false as any)
 expect(await p.applyWorkbookZoomPercent(c.r,200)).toMatchObject({changed:false})
 c.executeCommand.mockImplementation(async()=>{c.setZoom(2);throw new Error('receipt')})
 expect(await p.applyWorkbookZoomPercent(c.r,200)).toMatchObject({changed:true,percent:200})
 c.executeCommand.mockImplementation(async()=>{c.r.univerAPI.getActiveWorkbook=()=>null;return true})
 expect(await p.applyWorkbookZoomPercent(c.r,50)).toMatchObject({changed:false})
})

it('drops detached modal callbacks after disposal and never reopens removed UI',async()=>{
 const c=await setup(100),form=document.querySelector<HTMLFormElement>('.workbook-zoom-dialog form')!
 c.dialog.dispose();form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));c.dialog.open(200)
 expect(c.command).not.toHaveBeenCalled();expect(document.querySelector('.workbook-zoom-overlay')).toBeNull()
})
