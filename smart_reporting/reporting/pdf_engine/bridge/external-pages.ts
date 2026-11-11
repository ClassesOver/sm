/** 外部 PDF 字节仅来自有界上传；固定源 insertPdfBytes/replacePagesBytes 负责写入。 */
import { createHash } from 'node:crypto'
import { PDFArray, PDFDict, PDFDocument, PDFName, PDFRawStream, PDFRef, type PDFObject } from 'pdf-lib'
import { z } from 'zod'
import { insertPdfBytes, replacePagesBytes } from '../src/main/save-pdf'
import { inspectNativeText } from './text-operations'

export const EXTERNAL_PDF_MAX_BYTES = 6 * 1024 * 1024
const sha = (bytes: Uint8Array | string) => createHash('sha256').update(bytes).digest('hex')
const digest = z.string().regex(/^[a-f0-9]{64}$/)
const common = { kind:z.literal('externalPages'), sourceSha256:digest, externalSha256:digest, bytesBase64:z.string().min(8).max(4*Math.ceil(EXTERNAL_PDF_MAX_BYTES/3)) }
const schema = z.discriminatedUnion('action',[
  z.object({...common,action:z.literal('insert'),afterPageIndex:z.number().int().min(-1)}).strict(),
  z.object({...common,action:z.literal('replace'),pages:z.array(z.number().int().nonnegative()).min(1).max(10000)}).strict(),
])
async function safeDocument(bytes:Uint8Array) {
  if (!bytes.length || bytes.length>24*1024*1024 || Buffer.from(bytes.subarray(0,5)).toString()!=='%PDF-') throw Error('PDF 内容无效或超过上限')
  const doc=await PDFDocument.load(bytes,{updateMetadata:false})
  if(doc.isEncrypted || ['AcroForm','Perms','Names','Dests','Outlines','OpenAction','AA','StructTreeRoot','Threads','Collection'].some(key=>doc.catalog.has(PDFName.of(key))) || doc.getPageCount()<1 || doc.getPageCount()>10000) throw Error('含表单、保护或导航结构的 PDF 暂不支持外部页面操作')
  for(const page of doc.getPages()){
    const annotations=page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)
    if(annotations?.size() || page.node.has(PDFName.of('AA')) || page.node.has(PDFName.of('StructParents')))throw Error('含批注或页面动作的 PDF 暂不支持外部页面操作')
  }
  return doc
}
async function pageIdentity(bytes:Uint8Array,doc:PDFDocument){
  const text=await inspectNativeText(bytes,sha(bytes))
  let visits=0
  function canonical(value:PDFObject|undefined,seen=new Set<string>(),depth=0):unknown{
    if(++visits>200000||depth>40)throw Error('PDF 页面资源过于复杂，暂不支持外部页面操作')
    if(value instanceof PDFRef){const key=value.toString();if(seen.has(key))throw Error('PDF 页面资源循环引用，暂不支持');return canonical(doc.context.lookup(value),new Set([...seen,key]),depth+1)}
    if(value instanceof PDFRawStream)return {dictionary:canonical(value.dict,seen,depth+1),stream:sha(value.getContents())}
    if(value instanceof PDFArray)return Array.from({length:value.size()},(_,index)=>canonical(value.get(index),seen,depth+1))
    if(value instanceof PDFDict)return Object.fromEntries(value.entries().sort(([a],[b])=>a.toString().localeCompare(b.toString())).filter(([key])=>key.toString()!=='/Length').map(([key,item])=>[key.toString(),canonical(item,seen,depth+1)]))
    return value?.toString()??null
  }
  return doc.getPages().map((page,index)=>({mediaBox:page.getMediaBox(),cropBox:page.getCropBox(),bleedBox:page.getBleedBox(),trimBox:page.getTrimBox(),artBox:page.getArtBox(),rotation:page.getRotation().angle,userUnit:String(page.node.getInheritableAttribute(PDFName.of('UserUnit'))??'1'),contents:canonical(page.node.get(PDFName.of('Contents'))),resources:canonical(page.node.getInheritableAttribute(PDFName.of('Resources'))),text:(text[index]??[]).map(({objectId,...object})=>object)}))
}
export async function patchExternalPages(content:Uint8Array,rawOperation:unknown,expectedSha256:string){
  const operation=schema.parse(rawOperation), sourceSha256=sha(content)
  if(expectedSha256!==sourceSha256 || operation.sourceSha256!==sourceSha256)throw Error('父 PDF 来源摘要不匹配')
  const external=Buffer.from(operation.bytesBase64,'base64')
  if(external.length<1 || external.length>EXTERNAL_PDF_MAX_BYTES || external.toString('base64')!==operation.bytesBase64 || sha(external)!==operation.externalSha256)throw Error('外部 PDF 内容或摘要无效')
  const source=await safeDocument(content), other=await safeDocument(external), count=source.getPageCount()
  let order:{source:boolean;index:number}[]=Array.from({length:count},(_,index)=>({source:true,index}))
  const externalOrder=Array.from({length:other.getPageCount()},(_,index)=>({source:false,index}))
  if(operation.action==='insert'){
    if(operation.afterPageIndex>=count)throw Error('插入位置超出父 PDF 页数')
    order.splice(operation.afterPageIndex+1,0,...externalOrder)
  }else{
    if(new Set(operation.pages).size!==operation.pages.length || operation.pages.some(page=>page>=count))throw Error('替换页码重复或超出父 PDF 页数')
    const selected=new Set(operation.pages),at=Math.min(...operation.pages)
    order=order.filter(page=>!selected.has(page.index));order.splice(at,0,...externalOrder)
  }
  if(order.length>10000)throw Error('输出 PDF 页数超过上限')
  const [a,b]=await Promise.all([pageIdentity(content,source),pageIdentity(external,other)])
  const expected=JSON.stringify(order.map(page=>(page.source?a:b)[page.index]))
  const bytes=operation.action==='insert'?(await insertPdfBytes(content,external,operation.afterPageIndex)).merged:(await replacePagesBytes(content,external,operation.pages)).merged
  const outputSha256=sha(bytes)
  const skippedOperations:{operationIndex:number;kind:'externalPages';reason:string}[]=[]
  try{
    const output=await safeDocument(bytes),result=await pageIdentity(bytes,output)
    if(JSON.stringify(result)!==expected)throw Error('output_identity_mismatch')
  }catch{
    skippedOperations.push({operationIndex:0,kind:'externalPages',reason:'外部页面输出复核未通过；实际 PDF 已生成并保留，请人工核对页序、内容及页面范围'})
  }
  return {bytes,sourceSha256,externalSha256:operation.externalSha256,sha256:outputSha256,size:bytes.length,pageCount:order.length,appliedOperationIndices:skippedOperations.length?[]:[0],skippedOperations,previewDigest:sha(JSON.stringify({sourceSha256,externalSha256:operation.externalSha256,action:operation.action,order,outputSha256,skippedOperations}))}
}
