/** 仅为未保护的安全来源创建加密下载，不持久化明文密码。 */
import {createHash} from 'node:crypto'
import {PDFDocument,PDFName} from 'pdf-lib'
import {z} from 'zod'
import {decryptDocument,encryptDocument} from '../src/main/pdf-crypt'

const sha=(bytes:Uint8Array)=>createHash('sha256').update(bytes).digest('hex')
const password=z.string().min(1).refine(value=>Buffer.byteLength(value,'utf8')<=127)
const permissions=z.object({printing:z.boolean(),modifying:z.boolean(),annotating:z.boolean(),copying:z.boolean()}).strict()
const schema=z.object({sourceSha256:z.string().regex(/^[a-f0-9]{64}$/),userPassword:password,ownerPassword:password,permissions}).strict()
const geometry=(doc:PDFDocument)=>doc.getPages().map(page=>({media:page.getMediaBox(),crop:page.getCropBox(),rotation:page.getRotation().angle}))

export async function protectPdf(content:Uint8Array,rawInput:unknown){
 const input=schema.parse(rawInput),sourceSha256=sha(content)
 if(input.sourceSha256!==sourceSha256)throw Error('PDF 来源摘要不匹配')
 const document=await PDFDocument.load(content,{updateMetadata:false})
 if(document.isEncrypted||document.context.trailerInfo.Encrypt||document.catalog.has(PDFName.of('Perms'))||document.catalog.has(PDFName.of('AcroForm')))throw Error('当前仅支持未加密且不含表单或签名保护结构的 PDF')
 const before=JSON.stringify(geometry(document))
 encryptDocument(document,input)
 const bytes=await document.save({useObjectStreams:false,updateFieldAppearances:false})
 const reviewIssues:string[]=[]
 try{
  const reader=await decryptDocument(bytes,input.userPassword),owner=await decryptDocument(bytes,input.ownerPassword)
  const reopened=await PDFDocument.load(reader.bytes,{updateMetadata:false})
  if(JSON.stringify(reader.permissions)!==JSON.stringify(input.permissions)||JSON.stringify(owner.permissions)!==JSON.stringify(input.permissions)||JSON.stringify(geometry(reopened))!==before)reviewIssues.push('pdf_protection_output_review_mismatch')
  if(input.userPassword!==input.ownerPassword&&owner.unlockedAs!=='owner')reviewIssues.push('pdf_protection_owner_review_failed')
 }catch{reviewIssues.push('pdf_protection_output_review_failed')}
 return {bytes,sourceSha256,sha256:sha(bytes),size:bytes.length,reviewIssues,algorithm:'AES-256',revision:6}
}
