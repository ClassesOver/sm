import {afterEach, expect, it, vi} from 'vitest'
import {mountSlidesRailNavigation} from './slides-rail-navigation'
const disposers:Array<()=>void>=[]
const scrollDescriptor=Object.getOwnPropertyDescriptor(HTMLButtonElement.prototype,'scrollIntoView')
afterEach(()=>{disposers.splice(0).forEach(dispose=>dispose());document.body.replaceChildren();if(scrollDescriptor)Object.defineProperty(HTMLButtonElement.prototype,'scrollIntoView',scrollDescriptor);else delete (HTMLButtonElement.prototype as unknown as {scrollIntoView?:unknown}).scrollIntoView})
function fixture(ids=[7,2,19]) {
 const list=document.body.appendChild(document.createElement('ol'));let current=ids[0]!,enabled=true,blocked=false
 const error=document.body.appendChild(document.createElement('input'))
 const open=vi.fn((id:number)=>{if(blocked){error.focus();return}current=id;render()})
 const render=()=>{list.replaceChildren();for(const id of ids){const row=document.createElement('li'),button=document.createElement('button');button.className='slide-open';button.dataset.slideIndex=String(id);button.textContent=String(id);button.onclick=()=>open(id);row.append(button);list.append(row)}}
 render();const nav=mountSlidesRailNavigation(list,{enabled:()=>enabled,current:()=>current});disposers.push(()=>nav.dispose())
 const button=(id:number)=>list.querySelector<HTMLButtonElement>(`[data-slide-index="${id}"]`)!
 const press=(key:string,extra:KeyboardEventInit={})=>{const e=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,...extra});document.activeElement!.dispatchEvent(e);return e}
 button(current).focus();return{list,open,button,press,error,nav,current:()=>current,setCurrent:(id:number)=>{current=id},enable:(v:boolean)=>{enabled=v},block:(v:boolean)=>{blocked=v}}
}
it('navigates latest DOM order, focuses recreated buttons and consumes boundaries without another click',()=>{
 const app=fixture();expect(app.press('ArrowDown').defaultPrevented).toBe(true);expect(app.current()).toBe(2);expect(document.activeElement).toBe(app.button(2))
 app.press('PageDown');expect(app.current()).toBe(19);app.press('End');expect(app.open).toHaveBeenCalledTimes(2)
 app.press('Home');expect(app.current()).toBe(7);app.press('PageUp');expect(app.open).toHaveBeenCalledTimes(3)
 app.list.append(app.button(2).parentElement!);app.press('End');expect(app.current()).toBe(2)
})
it('computes from selected not Tab focus, and never steals the error focus after a notes veto',()=>{
 const app=fixture();app.setCurrent(2);app.button(7).focus();app.block(true);app.press('ArrowDown');expect(app.open).toHaveBeenCalledWith(19);expect(app.current()).toBe(2);expect(document.activeElement).toBe(app.error)
})
it('ignores modifiers IME handled events inactive views and unrelated controls, then disposes',()=>{
 const app=fixture();for(const extra of [{ctrlKey:true},{metaKey:true},{altKey:true},{shiftKey:true},{isComposing:true},{keyCode:229}])app.press('ArrowDown',extra)
 const handled=new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true});handled.preventDefault();app.button(7).dispatchEvent(handled)
 app.enable(false);app.press('ArrowDown');app.enable(true)
 const management=app.list.appendChild(document.createElement('button'));management.focus();app.press('ArrowDown')
 app.button(7).focus();app.nav.dispose();app.press('ArrowDown');expect(app.open).not.toHaveBeenCalled()
})
it('leaves modal hidden and disabled targets alone and scrolls successful current pages nearest',()=>{
 const app=fixture();const scroll=vi.fn();HTMLButtonElement.prototype.scrollIntoView=scroll
 const dialog=document.body.appendChild(document.createElement('div'));dialog.setAttribute('role','dialog');app.press('End');expect(app.open).not.toHaveBeenCalled()
 dialog.hidden=true;app.press('End');expect(app.current()).toBe(19);expect(scroll).toHaveBeenLastCalledWith({block:'nearest',inline:'nearest'})
 app.list.hidden=true;app.press('Home');expect(app.current()).toBe(19);app.list.hidden=false
 app.button(19).disabled=true;app.press('Home');expect(app.current()).toBe(19)
})
it('uses selected current even when Tab is on a different page and consumes an edge without flushing',()=>{
 const app=fixture();app.setCurrent(2);app.button(7).focus();app.press('ArrowDown');expect(app.current()).toBe(19);expect(document.activeElement).toBe(app.button(19))
 app.button(7).focus();const edge=app.press('End');expect(edge.defaultPrevented).toBe(true);expect(app.open).toHaveBeenCalledTimes(1);expect(document.activeElement).toBe(app.button(7))
})
