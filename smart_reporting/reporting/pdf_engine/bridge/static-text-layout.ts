/** Measure the writer's actual embedded font, sharing the pinned PDFium queue. */
import {chainPdfium,loadPdfium} from '../src/main/text-edit'
export function insertedLineWidths(bytes:Uint8Array,pageIndex:number,objects:{objectPath:number[];text:string;fontSize:number;measureText?:string}[]){
 return chainPdfium(async()=>{
  const m=await loadPdfium(),buffer=m._malloc(bytes.length),width=m._malloc(4)
  let doc=0,page=0,textPage=0
  try{
   m.HEAPU8.set(bytes,buffer);doc=m._FPDF_LoadMemDocument(buffer,bytes.length,0)
   if(!doc)throw Error('pdf_insert_text_measure_document_unreadable')
   page=m._FPDF_LoadPage(doc,pageIndex);if(!page)throw Error('pdf_insert_text_measure_page_unreadable')
   textPage=m._FPDFText_LoadPage(page);if(!textPage)throw Error('pdf_insert_text_measure_text_page_unreadable')
   return objects.map(item=>{
    if(item.objectPath.length!==1)throw Error('pdf_insert_text_measure_complex_object')
    const object=m._FPDFPage_GetObject(page,item.objectPath[0]!),font=m._FPDFTextObj_GetFont(object)
    const length=m._FPDFTextObj_GetText(object,textPage,0,0)
    if(length<2||!font)throw Error('pdf_insert_text_measure_object_unreadable')
    const text=m._malloc(length)
    try{m._FPDFTextObj_GetText(object,textPage,text,length);if(Buffer.from(m.HEAPU8.buffer,text,length-2).toString('utf16le')!==item.text)throw Error('pdf_insert_text_measure_identity_changed')}finally{m._free(text)}
    let advance=0
    for(const character of item.measureText??item.text){if(!m._FPDFFont_GetGlyphWidth(font,character.codePointAt(0)!,1,width))throw Error('pdf_insert_text_glyph_width_unavailable');advance+=m.HEAPF32[width>>2]!*item.fontSize}
    if(!Number.isFinite(advance)||advance<0)throw Error('pdf_insert_text_glyph_width_invalid')
    return advance
   })
  }finally{if(textPage)m._FPDFText_ClosePage(textPage);if(page)m._FPDF_ClosePage(page);if(doc)m._FPDF_CloseDocument(doc);m._free(width);m._free(buffer)}
 })
}
