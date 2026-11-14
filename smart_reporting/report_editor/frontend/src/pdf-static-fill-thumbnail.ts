import type {NativeOperation} from './native-draft'
import type {PdfModel,PdfPageIdentity,PdfRect} from './pdf-operations'
import {validatePdfStaticFill} from './pdf-static-fill'

export interface PdfStaticFillThumbnail {
  id:string
  image:string
  rect:PdfRect
}

/** Return only pending fills whose operation identity still matches this source page. */
export function pendingStaticFillsForThumbnail(model:Pick<PdfModel,'sourceSha256'|'pages'>,operations:NativeOperation[],page:PdfPageIdentity):PdfStaticFillThumbnail[]{
 const result:PdfStaticFillThumbnail[]=[]
 for(const operation of operations){
  if(operation.kind!=='setStaticFill'||operation.pageId!==page.pageId||operation.sourceSha256!==model.sourceSha256)continue
  try{
   validatePdfStaticFill([page],[operation])
   if(typeof operation.image==='string')result.push({id:String(operation.id),image:operation.image,rect:operation.rect as PdfRect})
  }catch{}
 }
 return result
}

/** Map the PDF rect through the active page viewport into thumbnail-relative percentages. */
export function pdfStaticFillThumbnailPosition(rect:PdfRect,viewport:{width:number;height:number;convertToViewportPoint:(x:number,y:number)=>number[]}):{left:number;top:number;width:number;height:number}{
 const first=viewport.convertToViewportPoint(rect[0],rect[1]),second=viewport.convertToViewportPoint(rect[2],rect[3])
 const left=Math.min(first[0]!,second[0]!),top=Math.min(first[1]!,second[1]!),width=Math.abs(second[0]!-first[0]!),height=Math.abs(second[1]!-first[1]!)
 return {left:left/viewport.width*100,top:top/viewport.height*100,width:width/viewport.width*100,height:height/viewport.height*100}
}
