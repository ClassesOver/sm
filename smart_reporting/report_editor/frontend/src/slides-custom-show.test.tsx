import {afterEach,expect,it,vi} from 'vitest'
import {act} from 'react'
import {openSlidesCustomShows} from './slides-custom-show-dialog'
let dialog:ReturnType<typeof openSlidesCustomShows>|undefined
Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(){this.open=true}})
afterEach(()=>{act(()=>dialog?.dispose());document.body.replaceChildren()})
it('源完整增删改名/选页/顺序/播放保留重复页，关闭不制造写入',()=>{
 const change=vi.fn(),play=vi.fn();dialog=openSlidesCustomShows(document.body,{shows:[{id:'7',name:'来源',slideIndices:[2,0,2]}],slideCount:3,onChange:change,onPlay:play});
 expect(document.querySelectorAll('.csd-order-item')).toHaveLength(3)
 act(()=>document.querySelector<HTMLButtonElement>('[aria-label="下移"]')!.click());expect(change).toHaveBeenCalledWith([{id:'7',name:'来源',slideIndices:[0,2,2]}])
 act(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='放映此自定义放映')!.click());expect(play).toHaveBeenCalledWith(expect.objectContaining({id:'7'}))
})
it('低高度原生dialog可滚动，Esc恢复焦点且IME不抢方向键',()=>{
 const opener=document.body.appendChild(document.createElement('button'));opener.focus();dialog=openSlidesCustomShows(document.body,{shows:[],slideCount:3,onChange:vi.fn(),onPlay:vi.fn()});expect(document.querySelector('dialog')?.getAttribute('aria-label')).toBe('自定义放映');act(()=>dialog!.dispose());expect(document.activeElement).toBe(opener)
})

it('完整新建/勾选/改名/删除与错误反馈，来源重复页保持可见',()=>{
 const change=vi.fn();dialog=openSlidesCustomShows(document.body,{shows:[{id:'7',name:'来源',slideIndices:[2,0,2]}],slideCount:3,onChange:change,onPlay:vi.fn()})
 const click=(name:string)=>act(()=>[...document.querySelectorAll('button')].find(b=>b.textContent===name)!.click())
 click('新建');expect(change.mock.lastCall?.[0]).toHaveLength(2)
 const added=change.mock.lastCall![0][1];expect(added.id).toMatch(/^cs-/)
 act(()=>document.querySelectorAll<HTMLInputElement>('input[type=checkbox]')[1]!.click());expect(change.mock.lastCall?.[0][1].slideIndices).toEqual([1])
 const input=document.querySelector<HTMLInputElement>('input[type=text]')!;act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'新增重点');input.dispatchEvent(new Event('input',{bubbles:true}))});expect(change.mock.lastCall?.[0][1].name).toBe('新增重点')
 click('删除');expect(change.mock.lastCall?.[0]).toEqual([{id:'7',name:'来源',slideIndices:[2,0,2]}]);expect(document.querySelectorAll('.csd-order-item')).toHaveLength(3)
 act(()=>dialog!.dispose());const reject=vi.fn(()=>{throw Error('引用不能删除')});dialog=openSlidesCustomShows(document.body,{shows:[{id:'7',name:'来源',slideIndices:[0]}],slideCount:3,onChange:reject,onPlay:vi.fn()});click('删除');expect(document.querySelector('[role=alert]')?.textContent).toBe('引用不能删除');expect(document.querySelectorAll('[role=option]')).toHaveLength(1);expect(document.querySelector('input[type=text]')).not.toBeNull()
})
it('列表方向键支持选择，输入法组合期间不切换来源列表',()=>{
 dialog=openSlidesCustomShows(document.body,{shows:[{id:'7',name:'甲',slideIndices:[0]},{id:'8',name:'乙',slideIndices:[1]}],slideCount:3,onChange:vi.fn(),onPlay:vi.fn()})
 const list=document.querySelector('[role=listbox]')!;act(()=>list.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',isComposing:true,bubbles:true})));expect(document.querySelector('[role=option][aria-selected=true]')?.textContent).toContain('甲')
 act(()=>list.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true})));expect(document.querySelector('[role=option][aria-selected=true]')?.textContent).toContain('乙')
})
