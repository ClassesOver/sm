/** Source-bound text replacement followed by searchable inserts; no page structural edits. */
import {createHash} from 'node:crypto'
import {replaceStyledText,type StyledReplaceTextOperation} from './replace-text-style'
import {insertStaticTexts,staticTextTargets,type StaticTextOperation} from './static-text'
const hash=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex')
type MixedTextOperation=StyledReplaceTextOperation|StaticTextOperation
export async function replaceAndInsertText(content:Uint8Array,operations:MixedTextOperation[],expectedSha256:string){
 const sourceSha256=hash(content)
 if(expectedSha256!==sourceSha256||operations.some(op=>op.sourceSha256!==undefined&&op.sourceSha256!==sourceSha256))throw Error('PDF 来源摘要不匹配')
 const inserts=operations.flatMap((op,index)=>op.kind==='insertText'?[{op,index}]:[]),replacements=operations.flatMap((op,index)=>op.kind==='replaceText'?[{op,index}]:[])
 const targets=await staticTextTargets(content,inserts.map(item=>item.op),sourceSha256)
 const replaced=await replaceStyledText(content,replacements.map(item=>({...item.op,sourceSha256})),sourceSha256)
 let bytes=replaced.bytes
 const appliedOperationIndices=replaced.appliedOperationIndices.map(index=>replacements[index]!.index)
 const skippedOperations:{operationIndex:number;kind:'insertText'|'replaceText';pageId:string;reason:string}[]=replaced.skippedOperations.map(skip=>({...skip,operationIndex:replacements[skip.operationIndex]!.index}))
 try{
  const intermediateSha256=hash(bytes)
  const rebound=inserts.map(({op},index)=>({...op,sourceSha256:intermediateSha256,pageId:`sha256:${intermediateSha256}:page:${targets[index]}`}))
  const inserted=await insertStaticTexts(bytes,rebound,intermediateSha256)
  bytes=inserted.bytes
  appliedOperationIndices.push(...inserted.appliedOperationIndices.map(index=>inserts[index]!.index))
  skippedOperations.push(...inserted.skippedOperations.map(skip=>({...skip,operationIndex:inserts[skip.operationIndex]!.index,pageId:inserts[skip.operationIndex]!.op.pageId})))
 }catch(error){
  for(const {op,index}of inserts)skippedOperations.push({operationIndex:index,kind:'insertText',pageId:op.pageId,reason:`pdf_insert_text_failed: ${error instanceof Error?error.message:String(error)}`})
 }
 appliedOperationIndices.sort((a,b)=>a-b);skippedOperations.sort((a,b)=>a.operationIndex-b.operationIndex)
 const outputSha256=hash(bytes)
 return {bytes,sourceSha256,sha256:outputSha256,size:bytes.length,appliedOperationIndices,skippedOperations,previewDigest:hash(JSON.stringify({sourceSha256,operations,outputSha256,appliedOperationIndices,skippedOperations}))}
}
