import type {NativeOperation} from './native-draft'
import {validatedPdfCrop,type PdfPageIdentity,type PdfRect} from './pdf-operations'

export interface PdfStampThumbnail {
 image:string
 rect:{left:number;top:number;width:number;height:number}
 opacity:number
}

export function pendingStampsForThumbnail(operations:NativeOperation[],pages:PdfPageIdentity[],page:PdfPageIdentity,sourceSha256:string,viewport:{width:number;height:number;convertToViewportPoint:(x:number,y:number)=>number[]}):PdfStampThumbnail[]{
 const stamps=operations.filter(operation=>operation.kind==='setStamps')
 if(stamps.length!==1||!page.pageId.startsWith(`sha256:${sourceSha256}:page:`)||!pages.some(item=>item.pageId===page.pageId))return []
 const operation=stamps[0]!
 if(operation.sourceSha256!==undefined&&operation.sourceSha256!==sourceSha256||!Array.isArray(operation.images)||!Array.isArray(operation.stamps))return []
 const images=operation.images as unknown[],pageStamps=(operation.stamps as {pageId:string;image:number;rect:number[];opacity?:number}[]).filter(stamp=>stamp?.pageId===page.pageId)
 const result:PdfStampThumbnail[]=[]
 for(const stamp of pageStamps){
  if(!Number.isInteger(stamp.image)||stamp.image<0||stamp.image>=images.length)continue
  const image=images[stamp.image]
  if(typeof image!=='string'||!image.startsWith('iVBORw0KGgo')||(stamp.opacity!==undefined&&(!Number.isFinite(stamp.opacity)||stamp.opacity<0||stamp.opacity>1)))continue
  let rect:PdfRect
  try{rect=validatedPdfCrop(stamp.rect,page.cropBox)}catch{continue}
  const [x1,y1,x2,y2]=rect,points=[[x1,y1],[x2,y1],[x1,y2],[x2,y2]].map(point=>viewport.convertToViewportPoint(point[0]!,point[1]!)),xs=points.map(point=>point[0]!),ys=points.map(point=>point[1]!),left=Math.min(...xs),top=Math.min(...ys),right=Math.max(...xs),bottom=Math.max(...ys)
  result.push({image,rect:{left:left/viewport.width*100,top:top/viewport.height*100,width:(right-left)/viewport.width*100,height:(bottom-top)/viewport.height*100},opacity:stamp.opacity??1})
 }
 return result
}
