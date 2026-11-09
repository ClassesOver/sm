/** Exact-source adapter around pinned note reply drawing; never accept root fallback. */
import { PDFArray, PDFDict, PDFDocument, PDFHexString, PDFName, PDFNumber, PDFRawStream, PDFRef, PDFString } from 'pdf-lib'
import { applySaveRequest } from '../src/main/save-pdf'
import { markupDictionaryHash, markupSourceId } from './markup-delete'
import { normalizeAddedNoteDates } from './note-timestamps'
export interface ReplyTarget { annotationId: string; expectedAnnotationSha256: string; sourceRef: string; pageIndex: number; rect: [number,number,number,number]; contents: string; color: [number,number,number] }
function replyReferences(doc: PDFDocument, protectedSource: boolean): Map<string,number> | null {
  if (protectedSource) return null
  try {
    const objects = doc.context.enumerateIndirectObjects(); if (objects.length > 20000) return null
    const refs = new Map<string,number>(), containers = new Set<object>(), stack = objects.map(([,obj])=>obj)
    let budget = 200000
    while (stack.length) {
      if (--budget < 0) return null
      const obj = stack.pop()!
      if (obj instanceof PDFRef) { refs.set(obj.toString(),(refs.get(obj.toString())??0)+1); continue }
      if (obj instanceof PDFRawStream) { stack.push(obj.dict); continue }
      if (obj instanceof PDFDict || obj instanceof PDFArray) {
        if (containers.has(obj)) return null; containers.add(obj)
        if (obj instanceof PDFDict) {
          if (obj.has(PDFName.of('ByteRange')) || String(obj.get(PDFName.of('Type')))==='/Sig') return null
          for (const value of obj.values()) stack.push(value)
        } else for (const value of obj.asArray()) stack.push(value)
      }
    }
    return refs
  } catch { return null }
}
export function canAppendPendingReplies(doc: PDFDocument, protectedSource: boolean) { return replyReferences(doc,protectedSource)!==null }
export interface SavedReplyIdentity { annotationId:string;parentAnnotationId:string;sourceRef:string;parentRef:string;pageIndex:number }
export function inspectNoteThreads(doc: PDFDocument, sourceSha: string, protectedSource: boolean) {
  const targets = new Map<string,ReplyTarget>(), replies = new Map<string,SavedReplyIdentity>()
  const empty = () => ({roots:new Map<string,ReplyTarget>(),replies:new Map<string,SavedReplyIdentity>()})
  try {
    if (protectedSource) return {roots:targets,replies}
    const refs = replyReferences(doc, false); if (!refs) return {roots:targets,replies}
    const nodes: {raw:PDFRef;dict:PDFDict;pageIndex:number;index:number}[] = [], occurrences = new Map<string,number>()
    for (const [pageIndex,page] of doc.getPages().entries()) {
      const annots = page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)
      if (!annots) continue
      for (let index=0;index<annots.size();index++) {
        const raw=annots.get(index),dict=doc.context.lookup(raw,PDFDict)
        if (!(raw instanceof PDFRef)) continue
        occurrences.set(raw.toString(),(occurrences.get(raw.toString())??0)+1)
        if (String(dict.get(PDFName.of('Subtype')))==='/Text') nodes.push({raw,dict,pageIndex,index})
      }
    }
    const safe = (node:typeof nodes[number]) => {
      const d=node.dict,flags=d.get(PDFName.of('F')),parent=d.get(PDFName.of('P')),value=d.lookup(PDFName.of('Contents'))
      return occurrences.get(node.raw.toString())===1
        && !['RC','DS','DA','State','StateModel','Popup','Parent','StructParent'].some(key=>d.has(PDFName.of(key)))
        && (flags===undefined || flags instanceof PDFNumber && Number.isInteger(flags.asNumber()) && flags.asNumber()>=0 && flags.asNumber()<=28 && (flags.asNumber() & ~28)===0)
        && (parent===undefined || parent instanceof PDFRef && parent.toString()===doc.getPage(node.pageIndex).ref.toString())
        && (value instanceof PDFString || value instanceof PDFHexString)
    }
    const childrenByRef = new Map<string,typeof nodes>()
    for (const node of nodes) { const parent=node.dict.get(PDFName.of('IRT')); if (parent instanceof PDFRef) { const key=parent.toString(),children=childrenByRef.get(key)??[];children.push(node);childrenByRef.set(key,children) } }
    for (const root of nodes) {
      if (!safe(root) || root.dict.has(PDFName.of('IRT')) || root.dict.has(PDFName.of('RT'))) continue
      const children=childrenByRef.get(root.raw.toString())??[]
      if (refs.get(root.raw.toString())!==children.length+1 || children.some(child=>child.pageIndex!==root.pageIndex || !safe(child) || String(child.dict.get(PDFName.of('RT')))!=='/R' || refs.get(child.raw.toString())!==1)) continue
      const rect=root.dict.lookupMaybe(PDFName.of('Rect'),PDFArray)?.asArray().map(value=>value instanceof PDFNumber?value.asNumber():NaN)
      const color=root.dict.lookupMaybe(PDFName.of('C'),PDFArray)?.asArray().map(value=>value instanceof PDFNumber?value.asNumber():NaN) ?? [1,.85,0]
      const box=doc.getPage(root.pageIndex).getCropBox()
      if (!rect || rect.length!==4 || !rect.every(Number.isFinite) || rect[0]>=rect[2] || rect[1]>=rect[3] || rect[0]<box.x || rect[3]>box.y+box.height || rect[0]+20>box.x+box.width || rect[3]-18<box.y || color.length!==3 || color.some(value=>!Number.isFinite(value)||value<0||value>1)) continue
      const annotationId=markupSourceId(sourceSha,root.pageIndex,root.index)
      targets.set(annotationId,{annotationId,expectedAnnotationSha256:markupDictionaryHash(root.dict),sourceRef:root.raw.toString(),pageIndex:root.pageIndex,rect:rect as ReplyTarget['rect'],contents:(root.dict.lookup(PDFName.of('Contents')) as PDFString|PDFHexString).decodeText(),color:color as ReplyTarget['color']})
      for (const child of children) {
        const childId=markupSourceId(sourceSha,child.pageIndex,child.index)
        replies.set(childId,{annotationId:childId,parentAnnotationId:annotationId,sourceRef:child.raw.toString(),parentRef:root.raw.toString(),pageIndex:child.pageIndex})
      }
    }
  } catch { return empty() }
  return {roots:targets,replies}
}
export function inspectReplyTargets(doc:PDFDocument,sourceSha:string,protectedSource:boolean) { return inspectNoteThreads(doc,sourceSha,protectedSource).roots }
export interface NoteReply { target: ReplyTarget; contents: string; createdMs: number }
export async function appendNoteReplies(bytes: Uint8Array, replies: NoteReply[], outputOrder: number[]) {
  if (!replies.length) return bytes
  const before=await PDFDocument.load(bytes,{updateMetadata:false})
  for (const reply of replies) {
    const target=reply.target,page=before.getPages()[outputOrder.indexOf(target.pageIndex)],annots=page?.node.lookupMaybe(PDFName.of('Annots'),PDFArray)
    const matches=annots?.asArray().filter(raw=>raw instanceof PDFRef && raw.toString()===target.sourceRef) ?? []
    if (matches.length!==1 || markupDictionaryHash(before.context.lookup(matches[0],PDFDict))!==target.expectedAnnotationSha256) throw Error('pdf_reply_parent_identity_changed')
  }
  const drawings=replies.map(({target,contents,createdMs})=>({kind:'note' as const,pageIndex:outputOrder.indexOf(target.pageIndex),at:[target.rect[0],target.rect[3]] as [number,number],color:target.color,contents,createdMs,replyToSaved:{objNum:Number(target.sourceRef.split(' ')[0]),rect:target.rect,contents:target.contents}}))
  const result=await applySaveRequest(bytes,{path:'',markups:[],drawings,formValues:[],stamps:[],rotations:[],deletedPages:[]})
  const notes=replies.map(({target,contents,createdMs},index)=>({pageIndex:drawings[index].pageIndex,contents,createdMs,rect:[target.rect[0],target.rect[3]-18,target.rect[0]+20,target.rect[3]].map(value=>Math.round(value*100)/100),replyToRef:target.sourceRef}))
  const output=await normalizeAddedNoteDates(bytes,result.bytes,notes,[],before.getPages().map((_,i)=>i)),after=await PDFDocument.load(output,{updateMetadata:false})
  // Preserve every original annotation's exact reference and dictionary; only append replies.
  for (const [index,page] of before.getPages().entries()) {
    const old=page.node.lookupMaybe(PDFName.of('Annots'),PDFArray),current=after.getPage(index).node.lookupMaybe(PDFName.of('Annots'),PDFArray)
    for (let i=0;i<(old?.size()??0);i++) {
      if (!current || String(old!.get(i))!==String(current.get(i)) || markupDictionaryHash(before.context.lookup(old!.get(i),PDFDict))!==markupDictionaryHash(after.context.lookup(current.get(i),PDFDict))) throw Error('pdf_reply_existing_annotation_changed')
    }
  }
  return output
}
