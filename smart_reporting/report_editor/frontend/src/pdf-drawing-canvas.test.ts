import { afterEach, expect, it, vi } from 'vitest'
import { mountDrawingCanvas, type DrawingCanvasController } from './pdf-drawing-canvas'
import { paintDrawing } from './pdf-drawing-shapes'
import type { NativeOperation } from './native-draft'
import type { PendingDrawingReference } from './pdf-pending-drawings'
import { pdfToView, viewToPdf } from './genoffice-pdf-annotations'
const ns='http://www.w3.org/2000/svg',box={x:10,y:20,width:400,height:500},page={pageId:'p',index:0,mediaBox:box,cropBox:box,rotation:0}
const base={kind:'addDrawing',pageId:'p',color:[1,0,0],width:2}
const shapes:NativeOperation[]=[
 {...base,shape:'rect',rect:[60,100,160,180]}, {...base,shape:'ellipse',rect:[60,100,160,180]},
 {...base,shape:'arrow',from:[60,100],to:[160,180]}, {...base,shape:'measure',from:[60,100],to:[160,180],label:'12.00 m'},
 {...base,shape:'ink',paths:[[60,100,80,120],[110,130,160,180]]},
 {...base,shape:'polygon',vertices:[[60,100],[160,100],[100,180]]}, {...base,shape:'caret',point:[100,150]},
]
const viewport={width:400,height:500,convertToViewportPoint:(x:number,y:number)=>[x-10,520-y],convertToPdfPoint:(x:number,y:number)=>[x+10,520-y]}
const controllers:DrawingCanvasController[]=[]
afterEach(()=>{controllers.forEach(c=>c.dispose());controllers.length=0;document.body.replaceChildren()})
function fixture(operations:NativeOperation[]) {
 const host=document.createElement('div');document.body.append(host);let selected:PendingDrawingReference|undefined,enabled=true,unchanged=true
 const commit=vi.fn(),error=vi.fn(),controller=mountDrawingCanvas({host,pages:[page],pageId:'p',operations,viewport,scale:1,current:()=>enabled,unchanged:()=>unchanged,selected:()=>selected,select(ref){selected=ref;controller.sync()},commit,error})
 controllers.push(controller);const svg=host.querySelector('svg')!;vi.spyOn(svg,'getBoundingClientRect').mockReturnValue({x:0,y:0,width:400,height:500,left:0,top:0,right:400,bottom:500,toJSON:()=>({})});controller.sync()
 return {host,svg,controller,commit,error,disable(){enabled=false;controller.sync()},stale(){unchanged=false;controller.sync()}}
}
function pointer(target:Element,type:string,x=70,y=380,id=1) {const e=new MouseEvent(type,{bubbles:true,cancelable:true,button:0,clientX:x,clientY:y});Object.defineProperties(e,{pointerId:{value:id},isPrimary:{value:true}});target.dispatchEvent(e)}
it.each(shapes.map(shape=>[String(shape.shape),shape] as const))('moves exact %s record once, cancels stale updates and never mutates during live',(_name,shape)=>{
 const input=[shape,shape],original=structuredClone(input),f=fixture(input),g=f.host.querySelector('[data-pdf-shape-index="1"]')!
 pointer(g.querySelector('[data-pdf-shape-hit]')!,'pointerdown');pointer(f.svg,'pointermove',80,390)
 expect(f.commit).not.toHaveBeenCalled();expect(input).toEqual(original);expect(f.host.querySelector('[data-pdf-drawing-selection]')?.getAttribute('data-pdf-drawing-selection')).toBe('1')
 pointer(f.svg,'pointerup',80,390);expect(f.commit).toHaveBeenCalledTimes(1)
 const result=f.commit.mock.calls[0]![0] as NativeOperation[];expect(result[0]).toEqual(shape);expect(result[1]).not.toEqual(shape);expect(result[1]!.color).toEqual(shape.color);expect(result[1]!.width).toBe(shape.width)
 if(shape.shape==='measure')expect(result[1]!.label).toBe(shape.label)
 pointer(g.querySelector('[data-pdf-shape-hit]')!,'pointerdown');pointer(f.svg,'pointermove',80,390);f.stale();pointer(f.svg,'pointerup',80,390);expect(f.commit).toHaveBeenCalledTimes(1)
})
it('preserves cross-kind z-order and restricts handles to images, links stay non-movable',()=>{
 const image={...base,shape:'image',image:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',rect:[60,100,160,180]}
 const f=fixture([shapes[0]!,image,shapes[1]!,image,{...base,shape:'link',rect:[60,100,160,180],url:'https://example.org'}])
 expect([...f.host.querySelectorAll('g[data-pdf-shape-index]')].map(g=>g.getAttribute('data-pdf-shape-kind'))).toEqual(['rect','image','ellipse','image','link'])
 pointer(f.host.querySelector('[data-pdf-shape-index="1"] image')!,'pointerdown');pointer(f.svg,'pointerup');expect(f.host.querySelectorAll('[data-pdf-image-handle]')).toHaveLength(4)
 pointer(f.host.querySelector('[data-pdf-shape-index="0"] [data-pdf-shape-hit]')!,'pointerdown');pointer(f.svg,'pointerup');expect(f.host.querySelectorAll('[data-pdf-image-handle]')).toHaveLength(0)
 const link=f.host.querySelector('[data-pdf-shape-kind="link"]')!;expect(link.querySelector('[data-pdf-shape-hit]')).toBeNull();pointer(link,'pointerdown');pointer(f.svg,'pointerup',100,400);expect(f.commit).not.toHaveBeenCalled()
})
it('renders all ink paths, fixed caret glyph, arrow heads and grouped measurement labels',()=>{
 const group=document.createElementNS(ns,'g')
 paintDrawing(group,shapes[4]!,viewport,3);expect(group.querySelectorAll('[data-pdf-drawing="ink"]')).toHaveLength(2);expect(group.querySelectorAll('[data-pdf-shape-hit]')).toHaveLength(2)
 expect(group.querySelector('[data-pdf-shape-hit]')?.getAttribute('stroke-width')).toBe('24')
 expect(group.querySelector('[data-pdf-drawing="ink"]')?.getAttribute('stroke-linecap')).toBe('round')
 paintDrawing(group,shapes[6]!,viewport,3);expect(group.querySelector('[data-pdf-drawing="caret"]')?.getAttribute('d')).toBe('M90 370 L82 376 L98 376 Z');expect(group.querySelector('[data-pdf-drawing="caret"]')?.getAttribute('fill')).toBe('rgb(255,0,0)');expect(group.querySelector('[data-pdf-drawing="caret"]')?.getAttribute('stroke')).toBe('none')
 paintDrawing(group,shapes[2]!,viewport,1);expect(group.querySelectorAll('[data-pdf-arrow-head]')).toHaveLength(2);expect(group.querySelectorAll('[data-pdf-shape-hit]')).toHaveLength(3)
 paintDrawing(group,shapes[3]!,viewport,.5);const label=group.querySelector('[data-pdf-measure-label]')!;expect(label.textContent).toBe('12.00 m');expect(label.getAttribute('font-size')).toBe('9');expect(label.getAttribute('stroke')).toBe('none');expect(label.getAttribute('text-anchor')).toBe('start');expect(label.getAttribute('transform')).toMatch(/^matrix\(/)
})
it('uses unfilled stroke geometry for hit outlines and no rectangular interception overlays',()=>{
 const f=fixture([shapes[0]!,shapes[1]!,shapes[5]!])
 for(const hit of f.host.querySelectorAll('[data-pdf-shape-hit]')){expect(hit.getAttribute('fill')).toBe('none');expect(hit.getAttribute('stroke')).toBe('transparent');expect(hit.getAttribute('stroke-width')).toBe('16')}
 expect(f.host.querySelectorAll('[data-pdf-shape-index="1"] rect')).toHaveLength(0)
 expect(f.host.querySelectorAll('[data-pdf-shape-index="2"] rect')).toHaveLength(0)
})
it.each([0,90,180,270])('translates all ink paths and endpoints through nonzero crop/UserUnit CSS viewport at %i',rotation=>{
 const geom={pw:800,ph:1000,x0:10,y0:20,userUnit:2,rot:rotation},scale=1.25
 const vp={width:(rotation%180?1000:800)*scale,height:(rotation%180?800:1000)*scale,convertToViewportPoint:(x:number,y:number)=>pdfToView(geom,x,y).map(v=>v*scale),convertToPdfPoint:(x:number,y:number)=>viewToPdf(geom,x/scale,y/scale)}
 const host=document.createElement('div');document.body.append(host);const commit=vi.fn(),controller=mountDrawingCanvas({host,pages:[page],pageId:'p',operations:[shapes[4]!],viewport:vp,current:()=>true,selected:()=>undefined,select(){},commit,error:vi.fn()});controllers.push(controller)
 const svg=host.querySelector('svg')!;vi.spyOn(svg,'getBoundingClientRect').mockReturnValue({x:30,y:40,width:vp.width/2,height:vp.height/2,left:30,top:40,right:30+vp.width/2,bottom:40+vp.height/2,toJSON:()=>({})});controller.sync()
 const a=vp.convertToViewportPoint(60,100),b=vp.convertToViewportPoint(70,95)
 pointer(host.querySelector('[data-pdf-shape-hit]')!,'pointerdown',30+a[0]!/2,40+a[1]!/2);pointer(svg,'pointerup',30+b[0]!/2,40+b[1]!/2)
 expect(commit).toHaveBeenCalledTimes(1);expect(commit.mock.calls[0]![0][0].paths).toEqual([[70,95,90,115],[120,125,170,175]])
})
it('refuses readonly, foreign-pointer cancellation, overflow and disposed events without changing source',()=>{
 const f=fixture([shapes[0]!]),target=f.host.querySelector('[data-pdf-shape-hit]')!
 pointer(target,'pointerdown');pointer(f.svg,'pointercancel',80,390,2);pointer(f.svg,'pointermove',-999,380);pointer(f.svg,'pointerup',-999,380);expect(f.error).toHaveBeenCalledTimes(1);expect(f.commit).not.toHaveBeenCalled()
 f.disable();pointer(target,'pointerdown');pointer(f.svg,'pointerup',80,390);expect(f.commit).not.toHaveBeenCalled();f.controller.dispose();pointer(target,'pointerdown');pointer(f.svg,'pointerup',80,390);expect(f.commit).not.toHaveBeenCalled()
})
