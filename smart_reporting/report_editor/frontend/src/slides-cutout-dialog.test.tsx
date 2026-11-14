import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {act} from 'react'
import {openSlidesCutout} from './slides-cutout-dialog'
let dialog:ReturnType<typeof openSlidesCutout>|undefined
let image:any
const put=vi.fn(),draw=vi.fn(),toData=vi.fn(()=> 'data:image/png;base64,YQ==')
beforeEach(()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.useFakeTimers();vi.stubGlobal('Image',class{naturalWidth=1040;naturalHeight=520;onload:(()=>void)|null=null;onerror:(()=>void)|null=null;constructor(){image=this}set src(_v:string){}})
 vi.stubGlobal('ImageData',class{constructor(public data:Uint8ClampedArray,public width:number,public height:number){}})
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockImplementation(function(this:HTMLCanvasElement){return {drawImage:draw,getImageData:()=>({data:new Uint8ClampedArray(this.width*this.height*4).fill(255)}),putImageData:put} as never})
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockImplementation(toData)
 Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(){this.open=true}})
})
afterEach(()=>{act(()=>dialog?.dispose());document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers()})
it('完整源容差/棋盘/百分比预览，应用重算原分辨率PNG',async()=>{
 const apply=vi.fn();await act(async()=>{dialog=openSlidesCutout(document.body,{dataUrl:'data:image/png;base64,YQ==',isCurrent:()=>true,onApply:apply});image.onload()})
 const canvas=document.querySelector('canvas')!;expect(canvas.width).toBe(520);expect(canvas.height).toBe(260);expect(document.querySelector('.cutout-preview')?.getAttribute('style')).toContain('conic-gradient');expect(document.querySelector('[data-cutout-hint]')?.textContent).toContain('100%')
 const slider=document.querySelector<HTMLInputElement>('input[type=range]')!;expect(slider.min).toBe('0');expect(slider.max).toBe('100');expect(slider.value).toBe('30')
 await act(async()=>{[...document.querySelectorAll('button')].find(b=>b.textContent==='应用')!.click();await vi.advanceTimersByTimeAsync(35)})
 expect(toData.mock.instances.at(-1)).toMatchObject({width:1040,height:520});expect(apply).toHaveBeenCalledWith('data:image/png;base64,YQ==');expect(document.querySelector('dialog')).toBeNull()
})
it('取消或选择变化后迟到decode/apply不能提交；IME Escape不抢占',async()=>{
 const apply=vi.fn();let current=true;await act(async()=>{dialog=openSlidesCutout(document.body,{dataUrl:'x',isCurrent:()=>current,onApply:apply})});const late=image.onload
 const event=new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true,cancelable:true});act(()=>document.querySelector('dialog')!.dispatchEvent(event));expect(document.querySelector('dialog')).not.toBeNull()
 act(()=>dialog!.dispose());await act(async()=>late());expect(apply).not.toHaveBeenCalled();expect(put).not.toHaveBeenCalled()
 await act(async()=>{dialog=openSlidesCutout(document.body,{dataUrl:'x',isCurrent:()=>current,onApply:apply});image.onload()});act(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='应用')!.click());current=false;await act(async()=>vi.advanceTimersByTimeAsync(35));expect(apply).not.toHaveBeenCalled();expect(document.querySelector('[role=alert]')?.textContent).toContain('变化')
})

it('解码失败有源错误且不可应用，Apply回调失败保留预览并可重试',async()=>{
 const apply=vi.fn(()=>{throw Error('源身份变化')});await act(async()=>{dialog=openSlidesCutout(document.body,{dataUrl:'x',isCurrent:()=>true,onApply:apply});image.onerror()});expect(document.querySelector('[role=alert]')?.textContent).toBe('图片加载失败');expect([...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='应用')!.disabled).toBe(true)
 act(()=>dialog!.dispose());await act(async()=>{dialog=openSlidesCutout(document.body,{dataUrl:'x',isCurrent:()=>true,onApply:apply});image.onload()});await act(async()=>{[...document.querySelectorAll('button')].find(b=>b.textContent==='应用')!.click();await vi.advanceTimersByTimeAsync(35)});expect(document.querySelector('[role=alert]')?.textContent).toBe('源身份变化');expect(document.querySelector('canvas')).not.toBeNull();expect([...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='应用')!.disabled).toBe(false)
})
