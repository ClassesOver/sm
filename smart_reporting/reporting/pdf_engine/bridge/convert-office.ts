import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { PDFDocument, PDFName, PDFNumber } from 'pdf-lib'
import { z } from 'zod'
import { openPptx } from '../../slides_engine/packages/pptx-engine/src/index'
import { parseDocx } from '../../doc_engine/packages/docx-engine/src/index'
import { applyStaticImage } from '../../workbook_engine/packages/xlsx-engine/src/chart-add'
import { embedXlsxPageImages } from './xlsx-page-images'
import { applyXlsxRichText } from './xlsx-rich-text'
import JSZip from 'jszip'
import { extractIrDocument, isScannedDocument } from '../vendor/pdf2docx/src/pipeline'
import { rebuildDocx } from '../vendor/pdf2docx/src/rebuild/index'
import { rebuildXlsx } from '../vendor/pdf2docx/src/rebuild-xlsx/rebuild'
import { applyOutputFontSubstitutions } from '../vendor/pdf2docx/src/rebuild/fontmap'
import { pdfiumWasmPath } from '../src/main/wasm-path'
import { convertPdfToPptx } from '../vendor/pdf2docx/src/rebuild-pptx/index'
import type { PdfiumModule } from '../vendor/pdf2docx/src/extract/pdfium'

const requestSchema=z.object({format:z.enum(['pptx','docx','xlsx']),sourceSha256:z.string().regex(/^[a-f0-9]{64}$/)}).strict()
const sha=(bytes:Uint8Array)=>createHash('sha256').update(bytes).digest('hex')
let pdfiumPromise:Promise<PdfiumModule>|undefined
function ensurePdfium(){
  pdfiumPromise??=(async()=>{
    const {init}=await import('@embedpdf/pdfium')
    const raw=readFileSync(pdfiumWasmPath())
    const wrapped=await init({wasmBinary:raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),thisProgram:'smart-reporting-pdf-convert'})
    const module=((wrapped as {pdfium?:unknown}).pdfium??wrapped) as PdfiumModule&{_PDFiumExt_Init():void}
    module._PDFiumExt_Init();return module
  })()
  return pdfiumPromise
}

