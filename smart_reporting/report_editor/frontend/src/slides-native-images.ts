/** 固定源 insertImage / replacePicture 的浏览器选图适配；保持 PNG/JPEG 原始字节。 */
import { imageDpiFromBytes } from '../../../reporting/slides_engine/packages/pptx-render/src/image-dpi'
export type SlideImageAsset = { bytesBase64: string; extension: 'png'|'jpg'; descr: string }
export type SlideImageGeometry = { x:number; y:number; width:number; height:number }

/** 对齐固定源 picture-frame.ts：96dpi，自然尺寸，最大8.5英寸，居中。返回现有 wire 的96dpi像素。 */
export function imagePlacement(slide:{cx:number;cy:number},natural:{width:number;height:number},dpi?:{x:number;y:number}):SlideImageGeometry {
 const width=natural.width*96/(dpi?.x??96),height=natural.height*96/(dpi?.y??96)
 const slideW=slide.cx/9525,slideH=slide.cy/9525
 const scale=Math.min(1,Math.min(slideW,816)/width,slideH/height)
 const w=width*scale,h=height*scale
 return {x:(slideW-w)/2,y:(slideH-h)/2,width:w,height:h}
}
function readDataUrl(file:File):Promise<string>{
 return new Promise((resolve,reject)=>{
  const reader=new FileReader()
  reader.onerror=()=>reject(Error('读取图片失败，请重新选择'))
  reader.onload=()=>resolve(String(reader.result))
  reader.readAsDataURL(file)
 })
}
export async function prepareSlideImage(file:File,slide:{cx:number;cy:number}):Promise<SlideImageAsset&{geometry:SlideImageGeometry}> {
 if(!file.size||file.size>6*1024*1024)throw Error('请选择不超过 6 MiB 的 PNG 或 JPEG 图片')
 const dataUrl=await readDataUrl(file),bytesBase64=dataUrl.slice(dataUrl.indexOf(',')+1)
 const bytes=Uint8Array.from(atob(bytesBase64),c=>c.charCodeAt(0))
 const png=[137,80,78,71,13,10,26,10].every((n,i)=>bytes[i]===n)
 const jpg=bytes[0]===255&&bytes[1]===216&&bytes[2]===255
 if(!png&&!jpg)throw Error('请选择有效的 PNG 或 JPEG 图片')
 const extension=png?'png':'jpg'
 // 解码真实文件，拒绝只有魔数而无法显示的输入；不重新编码，以免丢失分辨率元数据。
 const image=new Image()
 image.src=`data:image/${png?'png':'jpeg'};base64,${bytesBase64}`
 try{await image.decode()}catch{throw Error('图片内容损坏，无法读取 PNG 或 JPEG')}
 if(!image.naturalWidth||!image.naturalHeight||image.naturalWidth*image.naturalHeight>100_000_000)throw Error('图片尺寸无效或超过一亿像素')
 return {bytesBase64,extension,descr:file.name,geometry:imagePlacement(slide,{width:image.naturalWidth,height:image.naturalHeight},imageDpiFromBytes(bytes))}
}
export function pickSlideImage():Promise<File|null>{
 return new Promise(resolve=>{
  const input=document.createElement('input')
  input.type='file';input.accept='image/png,image/jpeg,.png,.jpg,.jpeg';input.hidden=true
  const finish=(file:File|null)=>{input.remove();resolve(file)}
  input.addEventListener('change',()=>finish(input.files?.[0]??null),{once:true})
  input.addEventListener('cancel',()=>finish(null),{once:true})
  document.body.append(input);input.click()
 })
}
