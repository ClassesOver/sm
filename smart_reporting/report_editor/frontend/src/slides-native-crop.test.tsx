import {act} from 'react'
import {beforeEach,afterEach,expect,it,vi} from 'vitest'
import {openSlidesPictureCrop} from './slides-native-crop'
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ResizeObserver',class{observe(){} disconnect(){}})})
afterEach(()=>{document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})
function host(){const h=document.createElement('div');document.body.append(h);Object.defineProperty(h,'clientWidth',{value:640});return h}
it('居中canvas相对host偏移定位覆盖层，回传仍使用原画布坐标',async()=>{
 const h=host(),canvas=document.createElement('canvas'),onConfirm=vi.fn()
 Object.defineProperty(h,'getBoundingClientRect',{value:()=>({left:40,top:80,width:1000,height:500})})
 Object.defineProperty(canvas,'getBoundingClientRect',{value:()=>({left:220,top:120,width:640,height:360})})
 h.append(canvas)
 let view!:ReturnType<typeof openSlidesPictureCrop>
 try{
  await act(async()=>{view=openSlidesPictureCrop(h,{box:{x:200,y:100,width:300,height:200},srcRect:{l:.25,t:0,r:0,b:0},imgSrc:'data:image/png;base64,',slideWidthPx:1280,onConfirm,onCancel:vi.fn()})})
  const mount=h.querySelector<HTMLElement>('.slides-native-crop-root')!
  expect(mount.style.left).toBe('180px');expect(mount.style.top).toBe('40px')
  expect(mount.style.width).toBe('640px');expect(mount.style.height).toBe('360px')
  const frame=h.querySelector<HTMLElement>('.crop-frame')!
  expect(frame.style.left).toBe('100px');expect(frame.style.top).toBe('50px')
  await act(async()=>{window.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))})
  expect(onConfirm).toHaveBeenCalledWith({srcRect:{l:.25,t:0,r:0,b:0},geometry:{x:200,y:100,width:300,height:200}})
 }finally{await act(async()=>view?.dispose())}
})
it.each(['left','top','width','height'] as const)('canvas的%s改变取消裁切并观察真实canvas',async(axis)=>{
 let notify!:ResizeObserverCallback
 const observe=vi.fn(),disconnect=vi.fn()
 vi.stubGlobal('ResizeObserver',class{constructor(callback:ResizeObserverCallback){notify=callback}observe=observe;disconnect=disconnect})
 const h=host(),canvas=document.createElement('canvas'),onConfirm=vi.fn(),onCancel=vi.fn()
 const rect={left:200,top:100,width:640,height:360}
 Object.defineProperty(h,'getBoundingClientRect',{value:()=>({left:20,top:40,width:1000,height:500})})
 Object.defineProperty(canvas,'getBoundingClientRect',{value:()=>rect})
 h.append(canvas)
 let view!:ReturnType<typeof openSlidesPictureCrop>
 try{
  await act(async()=>{view=openSlidesPictureCrop(h,{box:{x:0,y:0,width:400,height:200},srcRect:null,imgSrc:'data:image/png;base64,',slideWidthPx:1280,onConfirm,onCancel})})
  expect(observe).toHaveBeenCalledWith(h);expect(observe).toHaveBeenCalledWith(canvas)
  rect[axis]+=10
  await act(async()=>{notify([],{} as ResizeObserver)})
  expect(onCancel).toHaveBeenCalledTimes(1);expect(onConfirm).not.toHaveBeenCalled()
  expect(h.querySelector('.crop-overlay')).toBeNull();expect(disconnect).toHaveBeenCalledTimes(1)
 }finally{await act(async()=>view?.dispose())}
})
it('复用裁切覆盖层按CSS缩放显示，确认转回原画布，Esc取消不提交',async()=>{
 const h=host(),onConfirm=vi.fn(),onCancel=vi.fn()
 let view!:ReturnType<typeof openSlidesPictureCrop>
 await act(async()=>{view=openSlidesPictureCrop(h,{box:{x:200,y:100,width:300,height:200},srcRect:{l:.25,t:0,r:0,b:0},imgSrc:'data:image/png;base64,',slideWidthPx:1280,onConfirm,onCancel})})
 const frame=h.querySelector<HTMLElement>('.crop-frame')!
 expect(frame.style.left).toBe('100px');expect(frame.style.width).toBe('150px')
 await act(async()=>{window.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))})
 expect(onConfirm).toHaveBeenCalledWith({srcRect:{l:.25,t:0,r:0,b:0},geometry:{x:200,y:100,width:300,height:200}})
 expect(h.querySelector('.crop-overlay')).toBeNull()
 await act(async()=>{view=openSlidesPictureCrop(h,{box:{x:0,y:0,width:400,height:200},srcRect:null,imgSrc:'data:image/png;base64,',slideWidthPx:1280,onConfirm,onCancel})})
 await act(async()=>{window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))})
 expect(onCancel).toHaveBeenCalledTimes(1);expect(onConfirm).toHaveBeenCalledTimes(1)
 view.dispose()
})
it('过期确认错误可见且保留覆盖层，显式取消后安全卸载',async()=>{
 const h=host(),onCancel=vi.fn();let view!:ReturnType<typeof openSlidesPictureCrop>
 await act(async()=>{view=openSlidesPictureCrop(h,{box:{x:0,y:0,width:400,height:200},srcRect:null,imgSrc:'data:image/png;base64,',slideWidthPx:1280,onConfirm:()=>{throw Error('草稿已变化')},onCancel})})
 await act(async()=>{window.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))})
 expect(h.querySelector('[role=alert]')?.textContent).toContain('草稿已变化')
 expect(h.querySelector('.crop-overlay')).not.toBeNull()
 await act(async()=>{window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))})
 expect(onCancel).toHaveBeenCalledTimes(1)
 view.dispose()
})
it('向外拖动固定源左手柄恢复完整原图，frame与crop一起提交',async()=>{
 const h=host(),onConfirm=vi.fn();let view!:ReturnType<typeof openSlidesPictureCrop>
 await act(async()=>{view=openSlidesPictureCrop(h,{box:{x:200,y:100,width:300,height:200},srcRect:{l:.25,t:0,r:0,b:0},imgSrc:'data:image/png;base64,',slideWidthPx:1280,onConfirm,onCancel:vi.fn()})})
 const west=h.querySelectorAll<HTMLElement>('.crop-handle')[7]!
 await act(async()=>{west.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,clientX:100,clientY:100}));window.dispatchEvent(new MouseEvent('mousemove',{clientX:50,clientY:100}));window.dispatchEvent(new MouseEvent('mouseup'))})
 await act(async()=>{window.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))})
 expect(onConfirm).toHaveBeenCalledWith({srcRect:null,geometry:{x:100,y:100,width:400,height:200}})
 view.dispose()
})
it('画布CSS尺寸改变会取消裁切，禁止提交过期坐标',async()=>{
 let notify!:ResizeObserverCallback
 vi.stubGlobal('ResizeObserver',class{constructor(callback:ResizeObserverCallback){notify=callback}observe(){}disconnect(){}})
 const h=host(),onConfirm=vi.fn(),onCancel=vi.fn();let view!:ReturnType<typeof openSlidesPictureCrop>
 Object.defineProperty(h,'getBoundingClientRect',{value:()=>({width:640})})
 await act(async()=>{view=openSlidesPictureCrop(h,{box:{x:0,y:0,width:400,height:200},srcRect:null,imgSrc:'data:image/png;base64,',slideWidthPx:1280,onConfirm,onCancel})})
 // 一个真实canvas的宽度优先于host宽度，对应视口变化后的渲染宽度。
 const canvas=document.createElement('canvas');Object.defineProperty(canvas,'getBoundingClientRect',{value:()=>({width:600})});h.append(canvas)
 await act(async()=>{notify([],{} as ResizeObserver)})
 expect(onCancel).toHaveBeenCalledTimes(1);expect(onConfirm).not.toHaveBeenCalled()
 expect(h.querySelector('.crop-overlay')).toBeNull()
 view.dispose()
})
