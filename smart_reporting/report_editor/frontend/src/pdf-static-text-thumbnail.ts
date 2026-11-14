import type {NativeOperation} from './native-draft'
import type {PdfPageIdentity} from './pdf-operations'
import {validatePdfStaticText} from './pdf-static-text'

type PdfViewport = {width:number;height:number;convertToViewportPoint:(x:number,y:number)=>number[]}

export function pendingPdfTextInsertsForThumbnail(sourceSha256:string,operations:NativeOperation[],page:PdfPageIdentity):NativeOperation[]{
 const result:NativeOperation[]=[]
 for(const operation of operations){
  if(operation.kind!=='insertText'||operation.pageId!==page.pageId||operation.sourceSha256!==sourceSha256)continue
  try{validatePdfStaticText([page],[operation]);result.push(operation)}catch{}
 }
 return result
}

export function pdfTextInsertThumbnailStyle(operation:NativeOperation,viewport:PdfViewport):Record<string,string>{
 const origin=operation.origin as [number,number],fontSize=Number(operation.fontSize),point=viewport.convertToViewportPoint(origin[0],origin[1])
 const align=operation.align==='center'||operation.align==='right'?operation.align:'left'
 const style:Record<string,string>={
  position:'absolute',left:`${point[0]!/viewport.width*100}%`,top:`${(point[1]!-fontSize)/viewport.height*100}%`,
  fontSize:`${fontSize*.92/viewport.width*100}cqw`,lineHeight:typeof operation.lineLeading==='number'?`${operation.lineLeading/viewport.width*100}cqw`:'1.2',
  color:`rgb(${(operation.color as number[]).map(value=>Math.round(value*255)).join(', ')})`,whiteSpace:'pre',pointerEvents:'none',textAlign:align,
 }
 if(align==='center')style.transform='translateX(-50%)'
 else if(align==='right')style.transform='translateX(-100%)'
 if(operation.font==='arial')style.fontFamily="Arial, 'Helvetica Neue', sans-serif"
 else if(operation.font==='times')style.fontFamily="'Times New Roman', Times, serif"
 else if(operation.font==='courier')style.fontFamily="'Courier New', monospace"
 if(operation.bold){
  if(operation.font)style.fontWeight='700'
  else style.WebkitTextStroke='.035em currentColor'
 }
 if(operation.italic)style.fontStyle='italic'
 return style
}
