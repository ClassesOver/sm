import { afterEach, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createSlidesShapeFormatPane, planSlidesShapeStyle, shapeStyleForCommand } from './slides-shape-format-pane'
const base = { slideIndex: 0, element: { id:'shape', type:'shape', brushSource:{supported:true,shape:{fill:'#123456',stroke:{color:'#345678',widthPt:2.25}}} }, changes:{shapeStyles:[] as any[],edits:[{slideIndex:0,elementId:'shape',text:'保留'}]} }
let pane:ReturnType<typeof createSlidesShapeFormatPane> | undefined
afterEach(()=>{act(()=>pane?.dispose());pane=undefined;vi.useRealTimers();document.body.innerHTML='';(globalThis as any).IS_REACT_ACT_ENVIRONMENT=false})
it('来源轮廓改色保留实际粗细，改粗细保留颜色，返回来源时只删对应patch',()=>{
 const colored=planSlidesShapeStyle(base,'shapeOutline','#abcdef')!
 expect(colored.shapeStyles).toEqual([{slideIndex:0,elementId:'shape',stroke:{color:'#ABCDEF',widthPt:2.25}}])
 const resized=planSlidesShapeStyle({...base,changes:colored},'shapeOutlineWidth','3.5')!
 expect(resized.shapeStyles[0].stroke).toEqual({color:'#ABCDEF',widthPt:3.5})
 const filled=planSlidesShapeStyle({...base,changes:resized},'shapeNoFill')!
 const reset=planSlidesShapeStyle({...base,changes:filled},'shapeResetStroke')!
 expect(reset.shapeStyles).toEqual([{slideIndex:0,elementId:'shape',fill:'none'}]);expect(reset.edits).toEqual(base.changes.edits)
 expect(planSlidesShapeStyle(base,'shapeFill','#123456')).toBeUndefined()
 expect(shapeStyleForCommand('shapeOutlineWidth','4', {slideIndex:0,elementId:'legacy'})).toMatchObject({stroke:{color:'#000000',widthPt:4}})
})
it('填充和轮廓分别限制复杂来源，拒绝非法值，显式无线条保留null',()=>{
 const dashed={...base,element:{...base.element,brushSource:{supported:true,shape:{fill:'#123456'}}}}
 expect(()=>planSlidesShapeStyle(dashed,'shapeOutlineWidth','3')).toThrow(/轮廓/)
 expect(planSlidesShapeStyle(dashed,'shapeFill','#abcdef')!.shapeStyles[0].fill).toBe('#ABCDEF')
 for(const value of ['', '0','101','Infinity','wrong'])expect(()=>planSlidesShapeStyle(base,'shapeOutlineWidth',value)).toThrow()
 expect(planSlidesShapeStyle(base,'shapeNoOutline')!.shapeStyles[0].stroke).toBeNull()
 expect(()=>planSlidesShapeStyle({...base,reason:'组合待保存'},'shapeNoFill')).toThrow('组合待保存')
})
function setup() {
 (globalThis as any).IS_REACT_ACT_ENVIRONMENT=true
 let context=structuredClone(base)
 const confirm=vi.fn((changes:typeof base.changes)=>{context={...context,changes};pane!.update()})
 pane=createSlidesShapeFormatPane(()=>context,confirm);document.body.append(pane.element);act(()=>pane!.update())
 const width=()=>pane!.element.querySelector<HTMLInputElement>('[data-shape-width]')!
 const type=(value:string)=>act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(width(),value);width().dispatchEvent(new Event('input',{bubbles:true}))})
 const pick=(point:string,color:string)=>{
  act(()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})))
  act(()=>pane!.element.querySelector<HTMLButtonElement>(`[data-chart-format-well="${point}"]`)!.click())
  const input=document.querySelector<HTMLInputElement>('[data-chart-format-custom]')!
  act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,color);input.dispatchEvent(new Event('input',{bubbles:true}))})
 }
 return {confirm,width,type,pick,context:()=>context,setContext:(next:typeof context)=>{context=next;act(()=>pane!.update())}}
}
it('侧栏回填来源并合并颜色与宽度为一笔历史，原生颜色输入保持挂载',()=>{
 const {confirm,width,type,pick,context}=setup();vi.useFakeTimers()
 expect(width().value).toBe('2.25');pick('shape-fill','#abcdef');type('3.5')
 const input=document.querySelector('[data-chart-format-custom]');act(()=>vi.advanceTimersByTime(200))
 expect(confirm).toHaveBeenCalledOnce();expect(context().changes.shapeStyles).toMatchObject([{fill:'#ABCDEF',stroke:{color:'#345678',widthPt:3.5}}])
 expect(document.querySelector('[data-chart-format-custom]')).toBe(input)
})
it('非法宽度阻止flush且可改回原值，保存前flush与提交失败可重试',()=>{
 const {confirm,width,type}=setup();vi.useFakeTimers()
 type('');act(()=>expect(pane!.flush()).toBe(false));expect(pane!.element.textContent).toContain('粗细')
 type('2.25');act(()=>expect(pane!.flush()).toBe(true));expect(confirm).not.toHaveBeenCalled()
 type('4');confirm.mockImplementationOnce(()=>{throw new Error('写入失败')})
 act(()=>expect(pane!.flush()).toBe(false));expect(width().value).toBe('4');expect(pane!.element.textContent).toContain('写入失败')
 act(()=>expect(pane!.flush()).toBe(true));expect(confirm).toHaveBeenCalledTimes(2)
})
it('切选择、外部回填、锁定及销毁取消旧颜色与旧控件写入',()=>{
 const {confirm,pick,context,setContext}=setup();vi.useFakeTimers()
 pick('shape-fill','#abcdef');const old=pane!.element.querySelector<HTMLButtonElement>('[data-shape-none="fill"]')!
 setContext({...context(),element:{...context().element,id:'other'}});act(()=>{old.click();vi.advanceTimersByTime(250)});expect(confirm).not.toHaveBeenCalled()
 pick('shape-fill','#112233');act(()=>pane!.setLocked(true));act(()=>vi.advanceTimersByTime(250));expect(confirm).not.toHaveBeenCalled()
 act(()=>pane!.setLocked(false));expect(document.querySelector('[data-chart-format-palette]')).toBeNull()
 pick('shape-fill','#112233');act(()=>pane!.dispose());act(()=>vi.advanceTimersByTime(250));expect(confirm).not.toHaveBeenCalled()
})
it('重选已有覆盖不重排其他对象，防抖内恢复来源不创建空历史',()=>{
 const styles=[{slideIndex:0,elementId:'shape',fill:'#ABCDEF'},{slideIndex:0,elementId:'other',fill:'#112233'}]
 expect(planSlidesShapeStyle({...base,changes:{...base.changes,shapeStyles:styles}},'shapeFill','#ABCDEF')).toBeUndefined()
 const {confirm,pick}=setup();vi.useFakeTimers()
 pick('shape-fill','#abcdef');pick('shape-fill','#123456');act(()=>vi.advanceTimersByTime(250))
 expect(confirm).not.toHaveBeenCalled()
})
it('功能区任意来源线宽回填，锁定解锁后仍保留来源能力限制',()=>{
 (globalThis as any).IS_REACT_ACT_ENVIRONMENT=true
 const host=document.createElement('div');host.innerHTML='<input data-command="shapeFill" type="color"><input data-command="shapeOutline" type="color"><select data-command="shapeOutlineWidth"><option value="1">1</option></select>'
 const context=structuredClone(base);context.element.brushSource.shape.stroke.widthPt=3.75
 pane=createSlidesShapeFormatPane(()=>context,vi.fn(),host);act(()=>pane!.update())
 const width=host.querySelector<HTMLSelectElement>('select')!
 expect(width.value).toBe('3.75');expect(width.querySelectorAll('[data-shape-source-width]')).toHaveLength(1)
 act(()=>pane!.setLocked(true));expect(width.disabled).toBe(true)
 act(()=>pane!.setLocked(false));expect(width.disabled).toBe(false)
 delete (context.element.brushSource.shape as any).stroke;act(()=>pane!.update())
 width.disabled=false;act(()=>pane!.setLocked(false));expect(width.disabled).toBe(true)
})