/** Fixed-source PDF→Office converters. OCR is deliberately never supplied. */
export async function convertPdfOffice(content:Uint8Array,request:unknown){
  const options=requestSchema.parse(request)
  if(!(content instanceof Uint8Array)||content.length===0||content.length>24*1024*1024||sha(content)!==options.sourceSha256)throw Error('PDF 转换来源身份或 24 MiB 文件预算无效')
  const source=await PDFDocument.load(content,{updateMetadata:false})
  if(source.isEncrypted||source.context.trailerInfo.Encrypt||source.catalog.has(PDFName.of('Perms')))throw Error('暂不支持受保护 PDF 转换')
  const pageCount=source.getPageCount()
  if(pageCount<1||pageCount>50)throw Error('PDF 转换仅支持 1–50 页')
  let pixels=0
  for(const page of source.getPages()){
    const media=page.getMediaBox(),crop=page.getCropBox(),unitObject=page.node.get(PDFName.of('UserUnit'))
    const unit=unitObject===undefined?1:source.context.lookup(unitObject,PDFNumber).asNumber()
    const width=Math.max(media.width,crop.width)*unit,height=Math.max(media.height,crop.height)*unit,area=Math.ceil(width*2)*Math.ceil(height*2)
    if(!Number.isFinite(area)||unit<=0||width<=0||height<=0||area>20_000_000||(pixels+=area)>100_000_000)throw Error('PDF 转换超过单页 2000 万或合计 1 亿像素预算')
  }
  const engineOptions={pdfium:await ensurePdfium(),renderScale:2}
  let bytes:Uint8Array
  let result:{pages:number;warnings:string[];pageResults:ReturnType<typeof extractIrDocument>['pageResults'];scannedDocument:boolean}
  if(options.format==='pptx'){
    const converted=await convertPdfToPptx(content,engineOptions);bytes=converted.pptx;result=converted
  }else{
    const {irPages,warnings,pageResults,furnitureHf}=extractIrDocument(content,{...engineOptions,cellData:options.format==='xlsx'})
    if(options.format==='docx')bytes=await rebuildDocx(irPages,{furnitureHf})
    else{
      applyOutputFontSubstitutions(irPages,[])
      const converted=await rebuildXlsx(irPages,furnitureHf);bytes=converted.xlsx;warnings.push(...converted.warnings)
      const rich=await applyXlsxRichText(bytes,converted.sheets);bytes=rich.bytes;warnings.push(...rich.warnings)
      // Local adaptation: upstream XLSX omits raster fallbacks; the existing
      // xlsx-engine image writer preserves its cells and package mechanics.
      for(const page of irPages){
        if(!(page.scanned||page.degraded)||!page.render)continue
        const image=page.render,width=page.widthPt*12700,height=page.heightPt*12700
        const embedded=await applyStaticImage(bytes,{worksheetSheetName:'Page '+(page.index+1),imageId:'pdf-page-'+(page.index+1),bytes:image.data,contentType:image.mime,anchor:{fromRow:2,fromColumn:0,fromRowOffset:0,fromColumnOffset:0,toRow:2,toColumn:0,toRowOffset:Math.round(height),toColumnOffset:Math.round(width)}})
        bytes=embedded.bytes
        warnings.push('Page '+(page.index+1)+': XLSX 扫描或降级页面原图已嵌入；OCR 已禁用，不宣称单元格可编辑。')
      }
      const pictures=await embedXlsxPageImages(bytes,irPages,converted.sheets);bytes=pictures.bytes;warnings.push(...pictures.warnings)
      warnings.push('XLSX 正文与表格重建为单元格；源图片以独立图片保留在标注参考区，矢量装饰和原图文相对排版尚不保真，请核对来源。')
    }
    result={pages:irPages.length,warnings,pageResults,scannedDocument:isScannedDocument(pageResults,irPages.length)}
  }
  const issues=['PDF 转换已生成；尚未通过完整内容与版式保真验收，请人工核对。']
  const warnings=[...result.warnings,'PDF 嵌入字体不保证原样嵌入 Office；字体可能替换、换行和字距可能变化，请核对实际显示。']
  if(source.catalog.has(PDFName.of('AcroForm'))||source.getPages().some(page=>page.node.has(PDFName.of('Annots'))))warnings.push('PDF 表单和批注的可编辑语义未转换，请核对其页面外观。')
  if(result.scannedDocument)warnings.push('来源主要为扫描页；OCR 已禁用，扫描页按原始图像保留，不宣称文字可编辑。')
  // Review happens after real bytes exist: review failures retain those bytes.
  try{
    if(options.format==='pptx'){
      const reopened=await openPptx(bytes)
      if(reopened.deck.slides.length!==pageCount)throw Error('实际幻灯片数量与来源页数不一致')
    }else if(options.format==='docx')await parseDocx(bytes)
    else{
      const zip=await JSZip.loadAsync(bytes)
      if(!zip.file('xl/workbook.xml')||!zip.file('xl/worksheets/sheet1.xml'))throw Error('实际工作簿缺少必要内容')
    }
  }catch(error){issues.push(`Office 结构复核未通过：${error instanceof Error?error.message:String(error)}`)}
  if(bytes.length>64*1024*1024)issues.push('实际转换文件超过 64 MiB，请减少来源页数后重试；本次实际产物已保留。')
  issues.push(...warnings)
  return {bytes,sha256:sha(bytes),size:bytes.length,sourceSha256:options.sourceSha256,format:options.format,pages:result.pages,warnings,pageResults:result.pageResults,scannedDocument:result.scannedDocument,validation:{ok:false as const,issues}}
}
