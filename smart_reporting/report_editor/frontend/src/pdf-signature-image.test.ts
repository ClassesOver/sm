import {afterEach,expect,it,vi} from 'vitest'
import {preparePdfSignatureImage} from './pdf-signature-image'

afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals()})

it('decodes, downsamples and encodes a signature image as PNG',async()=>{
 const close=vi.fn(),drawImage=vi.fn(),imageData={data:new Uint8ClampedArray([20,40,60,255])}
 vi.stubGlobal('createImageBitmap',vi.fn(async()=>({width:3200,height:800,close})))
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage,getImageData:()=>imageData,putImageData:vi.fn()} as unknown as CanvasRenderingContext2D)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgoAAA==')
 const result=await preparePdfSignatureImage(new File([new Uint8Array([1])],'signature.png',{type:'image/png'}),false)
 expect(result).toEqual({image:'iVBORw0KGgoAAA==',width:1600,height:400})
 expect(drawImage).toHaveBeenCalledWith(expect.objectContaining({width:3200,height:800}),0,0,1600,400)
 expect(close).toHaveBeenCalledOnce()
})

it.each(['image/webp','image/gif','image/bmp'])('normalizes browser-decodable %s signature input',async type=>{
 const close=vi.fn();vi.stubGlobal('createImageBitmap',vi.fn(async()=>({width:80,height:40,close})))
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgoAAA==')
 const result=await preparePdfSignatureImage(new File(['raster'],`signature.${type.split('/')[1]}`,{type}),false)
 expect(result).toEqual({image:'iVBORw0KGgoAAA==',width:80,height:40});expect(close).toHaveBeenCalledOnce()
})

it('turns a light background into transparent black pixels when requested',async()=>{
 const close=vi.fn(),imageData={data:new Uint8ClampedArray([240,230,220,255])},putImageData=vi.fn()
 vi.stubGlobal('createImageBitmap',vi.fn(async()=>({width:100,height:50,close})))
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn(),getImageData:()=>imageData,putImageData} as unknown as CanvasRenderingContext2D)
 vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgoAAA==')
 await preparePdfSignatureImage(new File([new Uint8Array([1])],'signature.png',{type:'image/png'}),true)
 expect([...imageData.data]).toEqual([0,0,0,0]);expect(putImageData).toHaveBeenCalledOnce();expect(close).toHaveBeenCalledOnce()
})

it.each([
 ['empty',new File([],'empty.png',{type:'image/png'})],
 ['unsupported',new File(['x'],'signature.svg',{type:'image/svg+xml'})],
])('surfaces decoder failure for %s image',async(_label,file)=>{
 const decode=vi.fn();vi.stubGlobal('createImageBitmap',decode)
 await expect(preparePdfSignatureImage(file,false)).rejects.toThrow()
 expect(decode).toHaveBeenCalledOnce()
})

it('rejects signature images over 10MB before decoding',async()=>{
 const decode=vi.fn();vi.stubGlobal('createImageBitmap',decode)
 const file=new File([new Uint8Array(10*1024*1024+1)],'large.png',{type:'image/png'})
 await expect(preparePdfSignatureImage(file,false)).rejects.toThrow(/10MB/)
 expect(decode).not.toHaveBeenCalled()
})
