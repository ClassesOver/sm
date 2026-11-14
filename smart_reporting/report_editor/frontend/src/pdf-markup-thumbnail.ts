import type {NativeOperation} from './native-draft'
import {validatePdfMarkup,type MarkupType} from './pdf-markup'
import type {PdfPageIdentity} from './pdf-operations'

export interface PdfMarkupThumbnail {
 markupType:MarkupType
 color:number[]
 left:number
 top:number
 width:number
 height:number
}

export function pendingMarkupsForThumbnail(operations:NativeOperation[],page:PdfPageIdentity,sourceSha256:string,viewport:{width:number;height:number;convertToViewportPoint:(x:number,y:number)=>number[]}):PdfMarkupThumbnail[]{
 const result:PdfMarkupThumbnail[]=[]
 if(!page.pageId.startsWith(`sha256:${sourceSha256}:page:`))return result
 for(const operation of operations){
  if(operation.kind!=='addMarkup'||operation.pageId!==page.pageId||(operation.sourceSha256!==undefined&&operation.sourceSha256!==sourceSha256))continue
  try{validatePdfMarkup(operation)}catch{continue}
  for(const quad of operation.quads as number[][]){
   const points=[viewport.convertToViewportPoint(quad[0]!,quad[1]!),viewport.convertToViewportPoint(quad[2]!,quad[3]!),viewport.convertToViewportPoint(quad[4]!,quad[5]!),viewport.convertToViewportPoint(quad[6]!,quad[7]!)]
   const xs=points.map(point=>point[0]!),ys=points.map(point=>point[1]!),left=Math.min(...xs),top=Math.min(...ys),right=Math.max(...xs),bottom=Math.max(...ys)
   result.push({markupType:operation.markupType as MarkupType,color:operation.color as number[],left:left/viewport.width*100,top:top/viewport.height*100,width:(right-left)/viewport.width*100,height:(bottom-top)/viewport.height*100})
  }
 }
 return result
}
