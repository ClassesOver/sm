/** Reuse pinned localId/replyToLocalId drawings, with verified fresh PDF references. */
import { PDFArray, PDFDict, PDFDocument } from 'pdf-lib'
import { applySaveRequest } from '../src/main/save-pdf'
import { normalizeAddedNoteDates, type AddedNoteReference } from './note-timestamps'
import { markupDictionaryHash } from './markup-delete'
import { PDFName } from 'pdf-lib'
export interface LocalNoteRoot { localId:string;pageIndex:number;rect:[number,number,number,number];contents:string;color:[number,number,number];createdMs?:number }
export interface LocalNoteReply { parentLocalId:string;pageIndex:number;contents:string;createdMs:number;author?:'AI Assistant' }
export async function appendLocalNoteReplies(bytes:Uint8Array,roots:LocalNoteRoot[],replies:LocalNoteReply[],outputOrder:number[],references?:Map<string,AddedNoteReference>) {
 if(!roots.length&&!replies.length)return bytes
 const before=await PDFDocument.load(bytes,{updateMetadata:false}),byId=new Map(roots.map(root=>[root.localId,root]))
 if(byId.size!==roots.length)throw Error('pdf_local_reply_duplicate_root')
 const drawings=roots.map(root=>({kind:'note' as const,localId:root.localId,pageIndex:outputOrder.indexOf(root.pageIndex),at:[root.rect[0],root.rect[3]] as [number,number],contents:root.contents,color:root.color,createdMs:root.createdMs??0}))
 const children=replies.map(reply=>{const root=byId.get(reply.parentLocalId);if(!root||root.pageIndex!==reply.pageIndex||!outputOrder.includes(root.pageIndex))throw Error('pdf_local_reply_parent_invalid');return {kind:'note' as const,replyToLocalId:root.localId,pageIndex:outputOrder.indexOf(root.pageIndex),at:[root.rect[0],root.rect[3]] as [number,number],contents:reply.contents,color:root.color,createdMs:reply.createdMs,...(reply.author?{author:reply.author}:{})}})
 if(drawings.some(d=>d.pageIndex<0))throw Error('pdf_local_reply_page_missing')
 const result=await applySaveRequest(bytes,{path:'',markups:[],drawings:[...drawings,...children],formValues:[],stamps:[],rotations:[],deletedPages:[]})
 const notes=[...roots.map((root,i)=>({pageIndex:drawings[i].pageIndex,contents:root.contents,rect:[root.rect[0],root.rect[3]-18,root.rect[0]+20,root.rect[3]].map(value=>Math.round(value*100)/100),createdMs:root.createdMs,localId:root.localId})),...replies.map((reply,i)=>({pageIndex:children[i].pageIndex,contents:reply.contents,rect:[children[i].at[0],children[i].at[1]-18,children[i].at[0]+20,children[i].at[1]].map(value=>Math.round(value*100)/100),createdMs:reply.createdMs,replyToLocalId:reply.parentLocalId}))]
 const output=await normalizeAddedNoteDates(bytes,result.bytes,notes,[],before.getPages().map((_,i)=>i),undefined,references),after=await PDFDocument.load(output,{updateMetadata:false})
 for(const [index,page] of before.getPages().entries()){
  const old=page.node.lookupMaybe(PDFName.of('Annots'),PDFArray),current=after.getPage(index).node.lookupMaybe(PDFName.of('Annots'),PDFArray)
  for(let i=0;i<(old?.size()??0);i++)if(!current||String(old!.get(i))!==String(current.get(i))||markupDictionaryHash(before.context.lookup(old!.get(i),PDFDict))!==markupDictionaryHash(after.context.lookup(current.get(i),PDFDict)))throw Error('pdf_local_reply_existing_annotation_changed')
 }
 return output
}
