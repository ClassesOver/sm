import { afterEach, expect, it, vi } from 'vitest'
import { mountImageCanvas, type ImageCanvasController } from './pdf-image-canvas'
import type { PendingDrawingReference } from './pdf-pending-drawings'
import type { NativeOperation } from './native-draft'
const box={x:0,y:0,width:400,height:500},page={pageId:'p',index:0,mediaBox:box,cropBox:box,rotation:0}
const operation={kind:'addDrawing',pageId:'p',shape:'image',rect:[50,100,150,200],image:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',color:[1,0,0],width:2}
const controllers:ImageCanvasController[]=[]
afterEach(()=>{controllers.forEach(c=>c.dispose());controllers.length=0;document.body.replaceChildren()})
function fixture() {
  const host=document.createElement('div');document.body.append(host)
  let selected:PendingDrawingReference|undefined,enabled=true
  const commit=vi.fn(),error=vi.fn()
  const controller=mountImageCanvas({host,pages:[page],pageId:'p',operations:[operation,operation],viewport:{width:400,height:500,convertToViewportPoint:(x,y)=>[x,500-y],convertToPdfPoint:(x,y)=>[x,500-y]},current:()=>enabled,selected:()=>selected,select(ref){selected=ref;controller.sync()},commit,error})
  controllers.push(controller)
  const svg=host.querySelector('svg')!,image=host.querySelectorAll('image')[1]!
  vi.spyOn(svg,'getBoundingClientRect').mockReturnValue({x:0,y:0,width:400,height:500,left:0,top:0,right:400,bottom:500,toJSON:()=>({})})
  controller.sync()
  return {controller,host,svg,image,commit,error,disable(){enabled=false;controller.sync()}}
}
function pointer(target:Element,type:string,x=80,y=330,id=1) {
  const event=new MouseEvent(type,{bubbles:true,cancelable:true,clientX:x,clientY:y,button:0})
  Object.defineProperties(event,{pointerId:{value:id},isPrimary:{value:true}});target.dispatchEvent(event)
}
it('selects exact twin, previews locally and commits once on release, never during move',()=>{
  const f=fixture();pointer(f.image,'pointerdown');expect(f.host.querySelectorAll('circle')).toHaveLength(4)
  pointer(f.svg,'pointermove',100,340);expect(f.commit).not.toHaveBeenCalled();expect(f.image.getAttribute('x')).toBe('70')
  pointer(f.svg,'pointerup',100,340);expect(f.commit).toHaveBeenCalledTimes(1)
  const next=f.commit.mock.calls[0]![0] as NativeOperation[];expect(next[0]).toEqual(operation);expect(next[1]!.rect).toEqual([70,90,170,190])
  pointer(f.svg,'pointerup',100,340);expect(f.commit).toHaveBeenCalledTimes(1)
})
it.each(['pointercancel','lostpointercapture','Escape','blur','scroll','wheel','resize','disabled','detached','dispose'])('cancels %s without draft mutation',reason=>{
  const f=fixture();pointer(f.image,'pointerdown');pointer(f.svg,'pointermove',100,340)
  if(reason==='Escape')document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))
  else if(reason==='blur'||reason==='resize')window.dispatchEvent(new Event(reason))
  else if(reason==='scroll'||reason==='wheel')document.dispatchEvent(new Event(reason))
  else if(reason==='disabled')f.disable()
  else if(reason==='detached')f.host.remove()
  else if(reason==='dispose')f.controller.dispose()
  else pointer(f.svg,reason)
  pointer(f.svg,'pointerup',100,340);expect(f.commit).not.toHaveBeenCalled()
})
it('ignores other pointers and click no-ops; a stable SVG captures a resized handle',()=>{
  const f=fixture();pointer(f.image,'pointerdown');pointer(f.svg,'pointermove',100,340,2);pointer(f.svg,'pointercancel',100,340,2);pointer(f.svg,'pointerup',81,330)
  expect(f.commit).not.toHaveBeenCalled()
  const handle=f.host.querySelector('[data-pdf-image-handle="0"]')!;pointer(handle,'pointerdown',50,300);pointer(f.svg,'pointermove',100,350);pointer(f.svg,'pointerup',100,350)
  expect(f.commit).toHaveBeenCalledTimes(1);expect(f.commit.mock.calls[0]![0][1].rect).toEqual([100,100,150,150])
})
it('invalid geometry and stale readonly controllers cannot commit or intercept new edits',()=>{
  const f=fixture();pointer(f.image,'pointerdown');pointer(f.svg,'pointermove',-1000,330);pointer(f.svg,'pointerup',-1000,330)
  expect(f.error).toHaveBeenCalledTimes(1);expect(f.commit).not.toHaveBeenCalled()
  f.disable();pointer(f.image,'pointerdown');pointer(f.svg,'pointerup',100,340);expect(f.commit).not.toHaveBeenCalled()
})
