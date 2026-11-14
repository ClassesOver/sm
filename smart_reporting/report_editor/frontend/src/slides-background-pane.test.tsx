import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {act} from 'react'
import {createSlidesBackgroundPane} from './slides-background-pane'
import type {RenderSlide} from '@genoffice/pptx-render'
const slide={widthPx:960,heightPx:540,scale:1,nodes:[],background:{kind:'image',mode:'stretch',dataUrl:'data:image/png;base64,fixture'},bgOwn:true} as RenderSlide
let pane:ReturnType<typeof createSlidesBackgroundPane>|undefined
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true)})
afterEach(()=>{act(()=>pane?.dispose());document.body.replaceChildren();vi.useRealTimers();vi.unstubAllGlobals()})
function button(text:string){return [...document.querySelectorAll('button')].find(b=>b.textContent===text)!}
it('完整三模式、原图拉伸平铺与全部复用、独立隐藏图形、重置与折叠',()=>{
 const apply=vi.fn();pane=createSlidesBackgroundPane(apply);document.body.append(pane.element);act(()=>pane!.open(slide,'source:0'))
 expect(button('纯色填充')).toBeTruthy();expect(button('渐变填充')).toBeTruthy();expect(button('图片填充')).toBeTruthy()
 expect(document.querySelector('img')?.src).toContain('fixture')
 act(()=>button('平铺').click());expect(apply).toHaveBeenLastCalledWith({kind:'image',mode:'tile',pick:false},undefined)
 act(()=>button('应用到全部').click());expect(apply).toHaveBeenLastCalledWith({kind:'image',mode:'stretch',pick:false},true)
 act(()=>document.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());expect(apply).toHaveBeenLastCalledWith({kind:'hideGraphics',hidden:true},undefined)
 act(()=>button('重置背景').click());expect(apply).toHaveBeenLastCalledWith({kind:'reset'},undefined)
 act(()=>document.querySelector<HTMLButtonElement>('[aria-label="关闭格式窗格"]')!.click());expect(pane.element.hidden).toBe(true)
})
it('切页锁定后不能修改，关闭销毁可重复调用',()=>{
 const apply=vi.fn();pane=createSlidesBackgroundPane(apply);document.body.append(pane.element);act(()=>pane!.open({...slide,background:{kind:'solid',color:'#123456'}},'source:0'))
 act(()=>button('渐变填充').click());expect(apply).not.toHaveBeenCalled()
 act(()=>pane!.update(slide,'source:1',true));expect([...pane.element.querySelectorAll('button')].filter(b=>!b.disabled)).toHaveLength(1)
 pane.flush();expect(apply).not.toHaveBeenCalled()
})

it('保存flush提交待处理颜色一次，应用全部采用尚未debounce的颜色',()=>{
 const apply=vi.fn();pane=createSlidesBackgroundPane(apply);document.body.append(pane.element);act(()=>pane!.open({...slide,background:{kind:'solid',color:'#123456'}},'source:0'))
 act(()=>button('渐变填充').click());pane.flush();expect(apply).toHaveBeenCalledTimes(1);pane.flush();expect(apply).toHaveBeenCalledTimes(1)
 act(()=>button('应用到全部').click());expect(apply).toHaveBeenLastCalledWith(expect.objectContaining({kind:'solid'}),true)
})

it('背景共享色板键盘Escape关闭并恢复触发器焦点',()=>{
 const apply=vi.fn();pane=createSlidesBackgroundPane(apply);document.body.append(pane.element);act(()=>pane!.open({...slide,background:{kind:'gradient',stops:[{pos:0,color:'#123456'},{pos:1,color:'#ffffff'}],angleDeg:0}},'source:0'))
 const trigger=pane.element.querySelector<HTMLButtonElement>('[aria-label="起始色"]')!;act(()=>trigger.click());const cell=document.querySelector<HTMLElement>('[data-chart-format-palette] [tabindex="0"]')!;cell.focus()
 act(()=>cell.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})));expect(document.querySelector('[data-chart-format-palette]')).toBeNull();expect(document.activeElement).toBe(trigger)
})

it('固定源四种渐变方向完整保留0/90/45与径向',()=>{
 const apply=vi.fn();pane=createSlidesBackgroundPane(apply);document.body.append(pane.element);act(()=>pane!.open({...slide,background:{kind:'gradient',stops:[{pos:0,color:'#123456'},{pos:1,color:'#ffffff'}],angleDeg:0}},'source:0'))
 for(const [label,angleDeg,radial] of [['0°',0,false],['90°',90,false],['45°',45,false],['径向',0,true]] as const){act(()=>pane!.element.querySelector<HTMLButtonElement>('[aria-label="'+label+'"]')!.click());pane.flush();expect(apply).toHaveBeenLastCalledWith(expect.objectContaining({kind:'gradient',angleDeg,...(radial?{radial:true}:{})}))}
})
