/** Read actual PDF objects through the pinned engine, including exclusive Form ancestry. */
import {chainPdfium,loadPdfium} from '../src/main/text-edit'
import {concatMat,transformRect,walkPageText,type Mat} from '../src/main/form-text'
interface ObjectIdentity{text:string;rect:number[];objectPath:number[];measureText?:string}
export function replacementMetrics(bytes:Uint8Array,pageIndex:number,objects:ObjectIdentity[]){
 return chainPdfium(async()=>{
  const m=await loadPdfium(),buffer=m._malloc(bytes.length),scratch=m._malloc(48)
  let doc=0,page=0,textPage=0
  try{
   m.HEAPU8.set(bytes,buffer);doc=m._FPDF_LoadMemDocument(buffer,bytes.length,0)
   if(!doc)throw Error('pdf_text_style_measure_document_unreadable')
   page=m._FPDF_LoadPage(doc,pageIndex);if(!page)throw Error('pdf_text_style_measure_page_unreadable')
   textPage=m._FPDFText_LoadPage(page);if(!textPage)throw Error('pdf_text_style_measure_text_page_unreadable')
   const result:({matrix:Mat;width:number;fontSize:number;color:number[];boldPainted:boolean}|undefined)[]=objects.map(()=>undefined)
   walkPageText(m,page,1,({obj,topIndex,ordinals,toPage})=>{
    const path=[topIndex,...ordinals]
    if(!objects.some(item=>JSON.stringify(item.objectPath)===JSON.stringify(path)))return
    const length=m._FPDFTextObj_GetText(obj,textPage,0,0)
    if(length<2)return
    const textBuffer=m._malloc(length);let text=''
    try{m._FPDFTextObj_GetText(obj,textPage,textBuffer,length);text=Buffer.from(m.HEAPU8.buffer,textBuffer,length-2).toString('utf16le')}finally{m._free(textBuffer)}
    if(!m._FPDFPageObj_GetBounds(obj,scratch,scratch+4,scratch+8,scratch+12))return
    const local=Array.from(m.HEAPF32.subarray(scratch>>2,(scratch>>2)+4)) as [number,number,number,number],rect=transformRect(local,toPage)
    const index=objects.findIndex((item,i)=>!result[i]&&item.text===text&&JSON.stringify(item.objectPath)===JSON.stringify(path)&&item.rect.every((value,j)=>Math.abs(value-rect[j]!)<.05))
    if(index<0)return
    if(!m._FPDFPageObj_GetMatrix(obj,scratch)||!m._FPDFTextObj_GetFontSize(obj,scratch+24))throw Error('pdf_text_style_measure_matrix_unreadable')
    const matrix=concatMat(Array.from(m.HEAPF32.subarray(scratch>>2,(scratch>>2)+6)) as unknown as Mat,toPage),size=m.HEAPF32[(scratch+24)>>2]!,font=m._FPDFTextObj_GetFont(obj)
    let width=0
    for(const character of objects[index]!.measureText??text){if(!m._FPDFFont_GetGlyphWidth(font,character.codePointAt(0)!,1,scratch+28))throw Error('pdf_text_style_glyph_width_unavailable');width+=m.HEAPF32[(scratch+28)>>2]!*size*Math.hypot(matrix[0],matrix[1])}
    const color=m._FPDFPageObj_GetFillColor(obj,scratch,scratch+4,scratch+8,scratch+12)?[0,4,8].map(offset=>m.HEAP32[(scratch+offset)>>2]!):[]
    const mode=m._FPDFTextObj_GetTextRenderMode(obj),boldPainted=[2,6].includes(mode)&&!!m._FPDFPageObj_GetStrokeWidth(obj,scratch+32)&&m.HEAPF32[(scratch+32)>>2]!>0
    result[index]={matrix,width,fontSize:size*Math.hypot(matrix[2],matrix[3]),color,boldPainted}
   })
   if(result.some(item=>!item))throw Error('pdf_text_style_measure_identity_missing')
   return result as {matrix:Mat;width:number;fontSize:number;color:number[];boldPainted:boolean}[]
  }finally{if(textPage)m._FPDFText_ClosePage(textPage);if(page)m._FPDF_ClosePage(page);if(doc)m._FPDF_CloseDocument(doc);m._free(scratch);m._free(buffer)}
 })
}
