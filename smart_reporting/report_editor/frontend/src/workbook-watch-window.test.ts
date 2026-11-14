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
it.each(['composition','legacy','handled'])('监视窗口保留受保护的阅读与关闭按键：%s',protection=>{
 vi.useFakeTimers();const f=fixture(),entry=document.body.appendChild(document.createElement('button')),panel=createWorkbookWatchWindow(document.body,()=>f.workbook)
 entry.focus();panel.toggle()
 try{
  const scroll=document.querySelector<HTMLElement>('.watch-scroll')!;Object.defineProperty(scroll,'scrollHeight',{value:800});scroll.scrollTop=120;scroll.focus()
  for(const key of ['Escape','Home','End']){
   const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,isComposing:protection==='composition',keyCode:protection==='legacy'?229:0})
   if(protection==='handled')event.preventDefault()
   scroll.dispatchEvent(event);expect(panel.state().active).toBe(true);expect(scroll.scrollTop).toBe(120);expect(document.activeElement).toBe(scroll)
  }
  scroll.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true,cancelable:true}));expect(scroll.scrollTop).toBe(800)
  scroll.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));expect(panel.state().active).toBe(false);expect(document.activeElement).toBe(entry)
 }finally{panel.dispose()}
})
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
it('失效来源显示明确状态，恢复后原行与删除焦点保持',()=>{
 vi.useFakeTimers();const f=fixture(),panel=createWorkbookWatchWindow(document.body,()=>f.workbook);panel.toggle();document.querySelector<HTMLButtonElement>('[data-watch-add]')!.click()
 const row=document.querySelector<HTMLTableRowElement>('[data-watch-row]')!,remove=row.querySelector<HTMLButtonElement>('button')!;remove.focus()
 f.remove();vi.advanceTimersByTime(800)
 expect(row.cells[0]!.textContent).toBe('来源不可用');expect(row.cells[1]!.textContent).toBe('A1');expect(row.cells[2]!.textContent).toBe('');expect(row.cells[3]!.textContent).toBe('');expect(document.activeElement).toBe(remove)
 f.restore();vi.advanceTimersByTime(800)
 expect(document.querySelector('[data-watch-row]')).toBe(row);expect(row.cells[0]!.textContent).toBe('S');expect(row.cells[2]!.textContent).toBe('7');expect(row.classList.contains('watch-gone')).toBe(false);expect(document.activeElement).toBe(remove)
 panel.dispose()
})
it('打开聚焦添加监视，输入法Escape不关闭，普通Escape关闭并返回入口',()=>{
 vi.useFakeTimers();const f=fixture(),entry=document.body.appendChild(document.createElement('button')),read=vi.fn(()=>f.workbook),panel=createWorkbookWatchWindow(document.body,read)
 entry.focus();panel.toggle();const add=document.querySelector<HTMLButtonElement>('[data-watch-add]')!
 expect(document.activeElement).toBe(add)
 add.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true}));expect(panel.state().active).toBe(true)
 add.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(panel.state().active).toBe(false);expect(document.activeElement).toBe(entry)
 read.mockClear();vi.advanceTimersByTime(800);expect(read).not.toHaveBeenCalled()
 panel.dispose()
})
it('入口随Ribbon切换隐藏后，标题关闭返回当前标签',()=>{
 vi.useFakeTimers();const f=fixture(),entry=document.body.appendChild(document.createElement('button')),tab=document.body.appendChild(document.createElement('button'))
 tab.setAttribute('role','tab');tab.setAttribute('aria-selected','true');tab.dataset.ribbonTab='Home'
 const panel=createWorkbookWatchWindow(document.body,()=>f.workbook);entry.focus();panel.toggle();entry.hidden=true
 document.querySelector<HTMLButtonElement>('[data-watch-close]')!.click();expect(document.activeElement).toBe(tab);panel.dispose()
})
it('键盘删除后焦点落在邻近监视项，删除最后一项返回添加按钮',()=>{
 vi.useFakeTimers();const f=fixture(),panel=createWorkbookWatchWindow(document.body,()=>f.workbook);panel.toggle();document.querySelector<HTMLButtonElement>('[data-watch-add]')!.click()
 const remove=()=>[...document.querySelectorAll<HTMLButtonElement>('[data-watch-remove]')]
 const first=remove()[0]!,next=remove()[1]!;first.focus();first.click();expect(document.activeElement).toBe(next)
 const last=remove().at(-1)!,previous=remove().at(-2)!;last.focus();last.click();expect(document.activeElement).toBe(previous)
 while(remove().length>1)remove()[0]!.click()
 remove()[0]!.focus();remove()[0]!.click();expect(document.activeElement).toBe(document.querySelector('[data-watch-add]'));panel.dispose()
})
it('监视表格可键盘阅读首尾，不接管组合键，销毁不抢夺外部焦点',()=>{
 vi.useFakeTimers();const f=fixture(),panel=createWorkbookWatchWindow(document.body,()=>f.workbook);panel.toggle()
 const scroll=document.querySelector<HTMLElement>('.watch-scroll')!;expect(scroll.tabIndex).toBe(0)
 Object.defineProperty(scroll,'scrollHeight',{value:500});Object.defineProperty(scroll,'clientHeight',{value:100})
 const press=(key:string,options:KeyboardEventInit={})=>{const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,...options});scroll.dispatchEvent(event);return event}
 expect(press('End').defaultPrevented).toBe(true);expect(scroll.scrollTop).toBe(500)
 expect(press('Home',{ctrlKey:true}).defaultPrevented).toBe(false);expect(scroll.scrollTop).toBe(500)
 expect(press('Home').defaultPrevented).toBe(true);expect(scroll.scrollTop).toBe(0)
 const outside=document.body.appendChild(document.createElement('button'));outside.focus();panel.dispose();expect(document.activeElement).toBe(outside)
})
it('无选区时初始焦点及删除末项后的焦点避开禁用添加按钮',()=>{
 vi.useFakeTimers();const f=fixture();let selected=false
 const workbook={...f.workbook,getActiveRange:()=>selected?{getRange:()=>({startRow:0,endRow:0,startColumn:0,endColumn:0})}:null}
 const panel=createWorkbookWatchWindow(document.body,()=>workbook);panel.toggle()
 const close=document.querySelector<HTMLButtonElement>('[data-watch-close]')!,add=document.querySelector<HTMLButtonElement>('[data-watch-add]')!
 expect(add.disabled).toBe(true);expect(document.activeElement).toBe(close)
 selected=true;vi.advanceTimersByTime(800);add.click();selected=false;vi.advanceTimersByTime(800)
 const remove=document.querySelector<HTMLButtonElement>('[data-watch-remove]')!;remove.focus();remove.click();expect(document.activeElement).toBe(close);panel.dispose()
})
