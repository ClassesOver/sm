import {afterEach,expect,it,vi} from 'vitest'
import {createWorkbookWatchWindow} from './workbook-watch-window'
import {mountWorkbookRibbon} from './workbook-ribbon'
afterEach(()=>{vi.useRealTimers();document.body.replaceChildren()})
function fixture(){
 let name='S',value='7',formula='=A1+2',gone=false,identity={}
 const sheet={getMaxRows:()=>100,getMaxColumns:()=>100,getSheetId:()=> 'sheet',getSheetName:()=>name,getRange:()=>({getDisplayValue:()=>value,getFormula:()=>formula})}
 const workbook={getWorkbook:()=>identity,getActiveSheet:()=>sheet,getActiveRange:()=>({getRange:()=>({startRow:0,endRow:4,startColumn:0,endColumn:5})}),getSheetBySheetId:()=>gone?null:sheet}
 return {workbook,rename:()=>{name='Renamed';value='9'},remove:()=>{gone=true},restore:()=>{gone=false},replace:()=>{identity={}}}
}
it('preserves source per-add20, dedupe, live sheetId reads and closed list state',()=>{
 vi.useFakeTimers();const f=fixture(),panel=createWorkbookWatchWindow(document.body,()=>f.workbook)
 panel.toggle();const add=()=>document.querySelector<HTMLButtonElement>('[data-watch-add]')!.click()
 add();expect(document.querySelectorAll('[data-watch-row]')).toHaveLength(20)
 add();add();expect(document.querySelectorAll('[data-watch-row]')).toHaveLength(30)
 f.rename();vi.advanceTimersByTime(800);expect(document.querySelector('[data-watch-row]')!.textContent).toContain('RenamedA19=A1+2')
 f.remove();vi.advanceTimersByTime(800);expect(document.querySelectorAll('.watch-gone')).toHaveLength(30)
 f.restore();vi.advanceTimersByTime(800);expect(document.querySelectorAll('.watch-gone')).toHaveLength(0)
 panel.toggle();expect(vi.getTimerCount()).toBe(0);panel.toggle();expect(document.querySelectorAll('[data-watch-row]')).toHaveLength(30)
 document.querySelector<HTMLButtonElement>('[data-watch-remove]')!.click();expect(document.querySelectorAll('[data-watch-row]')).toHaveLength(29)
 f.replace();vi.advanceTimersByTime(800);expect(document.querySelectorAll('[data-watch-row]')).toHaveLength(0)
 panel.dispose();expect(vi.getTimerCount()).toBe(0);expect(document.querySelector('[data-watch-window]')).toBeNull()
})
it('keeps watch entry enabled on readonly protected sheets and reflects availability',()=>{
 let available=true;const command=vi.fn(),ribbon=mountWorkbookRibbon(document.body,command,{editable:()=>false,rotation:()=>0,protection:()=>({sheet:{protected:true},workbook:{locked:false}}),watchWindow:()=>({active:true,available})})
 document.querySelector<HTMLButtonElement>('[data-ribbon-tab="Formulas"]')!.click()
 const button=document.querySelector<HTMLButtonElement>('[data-ribbon-command="watch-window"]')!
 expect(button.disabled).toBe(false);expect(button.getAttribute('aria-pressed')).toBe('true');button.click();expect(command).toHaveBeenCalledWith('watch-window')
 available=false;ribbon.refreshState();expect(button.disabled).toBe(true);ribbon.dispose()
})
it('preserves focused controls across polling and marks shrunken coordinates unavailable',()=>{
 vi.useFakeTimers();let rows=10,value='1'
 const sheet={getSheetId:()=> 's',getSheetName:()=> 'S',getMaxRows:()=>rows,getMaxColumns:()=>10,getRange:vi.fn(()=>({getDisplayValue:()=>value,getFormula:()=>''}))}
 const workbook={getWorkbook:()=>sheet,getActiveSheet:()=>sheet,getActiveRange:()=>({getRange:()=>({startRow:5,endRow:5,startColumn:1,endColumn:1})}),getSheetBySheetId:()=>sheet}
 const panel=createWorkbookWatchWindow(document.body,()=>workbook);panel.toggle();document.querySelector<HTMLButtonElement>('[data-watch-add]')!.click()
 const remove=document.querySelector<HTMLButtonElement>('[data-watch-remove]')!;remove.focus();value='2';vi.advanceTimersByTime(800)
 expect(document.activeElement).toBe(remove);expect(document.querySelector('[data-watch-row]')!.textContent).toContain('2')
 sheet.getRange.mockClear();rows=3;vi.advanceTimersByTime(800);expect(sheet.getRange).not.toHaveBeenCalled();expect(document.querySelector('.watch-gone')).not.toBeNull()
 panel.dispose()
})
