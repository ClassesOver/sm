export interface PdfSignatureImage {
  image:string
  width:number
  height:number
}

const MAX_IMAGE_DIMENSION=1600
const MAX_INPUT_BYTES=10*1024*1024
const MAX_PNG_BASE64=6_000_000

export async function preparePdfSignatureImage(file:File,blackAndWhite:boolean):Promise<PdfSignatureImage>{
 if(file.size>MAX_INPUT_BYTES)throw Error('签名图片不能超过 10MB')
 const bitmap=await createImageBitmap(file)
 try{
  if(!bitmap.width||!bitmap.height)throw Error('图片尺寸无效')
  const ratio=Math.min(1,MAX_IMAGE_DIMENSION/Math.max(bitmap.width,bitmap.height))
  const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*ratio));canvas.height=Math.max(1,Math.round(bitmap.height*ratio))
  const context=canvas.getContext('2d',{willReadFrequently:blackAndWhite});if(!context)throw Error('浏览器无法处理签名图片')
  context.drawImage(bitmap,0,0,canvas.width,canvas.height)
  if(blackAndWhite){
   const pixels=context.getImageData(0,0,canvas.width,canvas.height),data=pixels.data
   for(let index=0;index<data.length;index+=4){
    const lightness=.299*data[index]!+.587*data[index+1]!+.114*data[index+2]!
    const alpha=lightness>200?0:lightness<120?255:Math.round(((200-lightness)/80)*255)
    data[index]=0;data[index+1]=0;data[index+2]=0;data[index+3]=Math.round(alpha*data[index+3]!/255)
   }
   context.putImageData(pixels,0,0)
  }
  const dataUrl=canvas.toDataURL('image/png'),image=dataUrl.startsWith('data:image/png;base64,')?dataUrl.slice('data:image/png;base64,'.length):''
  if(!image.startsWith('iVBORw0KGgo')||image.length>MAX_PNG_BASE64)throw Error('签名图片转换失败或过大，请选择较小的图片')
  return {image,width:canvas.width,height:canvas.height}
 }finally{bitmap.close()}
}
