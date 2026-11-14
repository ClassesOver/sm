import {cropImagePng} from './vendor/genoffice-pdf/renderer/ImageDialogs'
import {flipPixels,multiplyAlpha} from './vendor/genoffice-pdf/renderer/image-bake'
import {removeBackground} from './vendor/genoffice-pdf/renderer/cutout'
import type {PdfImageBake} from './pdf-existing-image'

const toBase64=(dataUrl:string)=>dataUrl.startsWith('data:image/png;base64,')?dataUrl.slice('data:image/png;base64,'.length):''

/** Reuse the image editor's crop and pixel helpers for a pending image thumbnail. */
export function bakePdfImagePixels(image:HTMLImageElement,bake:PdfImageBake):string{
 if(bake.kind==='crop')return cropImagePng(image,bake.crop)
 const canvas=image.ownerDocument.createElement('canvas')
 if(bake.kind==='rotate'){
  const turns=bake.quarterTurns===1?1:3
  canvas.width=turns%2?image.naturalHeight:image.naturalWidth;canvas.height=turns%2?image.naturalWidth:image.naturalHeight
  const context=canvas.getContext('2d');if(!context)throw Error('图像像素上下文不可用')
  context.translate(canvas.width/2,canvas.height/2);context.rotate(turns*Math.PI/2);context.drawImage(image,-image.naturalWidth/2,-image.naturalHeight/2)
  return toBase64(canvas.toDataURL('image/png'))
 }
 canvas.width=image.naturalWidth;canvas.height=image.naturalHeight
 const context=canvas.getContext('2d');if(!context)throw Error('图像像素上下文不可用')
 context.drawImage(image,0,0)
 const pixels=context.getImageData(0,0,canvas.width,canvas.height),sourcePixels={data:pixels.data,width:pixels.width,height:pixels.height}
 const data=bake.kind==='flip'?flipPixels(sourcePixels,bake.axis):bake.kind==='cutout'?removeBackground(sourcePixels,bake.tolerance).data:multiplyAlpha(sourcePixels,bake.alpha),output=context.createImageData(pixels.width,pixels.height)
 output.data.set(data);context.putImageData(output,0,0)
 return toBase64(canvas.toDataURL('image/png'))
}
