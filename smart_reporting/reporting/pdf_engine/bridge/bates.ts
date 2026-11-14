import {PDFDict,PDFDocument,PDFName,PDFSignature} from 'pdf-lib'
import {formatBates} from '../vendor/bates/bates'
import {validateBatesOperation,type BatesOperation} from '../vendor/bates/protocol'
import type {TextInsertInput} from '../src/shared/ipc'
import {inspectTextObjects} from '../src/main/text-edit'
export function batesAvailability(document:PDFDocument){
 try{
  if(document.isEncrypted||document.context.trailerInfo.Encrypt||document.catalog.has(PDFName.of('Perms'))||document.catalog.lookupMaybe(PDFName.of('AcroForm'),PDFDict)?.has(PDFName.of('XFA'))||document.getForm().getFields().some(field=>field instanceof PDFSignature))throw Error('protected')
  return {bates:true,batesReason:null as string|null}
 }catch{return {bates:false,batesReason:'来源含签名、加密保护或动态表单，暂不支持 Bates 编号'}}
}
export interface BatesPlan {operationIndex:number;pageId:string;input:TextInsertInput}
export function prepareBates(operations:{kind:string;[key:string]:unknown}[],sourceSha256:string,pages:{pageId:string;index:number;mediaBox:{x:number;y:number;width:number;height:number}}[],blankIndex:Map<string,number>,deleted:Set<string>):BatesPlan[]{
 const known=new Set([...pages.map(page=>page.pageId),...blankIndex.keys()]),plans:BatesPlan[]=[]
 for(const [operationIndex,raw]of operations.entries()){
  if(raw.kind!=='addBates')continue
  const operation=raw as unknown as BatesOperation;validateBatesOperation(operation,known,sourceSha256)
  for(const entry of operation.entries){
   const source=pages.find(page=>page.pageId===entry.pageId),blank=operations.find(op=>op.kind==='insertBlankPage'&&op.pageId===entry.pageId)
   const box=source?.mediaBox??{x:0,y:0,width:Number(blank?.width),height:Number(blank?.height)}
   if(entry.origin[0]<box.x||entry.origin[1]<box.y||entry.origin[0]>box.x+box.width||entry.origin[1]>box.y+box.height)throw Error('Bates 文字位置超出来源页面')
   if(deleted.has(entry.pageId))continue
   const cfg=operation.config
   plans.push({operationIndex,pageId:entry.pageId,input:{pageIndex:source?.index??blankIndex.get(entry.pageId)!,origin:entry.origin,text:formatBates(cfg.prefix,cfg.start+entry.ordinal,cfg.digits),fontSize:cfg.fontSize,color:cfg.color.map(value=>Math.round(value*255)) as [number,number,number],align:cfg.position.endsWith('right')?'right':cfg.position.endsWith('center')?'center':'left',lineXOffsets:entry.lineXOffsets,rotate:entry.rotate}})
  }
 }
 return plans
}
/** 独立提取文字复核只追加告警，不能丢弃已生成字节或中断下载。 */
export async function reviewBatesOutput(bytes:Uint8Array,plans:BatesPlan[],finalOrder:number[]){
 if(!plans.length)return []
 const issues:{operationIndex:number;kind:string;fieldName:string;code:string;message:string}[]=[]
 const issue=(index:number,code:string,message:string)=>{if(!issues.some(row=>row.operationIndex===index&&row.code===code))issues.push({operationIndex:index,kind:'addBates',fieldName:'',code,message})}
 try{
  const text=await inspectTextObjects(bytes),doc=await PDFDocument.load(bytes,{updateMetadata:false}),remaining=text.map(items=>[...items])
  for(const plan of plans){
   const index=finalOrder.indexOf(plan.input.pageIndex);if(index<0)continue
   const match=remaining[index]?.findIndex(item=>item.text.trimEnd()===plan.input.text&&Math.abs(item.fontSize-plan.input.fontSize)<.1)??-1
   if(match<0){issue(plan.operationIndex,'pdf_bates_output_not_extractable','Bates 编号未能按请求从实际 PDF 独立提取；已保留生成文件，请人工核对。');continue}
   const item=remaining[index]!.splice(match,1)[0]!,box=doc.getPage(index).getCropBox()
   if(item.rect[0]<box.x||item.rect[1]<box.y||item.rect[2]>box.x+box.width||item.rect[3]>box.y+box.height)issue(plan.operationIndex,'pdf_bates_output_clipped','Bates 编号可能超出最终裁切范围；已保留生成文件，请核对实际预览。')
  }
 }catch(error){for(const index of new Set(plans.map(plan=>plan.operationIndex)))issue(index,'pdf_bates_output_review_failed','Bates 写入后的独立文字复核失败；已保留实际生成文件：'+String(error))}
 return issues
}
