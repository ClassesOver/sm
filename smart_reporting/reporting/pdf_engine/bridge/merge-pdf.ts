/** 固定源多文件合并：基文档完整加载，外部页按调用顺序追加。 */
import {createHash} from 'node:crypto'
import {PDFDocument,PDFName} from 'pdf-lib'
import {mergePdfBytes} from '../src/main/save-pdf'

const sha=(bytes:Uint8Array)=>createHash('sha256').update(bytes).digest('hex')
export async function mergePdf(content:Uint8Array,others:Uint8Array[]){
  if(!others.length)throw Error('至少选择一份外部 PDF')
  const inputs=[content,...others]
  const documents=await Promise.all(inputs.map(bytes=>PDFDocument.load(bytes,{updateMetadata:false})))
  const expected=documents.flatMap(document=>document.getPages().map(page=>({media:page.getMediaBox(),crop:page.getCropBox(),rotation:page.getRotation().angle})))
  const {merged:bytes,appended}=await mergePdfBytes(content,others)
  const reviewIssues:string[]=[]
  // copyPages 不导入外部文档的字段树、目录与附件目录；保留源行为并如实告警。
  if(documents.slice(1).some(document=>['AcroForm','Outlines','Names','Dests'].some(key=>document.catalog.has(PDFName.of(key)))))reviewIssues.push('外部 PDF 的表单字段树、目录或附件目录不保证迁移完整；页面已按源合并流程追加，请下载核对。')
  try{
    const output=await PDFDocument.load(bytes,{updateMetadata:false})
    const actual=output.getPages().map(page=>({media:page.getMediaBox(),crop:page.getCropBox(),rotation:page.getRotation().angle}))
    if(JSON.stringify(actual)!==JSON.stringify(expected))throw Error('merge_output_review_failed')
  }catch{reviewIssues.push('合并 PDF 后置页面复核未通过；实际文件已保留，请核对内容与页序。')}
  return{bytes,sourceSha256:sha(content),externalSha256s:others.map(sha),sha256:sha(bytes),size:bytes.length,pageCount:expected.length,appendedCount:appended,reviewIssues}
}