it('填充和轮廓使用原生可辨识分组',()=>{
 setup()
 expect([...pane!.element.querySelectorAll('fieldset > legend')].map(node=>node.textContent)).toEqual(['填充','轮廓'])
})
it('非法粗细暴露字段错误状态',()=>{
 const {type,width}=setup();type('0');expect(width().getAttribute('aria-invalid')).toBe('true')
})
it.each(['legacy','handled'])('粗细Enter与Escape尊重受保护按键：%s',protection=>{
 const {type,width,confirm}=setup();vi.useFakeTimers()
 for(const key of ['Enter','Escape']){
  type(key==='Enter'?'4':'0');width().focus()
  const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,keyCode:protection==='legacy'?229:0});if(protection==='handled')event.preventDefault()
  act(()=>width().dispatchEvent(event));expect(confirm).not.toHaveBeenCalled();expect(width().value).toBe(key==='Enter'?'4':'0');expect(document.activeElement).toBe(width())
 }
 act(()=>width().dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})));expect(width().value).toBe('2.25')
 act(()=>vi.advanceTimersByTime(250));expect(confirm).not.toHaveBeenCalled()
})
it('粗细错误关联唯一且可聚焦的状态说明，多实例不重用身份',()=>{
 const {type,width}=setup();type('0')
 const status=pane!.element.querySelector<HTMLElement>('[role=status]')!
 expect(status.id).toBeTruthy();expect(width().getAttribute('aria-describedby')).toBe(status.id);expect(status.getAttribute('aria-label')).toBe('形状格式状态');expect(status.tabIndex).toBe(0)
 expect(status.classList.contains('shape-format-error')).toBe(true);status.focus();expect(document.activeElement).toBe(status)
 const other=createSlidesShapeFormatPane(()=>structuredClone(base),vi.fn());document.body.append(other.element)
 try{act(()=>other.update());expect(other.element.querySelector('[role=status]')!.id).not.toBe(status.id)}finally{act(()=>other.dispose())}
})
it.each(['Enter','Escape'])('组合输入期间的 %s 不提交或撤回粗细',key=>{
 const {type,width,confirm}=setup();vi.useFakeTimers()
 type(key==='Enter'?'4':'0');width().focus()
 act(()=>width().dispatchEvent(new KeyboardEvent('keydown',{key,isComposing:true,bubbles:true,cancelable:true})))
 expect(confirm).not.toHaveBeenCalled();expect(width().value).toBe(key==='Enter'?'4':'0');expect(document.activeElement).toBe(width())
})
it('Escape 撤回尚未提交的粗细且保留同批填充，定时器不会随后提交旧粗细',()=>{
 const {type,width,pick,confirm,context}=setup();vi.useFakeTimers()
 pick('shape-fill','#abcdef');act(()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})))
 width().focus();type('4')
 act(()=>width().dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})))
 expect(width().value).toBe('2.25');expect(document.activeElement).toBe(width())
 act(()=>vi.advanceTimersByTime(250))
 expect(confirm).toHaveBeenCalledOnce();expect(context().changes.shapeStyles).toEqual([{slideIndex:0,elementId:'shape',fill:'#ABCDEF'}])
})
it('Escape 撤回单独的粗细输入，不留下空历史',()=>{
 const {type,width,confirm}=setup();vi.useFakeTimers();type('4')
 act(()=>width().dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true})))
 expect(width().value).toBe('2.25');act(()=>vi.advanceTimersByTime(250));expect(confirm).not.toHaveBeenCalled()
})
