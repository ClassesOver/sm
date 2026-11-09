import { validatePendingPdfNote } from './pdf-notes'
import type { NativeOperation } from './native-draft'
import type { PdfPageIdentity } from './pdf-operations'
export function validatePdfReplies(pages: PdfPageIdentity[], operations: NativeOperation[]) {
 const replies=operations.filter(op=>['replyNote','replyPendingNote'].includes(op.kind))
 const ids=operations.filter(op=>op.kind==='addTextAnnotation'&&op.localId!==undefined).map(op=>op.localId)
 if(new Set(ids).size!==ids.length)throw Error('待保存根便签身份重复')
 if(replies.length && operations.some(op=>['replaceText','setPageSize','cropPage'].includes(op.kind)))throw Error('回复与原位改字、页面尺寸或裁切请分别保存重开')
 for(const op of replies){
  if(op.kind==='replyPendingNote'){
   const root=operations.find(root=>root.kind==='addTextAnnotation'&&root.localId===op.parentLocalId),page=pages.find(page=>page.pageId===op.pageId)
   if(!page||!root||root.pageId!==op.pageId||typeof op.parentLocalId!=='string'||!/^[a-f0-9]{32}$/.test(op.parentLocalId)||Object.keys(op).some(key=>!['kind','pageId','parentLocalId','contents','createdMs','sourceSha256'].includes(key))||(op.sourceSha256!==undefined&&page.pageId!==`sha256:${op.sourceSha256}:page:${page.index}`))throw Error('待保存回复的根便签身份无效')
   validatePendingPdfNote(root,page);validateReplyContents(op)
   if(operations.some(other=>other.kind==='deletePage'&&other.pageId===op.pageId))throw Error('待保存回复不能引用已删除页面')
   continue
  }
  const page=pages.find(page=>page.pageId===op.pageId),note=page?.notes?.find(note=>note.annotationId===op.annotationId)
  if(Object.keys(op).some(key=>!['kind','pageId','annotationId','expectedAnnotationSha256','contents','createdMs','sourceSha256'].includes(key)) || !page?.notesReadSafe || !note?.replyable || !/^[a-f0-9]{64}$/.test(String(op.annotationId)) || note.expectedAnnotationSha256!==op.expectedAnnotationSha256 || (op.sourceSha256!==undefined && page.pageId!==`sha256:${op.sourceSha256}:page:${page.index}`))throw Error('回复根便签身份已过期或当前线程仅可查看')
  validateReplyContents(op)
  if(operations.some(other=>other.pageId===op.pageId && (other.kind==='deletePage'||(['editNote','removeNote'].includes(other.kind)&&other.annotationId===op.annotationId))))throw Error('回复根便签不能在同一批编辑或删除')
 }
}
function validateReplyContents(op:NativeOperation){if(typeof op.contents!=='string'||!op.contents.trim()||op.contents!==op.contents.trim()||op.contents.length>10000||typeof op.createdMs!=='number'||!Number.isSafeInteger(op.createdMs)||op.createdMs<0||op.createdMs>253402300799999)throw Error('回复正文或创建时间无效')}
export function stagePdfReply(pages:PdfPageIdentity[],operations:NativeOperation[],pageId:string,annotationId:string,contents:string,createdMs=Date.now()) {
 const note=pages.find(page=>page.pageId===pageId)?.notes?.find(note=>note.annotationId===annotationId)
 const next=[...structuredClone(operations),{kind:'replyNote',pageId,annotationId,expectedAnnotationSha256:note?.expectedAnnotationSha256,contents:contents.trim(),createdMs}]
 validatePdfReplies(pages,next);if(next.length>500)throw Error('回复将超过500条操作，请先保存');return next
}
export function stagePendingPdfReply(pages:PdfPageIdentity[],operations:NativeOperation[],reference:{index:number;snapshot:string},contents:string|null) {
 if(!Number.isInteger(reference.index)||JSON.stringify(operations)!==reference.snapshot||!['replyNote','replyPendingNote'].includes(operations[reference.index]?.kind))throw Error('草稿已变化，请重新选择待保存回复')
 validatePdfReplies(pages,operations);const next=structuredClone(operations)
 if(contents===null)next.splice(reference.index,1);else next[reference.index].contents=contents.trim()
 validatePdfReplies(pages,next);return next
}

/** Assign legacy roots an identity in the same history transaction as their first reply. */
export function stagePdfLocalReply(pages:PdfPageIdentity[],operations:NativeOperation[],reference:{index:number;snapshot:string},contents:string,createdMs=Date.now(),newId=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('')) {
 if(!Number.isInteger(reference.index)||JSON.stringify(operations)!==reference.snapshot||operations[reference.index]?.kind!=='addTextAnnotation')throw Error('草稿已变化，请重新选择根便签')
 const next=operations.map(op=>structuredClone(op)),root=next[reference.index],page=pages.find(page=>page.pageId===root.pageId)
 if(!page)throw Error('根便签来源页面已过期');validatePendingPdfNote(root,page)
 root.localId??=newId()
 next.push({kind:'replyPendingNote',pageId:root.pageId,parentLocalId:root.localId,contents:contents.trim(),createdMs})
 validatePdfReplies(pages,next);if(next.length>500)throw Error('回复将超过500条操作，请先保存');return next
}
