// Probe the actual PDFium substitute, not a guessed global font-name alias.
import {createHash} from 'node:crypto'
import {readFile,mkdir,writeFile} from 'node:fs/promises'
import {createRequire} from 'node:module'
import {dirname,join,resolve} from 'node:path'
const req=createRequire(new URL('../../../reporting/pdf_engine/package.json',import.meta.url))
const {init}=req('@embedpdf/pdfium'),source=resolve(process.argv[2]),directory=resolve(process.argv[3])
await mkdir(directory,{recursive:true})
const wasmPath=process.env.AGENT_REPORTING_PDF_WASM_DIR?join(process.env.AGENT_REPORTING_PDF_WASM_DIR,'pdfium.wasm'):join(dirname(req.resolve('@embedpdf/pdfium')),'pdfium.wasm')
const wasm=await readFile(wasmPath),wrapped=await init({wasmBinary:wasm.buffer.slice(wasm.byteOffset,wasm.byteOffset+wasm.byteLength)}),m=wrapped.pdfium??wrapped
m._PDFiumExt_Init()
const bytes=await readFile(source),ptr=m._malloc(bytes.length);m.HEAPU8.set(bytes,ptr)
const document=m._FPDF_LoadMemDocument(ptr,bytes.length,0),seen=new Set(),fonts=[]
if(!document)throw Error('Unable to open source PDF')
const readName=(method,font)=>{const size=m[method](font,0,0);if(size<=1)return '';const buffer=m._malloc(size);try{m[method](font,buffer,size);return new TextDecoder().decode(m.HEAPU8.subarray(buffer,buffer+size-1))}finally{m._free(buffer)}}
try{
 for(let pageIndex=0;pageIndex<m._FPDF_GetPageCount(document);pageIndex++){
  const page=m._FPDF_LoadPage(document,pageIndex),text=m._FPDFText_LoadPage(page)
  try{
   for(let index=0;index<m._FPDFText_CountChars(text);index++){
    const object=m._FPDFText_GetTextObject(text,index);if(!object)continue
    const font=m._FPDFTextObj_GetFont(object);if(!font||seen.has(font))continue;seen.add(font)
    const base=readName('_FPDFFont_GetBaseFontName',font),family=readName('_FPDFFont_GetFamilyName',font),length=m._malloc(4)
    try{
     m._FPDFFont_GetFontData(font,0,0,length);const size=m.HEAPU32[length>>2],buffer=m._malloc(size)
     try{
      if(!m._FPDFFont_GetFontData(font,buffer,size,length))throw Error('Unable to read font data: '+base)
      const data=m.HEAPU8.slice(buffer,buffer+size),file=(base.replace(/[^a-z0-9._-]/gi,'_')||'font-'+fonts.length)+'.font'
      await writeFile(join(directory,file),data)
      fonts.push({pageIndex,base,family,embedded:!!m._FPDFFont_GetIsEmbedded(font),size,file,sha256:createHash('sha256').update(data).digest('hex')})
     }finally{m._free(buffer)}
    }finally{m._free(length)}
   }
  }finally{m._FPDFText_ClosePage(text);m._FPDF_ClosePage(page)}
 }
}finally{m._FPDF_CloseDocument(document);m._free(ptr)}
const result={sourceSha256:createHash('sha256').update(bytes).digest('hex'),wasmSha256:createHash('sha256').update(wasm).digest('hex'),fonts}
await writeFile(join(directory,'font-evidence.json'),JSON.stringify(result,null,2)+'\n');process.stdout.write(JSON.stringify(result,null,2)+'\n')
