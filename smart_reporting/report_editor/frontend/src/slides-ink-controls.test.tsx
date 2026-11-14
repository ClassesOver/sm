import {act} from 'react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {mountSlidesInk} from './slides-ink-controls'
let ui:ReturnType<typeof mountSlidesInk>|undefined
beforeEach(()=>{localStorage.clear();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}})})
afterEach(()=>{act(()=>ui?.dispose());document.body.replaceChildren();vi.unstubAllGlobals()})
it('完整源5笔槽、活动属性5粗细16色自定义、增3种笔与最少保留1支',()=>{
 const panel=document.createElement('div'),canvas=document.createElement('div');document.body.append(panel,canvas)
 act(()=>{ui=mountSlidesInk(panel,{canvas:()=>canvas,state:()=>({slide:undefined,slideIndex:0,changes:{},key:'a',available:true}),commit:vi.fn(),status:vi.fn()})})
 expect(panel.querySelectorAll('.ink-pen-slot')).toHaveLength(5)
 const click=(element:Element)=>act(()=>{(element as HTMLElement).click()})
 click(panel.querySelector('.ink-pen-slot')!);click(panel.querySelector('.ink-pen-slot')!);expect(panel.querySelectorAll('.ink-width')).toHaveLength(5);expect(panel.querySelectorAll('.ink-swatch')).toHaveLength(16);expect(panel.querySelector('.ink-pen-more')).toBeTruthy()
 click(panel.querySelector('.ink-pen-add')!);expect(panel.querySelectorAll('.ink-pen-pop .ink-pen-item')).toHaveLength(3);click(panel.querySelectorAll('.ink-pen-pop .ink-pen-item')[2]!);expect(panel.querySelectorAll('.ink-pen-slot')).toHaveLength(6)
 for(let n=6;n>1;n--){const last=[...panel.querySelectorAll('.ink-pen-slot')].at(-1)!;click(last);if(!panel.querySelector('.ink-pen-delete'))click(last);click(panel.querySelector('.ink-pen-delete')!)}
 const last=panel.querySelector('.ink-pen-slot')!;click(last);if(!panel.querySelector('.ink-pen-delete'))click(last);expect((panel.querySelector('.ink-pen-delete') as HTMLButtonElement).disabled).toBe(true)
})
it('只读禁用整族、IME Escape不退出，正常Escape取消在绘笔迹',()=>{
 const panel=document.createElement('div'),canvas=document.createElement('div');document.body.append(panel,canvas);let available=true
 act(()=>{ui=mountSlidesInk(panel,{canvas:()=>canvas,state:()=>({slide:undefined,slideIndex:0,changes:{},key:'a',available}),commit:vi.fn(),status:vi.fn()})})
 act(()=>panel.querySelector<HTMLButtonElement>('.ink-pen-slot')!.click());expect(panel.querySelector('.ink-pen-slot.active')).toBeTruthy()
 act(()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true})));expect(panel.querySelector('.ink-pen-slot.active')).toBeTruthy()
 act(()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})));expect(panel.querySelector('.ink-pen-slot.active')).toBeNull()
 available=false;act(()=>ui!.update());expect([...panel.querySelectorAll<HTMLButtonElement>('button')].every(b=>b.disabled)).toBe(true)
})
