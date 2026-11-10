import { describe, expect, it } from 'vitest'
import { pdfToView, viewToPdf } from './genoffice-pdf-annotations'
import { imageViewBox, imageGestureOperations, type ImageViewport } from './pdf-image-gesture'
import type { PdfPageIdentity } from './pdf-operations'
const box={x:-10,y:20,width:400,height:600}
const page:PdfPageIdentity={pageId:'source',index:0,mediaBox:box,cropBox:box,rotation:0}
const image={kind:'addDrawing',pageId:'source',shape:'image',rect:[50,100,150,180],image:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',color:[1,0,0],width:2}
function viewport(rot:number):ImageViewport {
  const geom={pw:800,ph:1200,x0:-10,y0:20,userUnit:2,rot},scale=1.25
  return {width:(rot%180?1200:800)*scale,height:(rot%180?800:1200)*scale,convertToViewportPoint:(x,y)=>pdfToView(geom,x,y).map(v=>v*scale),convertToPdfPoint:(x,y)=>viewToPdf(geom,x/scale,y/scale)}
}
const ref=(ops:typeof image[])=>({index:1,pageId:'source',snapshot:JSON.stringify(ops)})
describe('source image gestures through viewport transforms',()=>{
  it.each([0,90,180,270])('moves exact twins and resizes all four corners at %i with CropBox/UserUnit/CSS scale',rot=>{
    const vp=viewport(rot),bounds={x:30,y:70,width:vp.width/2,height:vp.height/2},ops=[structuredClone(image),structuredClone(image)],original=structuredClone(ops)
    const a=vp.convertToViewportPoint(80,130),b=vp.convertToViewportPoint(90,125)
    const changed=imageGestureOperations([page],ops,ref(ops),vp,bounds,[30+a[0]!/2,70+a[1]!/2],[30+b[0]!/2,70+b[1]!/2])!
    expect(changed[0]).toEqual(image);expect(changed[1]!.rect).toEqual([60,95,160,175]);expect(ops).toEqual(original)
    const view=imageViewBox(image.rect,vp)
    for(const corner of [0,1,2,3]) {
      const x=view.x+(corner%2?view.width:0),y=view.y+(corner<2?0:view.height),fx=view.x+(corner%2?0:view.width),fy=view.y+(corner<2?view.height:0)
      const next=imageGestureOperations([page],ops,ref(ops),vp,bounds,[30+x/2,70+y/2],[30+(x+fx)/4,70+(y+fy)/4],corner)!
      const r=next[1]!.rect as number[],fixed=vp.convertToPdfPoint(fx,fy)
      expect(r[2]!-r[0]!).toBeCloseTo(50);expect(r[3]!-r[1]!).toBeCloseTo(40)
      expect([r[0],r[2]]).toContain(fixed[0]);expect([r[1],r[3]]).toContain(fixed[1]);expect(next[0]).toEqual(image)
    }
  })
  it('uses CSS thresholds, minimum display size and rejects stale/invalid/overflow changes',()=>{
    const vp=viewport(0),bounds={x:0,y:0,width:vp.width,height:vp.height},ops=[image,image],reference=ref(ops)
    expect(imageGestureOperations([page],ops,reference,vp,bounds,[100,100],[102,101])).toBeUndefined()
    const view=imageViewBox(image.rect,vp),start:[number,number]=[view.x,view.y],end:[number,number]=[view.x+view.width,view.y+view.height]
    expect(imageGestureOperations([page],ops,reference,vp,{...bounds,width:vp.width/40,height:vp.height/40},[10,10],[10,10],0)).toBeUndefined()
    const tiny=imageGestureOperations([page],ops,reference,vp,bounds,start,end,0)!
    const tinyBox=imageViewBox(tiny[1]!.rect as number[],vp);expect(Math.max(tinyBox.width,tinyBox.height)).toBeCloseTo(16)
    expect(imageGestureOperations([page],ops,reference,vp,bounds,start,[start[0]+.5,start[1]+.5],0)).toBeUndefined()
    expect(()=>imageGestureOperations([page],ops,reference,vp,bounds,start,[-5000,-5000],0)).toThrow()
    expect(()=>imageGestureOperations([page],ops,reference,vp,{...bounds,width:0},start,end)).toThrow()
    expect(()=>imageGestureOperations([page],ops,reference,vp,bounds,start,[NaN,0])).toThrow()
    expect(()=>imageGestureOperations([page],[...ops,image],reference,vp,bounds,start,end)).toThrow()
    expect(()=>imageGestureOperations([page],ops,reference,vp,bounds,start,end,4)).toThrow()
  })
})
