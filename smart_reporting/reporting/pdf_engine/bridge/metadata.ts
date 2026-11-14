import {PDFDict,PDFDocument,PDFName,PDFSignature} from 'pdf-lib'
import {metadataFields,normalizedKeywords,type MetadataOperation} from '../vendor/metadata/protocol'
export function metadataAvailability(document:PDFDocument){
 try{
  if(document.isEncrypted||document.context.trailerInfo.Encrypt||document.catalog.has(PDFName.of('Perms'))||document.catalog.lookupMaybe(PDFName.of('AcroForm'),PDFDict)?.has(PDFName.of('XFA'))||(document.catalog.has(PDFName.of('AcroForm'))&&document.getForm().getFields().some(field=>field instanceof PDFSignature)))throw Error('protected')
  return {editMetadata:true,editMetadataReason:null as string|null}
 }catch{return {editMetadata:false,editMetadataReason:'来源含签名、加密保护或动态表单，文档属性仅可查看'}}
}
/** 固定源写入器在保存时设当前日期；不可变草稿固定应用时刻，保证预览/保存摘要可复现。 */
export async function freezeMetadataDate(bytes:Uint8Array,operation:MetadataOperation){
 const document=await PDFDocument.load(bytes,{updateMetadata:false});document.setModificationDate(new Date(operation.modifiedMs));return document.save()
}
/** 写后复核只报告告警，实际文件与下载继续保留。 */
export async function reviewMetadataOutput(bytes:Uint8Array,operation:MetadataOperation,operationIndex:number){
 const issue=(code:string,message:string)=>[{operationIndex,kind:'setMetadata',fieldName:'',code,message}]
 try{
  const doc=await PDFDocument.load(bytes,{updateMetadata:false}),actual={title:doc.getTitle()??'',author:doc.getAuthor()??'',subject:doc.getSubject()??'',keywords:doc.getKeywords()??''}
  const mismatch=metadataFields.filter(key=>actual[key]!== (key==='keywords'?normalizedKeywords(operation.metadata[key]):operation.metadata[key]))
  if(mismatch.length||doc.getModificationDate()?.getTime()!==Math.floor(operation.modifiedMs/1000)*1000)return issue('pdf_metadata_output_mismatch','文档属性写后复核不一致（'+[...mismatch,...(doc.getModificationDate()?.getTime()!==Math.floor(operation.modifiedMs/1000)*1000?['修改时间']:[])].join('、')+'）；实际生成文件已保留，请人工核对。')
  return []
 }catch(error){return issue('pdf_metadata_output_review_failed','文档属性写后复核失败，实际生成文件已保留，请人工核对：'+String(error))}
}
