/** Move original whole text objects with the pinned translate path, never rebuild glyphs. */
import {createHash} from 'node:crypto'
import {PDFDocument} from 'pdf-lib'
import {staticTextAvailability} from './static-text'
import {inspectNativeText} from './text-operations'
import {applyTextEdits,validateTextEdits} from '../src/main/text-edit'
import type {TextEditInput} from '../src/shared/ipc'
const hash=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex')
export interface MoveTextOperation{kind:'moveText';sourceSha256:string;pageId:string;objectId:string;expectedTextSha256:string;delta:[number,number]}
export async function moveSourceText(content:Uint8Array,operations:MoveTextOperation[],expectedSha256:string){
 const sourceSha256=hash(content)
 if(sourceSha256!==expectedSha256||operations.some(op=>op.sourceSha256!==sourceSha256))throw Error('PDF 来源摘要不匹配')
 const document=await PDFDocument.load(content,{updateMetadata:false}),available=staticTextAvailability(document)
 if(!available.insertText)throw Error(available.insertTextReason!)
 const pageGeometry=(doc:PDFDocument)=>doc.getPages().map(page=>({mediaBox:page.getMediaBox(),cropBox:page.getCropBox(),rotation:page.getRotation().angle}))
 const originalGeometry=JSON.stringify(pageGeometry(document))
 const before=await inspectNativeText(content,sourceSha256),used=new Set<string>()
 const targets=operations.map(op=>{
  const pageIndex=document.getPages().findIndex((_,index)=>op.pageId===`sha256:${sourceSha256}:page:${index}`),target=before[pageIndex]?.find(item=>item.objectId===op.objectId&&item.expectedTextSha256===op.expectedTextSha256)
  if(!target||!target.text.trim()||used.has(op.objectId))throw Error('移动文字对象身份无效、已变化或重复')
  used.add(op.objectId)
  const rect=target.rect,box=document.getPage(pageIndex).getCropBox(),[dx,dy]=op.delta
  if(rect[0]+dx<box.x||rect[1]+dy<box.y||rect[2]+dx>box.x+box.width||rect[3]+dy>box.y+box.height)throw Error('移动后的文字超出页面裁切范围')
  const overlaps=before[pageIndex]!.filter(item=>Math.max(0,Math.min(item.rect[2],rect[2])-Math.max(item.rect[0],rect[0]))*Math.max(0,Math.min(item.rect[3],rect[3])-Math.max(item.rect[1],rect[1]))>(rect[2]-rect[0])*(rect[3]-rect[1])*.5)
  if(overlaps.length!==1)throw Error('移动文字对象范围存在歧义')
  return {pageIndex,target}
 })
 const edits:TextEditInput[]=targets.map(({pageIndex,target},index)=>({pageIndex,rect:[...target.rect],oldText:target.text,newText:target.text,fontSize:target.fontSize,translate:operations[index]!.delta}))
 const validations=await validateTextEdits(content,edits)
 if(validations.some(item=>item.reason))throw Error(validations.map(item=>item.reason).filter(Boolean).join('; '))
 let bytes=content
 const skippedOperations:{operationIndex:number;kind:'moveText';pageId:string;reason:string}[]=[],warn=(index:number,reason:string)=>{if(!skippedOperations.some(skip=>skip.operationIndex===index))skippedOperations.push({operationIndex:index,kind:'moveText',pageId:operations[index]!.pageId,reason})}
 try{
  const result=await applyTextEdits(content,edits);bytes=result.bytes
  for(const [index,edit]of edits.entries()){const failure=result.skipped.find(skip=>skip.pageIndex===edit.pageIndex&&skip.oldText===edit.oldText);if(failure)warn(index,failure.reason)}
  try{
   const after=await inspectNativeText(bytes,hash(bytes))
   if(after.length!==before.length)throw Error('page count changed')
   if(JSON.stringify(pageGeometry(await PDFDocument.load(bytes,{updateMetadata:false})))!==originalGeometry)throw Error('page geometry changed')
   for(const [pageIndex,originals]of before.entries()){
    const remaining=[...after[pageIndex]!]
    for(const original of originals){
     const index=targets.findIndex(target=>target.target.objectId===original.objectId),delta=index>=0&&!skippedOperations.some(skip=>skip.operationIndex===index)?operations[index]!.delta:[0,0]
     const match=remaining.findIndex(item=>item.text.trimEnd()===original.text.trimEnd()&&item.fontName===original.fontName&&item.fontSha256===original.fontSha256&&Math.abs(item.fontSize-original.fontSize)<.05&&item.rect.every((value,axis)=>Math.abs(value-original.rect[axis]!-(delta[axis%2]??0))<.05))
     if(match<0)throw Error('original text font or expected geometry changed')
     remaining.splice(match,1)
    }
    if(remaining.length)throw Error('unexpected output text')
   }
  }catch(error){operations.forEach((_,index)=>warn(index,`pdf_move_text_output_review_failed: ${error instanceof Error?error.message:String(error)}`))}
 }catch(error){operations.forEach((_,index)=>warn(index,`pdf_move_text_failed: ${error instanceof Error?error.message:String(error)}`))}
 skippedOperations.sort((a,b)=>a.operationIndex-b.operationIndex)
 const appliedOperationIndices=operations.flatMap((_,index)=>skippedOperations.some(skip=>skip.operationIndex===index)?[]:[index]),outputSha256=hash(bytes)
 return {bytes,sourceSha256,sha256:outputSha256,size:bytes.length,appliedOperationIndices,skippedOperations,previewDigest:hash(JSON.stringify({sourceSha256,operations,outputSha256,appliedOperationIndices,skippedOperations}))}
}
