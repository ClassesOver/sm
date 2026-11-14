import {expect,it,vi} from 'vitest'
import {bakePdfImagePixels} from './pdf-image-pixels'

vi.mock('./vendor/genoffice-pdf/renderer/ImageDialogs',()=>({cropImagePng:vi.fn(()=> 'cropped-png')}))

it('uses the established image cropper for pending crop thumbnails',()=>{
 const image={naturalWidth:10,naturalHeight:8} as HTMLImageElement
 expect(bakePdfImagePixels(image,{kind:'crop',crop:{l:0,t:.25,r:.5,b:1}})).toBe('cropped-png')
})

it('rotates using canvas geometry and quarter-turn orientation',()=>{
 const context={translate:vi.fn(),rotate:vi.fn(),drawImage:vi.fn(),getImageData:vi.fn(),putImageData:vi.fn()}
 const canvas={width:0,height:0,getContext:()=>context,toDataURL:()=> 'data:image/png;base64,rotated'} as unknown as HTMLCanvasElement
 const create=document.createElement.bind(document);vi.spyOn(document,'createElement').mockImplementation(tag=>tag==='canvas'?canvas:create(tag))
 const image={naturalWidth:4,naturalHeight:2,ownerDocument:document} as HTMLImageElement
 expect(bakePdfImagePixels(image,{kind:'rotate',quarterTurns:1})).toBe('rotated')
 expect(canvas.width).toBe(2);expect(canvas.height).toBe(4);expect(context.translate).toHaveBeenCalledWith(1,2);expect(context.rotate).toHaveBeenCalledWith(Math.PI/2)
})

it('reuses pixel helpers for flip and opacity bakes',()=>{
 const data=new Uint8ClampedArray([10,20,30,255,40,50,60,200]),context={drawImage:vi.fn(),getImageData:vi.fn(()=>({data,width:2,height:1})),createImageData:vi.fn((width:number,height:number)=>({data:new Uint8ClampedArray(width*height*4),width,height})),putImageData:vi.fn(),translate:vi.fn(),rotate:vi.fn()}
 const canvas={width:0,height:0,getContext:()=>context,toDataURL:()=> 'data:image/png;base64,baked'} as unknown as HTMLCanvasElement
 const create=document.createElement.bind(document);vi.spyOn(document,'createElement').mockImplementation(tag=>tag==='canvas'?canvas:create(tag))
 const image={naturalWidth:2,naturalHeight:1,ownerDocument:document} as HTMLImageElement
 expect(bakePdfImagePixels(image,{kind:'flip',axis:'h'})).toBe('baked')
 expect(context.putImageData.mock.calls[0]?.[0].data).toEqual(new Uint8ClampedArray([40,50,60,200,10,20,30,255]))
 expect(bakePdfImagePixels(image,{kind:'opacity',alpha:.25})).toBe('baked')
 expect(context.putImageData.mock.calls[1]?.[0].data).toEqual(new Uint8ClampedArray([10,20,30,64,40,50,60,50]))
})

it('removes edge background for pending cutout thumbnails without changing source pixels',()=>{
 const data=new Uint8ClampedArray(Array.from({length:9},(_,index)=>index===4?[0,0,0,255]:[255,255,255,255]).flat()),original=new Uint8ClampedArray(data)
 const context={drawImage:vi.fn(),getImageData:vi.fn(()=>({data,width:3,height:3})),createImageData:vi.fn((width:number,height:number)=>({data:new Uint8ClampedArray(width*height*4),width,height})),putImageData:vi.fn()}
 const canvas={width:0,height:0,getContext:()=>context,toDataURL:()=> 'data:image/png;base64,cutout'} as unknown as HTMLCanvasElement
 const create=document.createElement.bind(document);vi.spyOn(document,'createElement').mockImplementation(tag=>tag==='canvas'?canvas:create(tag))
 const image={naturalWidth:3,naturalHeight:3,ownerDocument:document} as HTMLImageElement
 expect(bakePdfImagePixels(image,{kind:'cutout',tolerance:0})).toBe('cutout')
 const output=context.putImageData.mock.calls[0]?.[0].data as Uint8ClampedArray
 expect(Array.from({length:9},(_,index)=>output[index*4+3])).toEqual([0,0,0,0,255,0,0,0,0])
 expect(data).toEqual(original)
})
