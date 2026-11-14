import {afterEach,expect,it,vi} from 'vitest'
import {createPdfSidebarSizing} from './pdf-sidebar'

const controllers:ReturnType<typeof createPdfSidebarSizing>[]=[]
afterEach(()=>{controllers.splice(0).forEach(controller=>controller.dispose());document.body.replaceChildren();localStorage.clear()})
function fixture(){
 localStorage.setItem('genoffice-pdf-sidebar-width','150')
 const divider=document.createElement('div'),panel=document.createElement('aside');panel.id='sidebar-keyboard-test';document.body.append(divider,panel)
 const widths=vi.fn(),controller=createPdfSidebarSizing(divider,widths);controllers.push(controller);controller.setPanel(panel)
 return {divider,controller,widths}
}
function pointer(target:EventTarget,type:string,x:number){const event=new MouseEvent(type,{bubbles:true,cancelable:true,button:0,clientX:x});Object.defineProperties(event,{pointerId:{value:1},isPrimary:{value:true}});target.dispatchEvent(event)}
for(const key of ['ArrowLeft','ArrowRight','Home','End'])it.each(['composing','legacy229','consumed'] as const)(`${key} %s leaves sidebar width and preference unchanged`,mode=>{
 const f=fixture()
 if(mode==='consumed')f.divider.addEventListener('keydown',event=>event.preventDefault(),{capture:true})
 f.divider.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,isComposing:mode==='composing',keyCode:mode==='legacy229'?229:0}))
 expect(f.controller.width).toBe(150);expect(localStorage.getItem('genoffice-pdf-sidebar-width')).toBe('150');expect(f.widths).toHaveBeenCalledTimes(1)
})
it.each(['composing','legacy229','consumed'] as const)('keeps sidebar drag after %s Escape and persists release width',mode=>{
 const f=fixture(),control=document.createElement('input');document.body.append(control)
 if(mode==='consumed')control.addEventListener('keydown',event=>event.preventDefault())
 pointer(f.divider,'pointerdown',150);pointer(window,'pointermove',190)
 control.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true,isComposing:mode==='composing',keyCode:mode==='legacy229'?229:27}))
 pointer(window,'pointerup',190)
 expect(f.controller.width).toBe(190);expect(localStorage.getItem('genoffice-pdf-sidebar-width')).toBe('190');expect(f.widths.mock.calls.filter(call=>call[1])).toEqual([[190,true]])
})
it('ordinary Escape cancels sidebar drag without persisting preview width',()=>{
 const f=fixture();pointer(f.divider,'pointerdown',150);pointer(window,'pointermove',190)
 f.divider.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));pointer(window,'pointerup',190)
 expect(f.controller.width).toBe(150);expect(localStorage.getItem('genoffice-pdf-sidebar-width')).toBe('150');expect(f.widths.mock.calls.filter(call=>call[1])).toEqual([])
 expect(document.body.style.cursor).toBe('');expect(document.body.style.userSelect).toBe('')
})
it('ordinary sidebar navigation persists exact widths and stops after disposal',()=>{
 const f=fixture()
 for(const [key,width]of [['End',320],['Home',120],['ArrowRight',130],['ArrowLeft',120]] as const){f.divider.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}));expect(f.controller.width).toBe(width);expect(localStorage.getItem('genoffice-pdf-sidebar-width')).toBe(String(width))}
 f.controller.dispose();f.divider.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true,cancelable:true}));expect(f.controller.width).toBe(120)
})
