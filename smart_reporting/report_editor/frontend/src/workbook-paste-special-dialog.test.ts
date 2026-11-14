import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createWorkbookPasteSpecial} from './workbook-paste-special'
let cleanup:(()=>void)|undefined,clipboard:PropertyDescriptor|undefined
beforeEach(()=>{clipboard=Object.getOwnPropertyDescriptor(navigator,'clipboard')})
afterEach(()=>{cleanup?.();cleanup=undefined;document.body.replaceChildren();if(clipboard)Object.defineProperty(navigator,'clipboard',clipboard);else Reflect.deleteProperty(navigator,'clipboard')})
function fixture(){
 const root=document.createElement('main');document.body.append(root);let column=2,enabled=true,message=''
 const range={getRange:()=>({startRow:2,endRow:2,startColumn:column,endColumn:column})}
 const sheet={getSheetId:()=> 's'},workbook={getId:()=> 'u',getActiveSheet:()=>sheet,getActiveRange:()=>range,isCellEditing:()=>false}
 const executeCommand=vi.fn(async()=>true),changed=vi.fn(),runtime={univer:{__getInjector:()=>({get:()=>({_copyContentCache:{getLastCopyId:()=>null}})})},univerAPI:{getActiveWorkbook:()=>workbook,executeCommand}} as any
 Object.defineProperty(navigator,'clipboard',{configurable:true,value:{read:vi.fn(async()=>[{types:['text/plain'],getType:async()=>({text:async()=> '7'})}])}})
 const panel=createWorkbookPasteSpecial(root,{runtime,editable:()=>enabled,onMessage:text=>message=text,onChange:changed});cleanup=()=>panel.dispose()
 const buttons=()=>[...root.querySelectorAll<HTMLButtonElement>('button')]
 return {root,panel,executeCommand,changed,buttons,get message(){return message},move:()=>column++,lock:()=>enabled=false}
}
it('opens the full source dialog for outside text and cancels without executing or changing the draft',async()=>{
 const f=fixture();await f.panel.open();expect(f.root.querySelectorAll('input[type=radio][name=paste-special-type]')).toHaveLength(12)
 const typeInputs=[...f.root.querySelectorAll<HTMLInputElement>('input[name=paste-special-type]')];expect(typeInputs.filter(x=>!x.disabled).map(x=>x.value)).toEqual(['all','values'])
 f.buttons().find(button=>button.textContent==='取消')!.click();expect(f.executeCommand).not.toHaveBeenCalled();expect(f.changed).not.toHaveBeenCalled();expect(f.root.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(true)
})
it('rejects a changed active target before applying, retaining the visible dialog and existing draft',async()=>{
 const f=fixture();await f.panel.open();f.move();f.buttons().find(button=>button.textContent==='确定')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector('[role=alert]')?.textContent).toMatch(/目标区域/));expect(f.executeCommand).not.toHaveBeenCalled();expect(f.changed).not.toHaveBeenCalled()
})
it('keeps the dialog open on command false and only marks an actual write as changed',async()=>{
 const f=fixture();f.executeCommand.mockResolvedValue(false);await f.panel.open();f.buttons().find(button=>button.textContent==='确定')!.click()
 await vi.waitFor(()=>expect(f.root.querySelector('[role=alert]')?.textContent).toMatch(/未应用/));expect(f.changed).not.toHaveBeenCalled();expect(f.root.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(false)
 f.executeCommand.mockResolvedValue(true);f.buttons().find(button=>button.textContent==='确定')!.click();await vi.waitFor(()=>expect(f.changed).toHaveBeenCalledOnce())
})
it('does not open a late clipboard response after target changes, Escape cancellation, disposal or readonly transition',async()=>{
 for(const action of ['move','escape','dispose','lock']){
  const f=fixture();let resolve!:(value:any)=>void;Object.defineProperty(navigator,'clipboard',{configurable:true,value:{read:()=>new Promise(r=>resolve=r)}})
  const pending=f.panel.open();if(action==='move')f.move();if(action==='escape')f.root.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));if(action==='dispose')f.panel.dispose();if(action==='lock')f.lock()
  resolve([{types:['text/plain'],getType:async()=>({text:async()=> '7'})}]);await pending;expect(f.root.querySelector<HTMLElement>('[role=dialog]')?.hidden??true).toBe(true);expect(f.executeCommand).not.toHaveBeenCalled();f.panel.dispose();f.root.remove()
 }
})
it('preserves composition Escape and uses Ctrl+Alt+V only in an editable grid',async()=>{
 const f=fixture();f.root.dispatchEvent(new KeyboardEvent('keydown',{key:'v',ctrlKey:true,altKey:true,bubbles:true,cancelable:true}));await vi.waitFor(()=>expect(f.root.querySelector<HTMLElement>('[role=dialog]')?.hidden).toBe(false))
 f.root.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true,cancelable:true}));expect(f.root.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(false)
 f.root.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));expect(f.root.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(true);f.lock();f.root.dispatchEvent(new KeyboardEvent('keydown',{key:'v',ctrlKey:true,altKey:true,bubbles:true,cancelable:true}));expect(f.root.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(true)
})
