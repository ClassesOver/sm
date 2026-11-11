import { expect, it } from 'vitest'
import { stagePdfReply, stagePendingPdfReply, validatePdfReplies } from './pdf-replies'
import { projectPageComments } from './pdf-comments'
import { pdfPageState, deletePdfPage } from './pdf-operations'
import { stagePdfNote } from './pdf-notes'
const note={sourceRef:'20R',annotationId:'a'.repeat(64),expectedAnnotationSha256:'b'.repeat(64),contents:'root',removalReason:null,editable:true,removable:true,replyable:true}
const page={pageId:'p',index:0,rotation:0,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:0,y:0,width:300,height:400},notes:[note],notesReadSafe:true},pages=[page,{...page,pageId:'p2',index:1,notes:[]}]
it('stages exact-root replies, validates restored drafts and keeps creation instant through edits',()=>{
 const ops=stagePdfReply(pages,[],'p',note.annotationId,' reply ',123);expect(ops[0].contents).toBe('reply');expect(pdfPageState(pages,ops)).toHaveLength(2)
 const ref={index:0,snapshot:JSON.stringify(ops)},changed=stagePendingPdfReply(pages,ops,ref,'changed');expect(changed[0].createdMs).toBe(123);expect(changed[0].contents).toBe('changed');expect(stagePendingPdfReply(pages,ops,ref,null)).toEqual([])
 expect(()=>stagePendingPdfReply(pages,changed,ref,null)).toThrow(/草稿已变化/)
 for(const operations of [[{...ops[0],extra:1}],[{...ops[0],createdMs:NaN}],[{...ops[0],expectedAnnotationSha256:'0'.repeat(64)}],[...ops,{kind:'cropPage'}],[...ops,{kind:'editNote',annotationId:note.annotationId,pageId:'p'}],[...ops,{kind:'deletePage',pageId:'p'}]])expect(()=>validatePdfReplies(pages,operations)).toThrow()
 expect(()=>stagePdfReply([{...page,notes:[{...note,replyable:false}]}],[],'p',note.annotationId,'reply')).toThrow()
 expect(()=>stagePdfNote(pages,ops,'p',note.annotationId,'changed')).toThrow(/回复/)
 const deleted=deletePdfPage(pages,ops,'p');expect(deleted.some(op=>op.kind==='replyNote')).toBe(false)
})
it('projects replies under exact saved root and keeps preview/pending roots readonly',()=>{
 const ops=stagePdfReply(pages,[],'p',note.annotationId,'pending',123),raw=[{id:'20R',annotationType:1,subtype:'Text',contentsObj:{str:'root'}}]
 const roots=projectPageComments(raw,page,1,ops,false);expect(roots[0].replyAnnotationId).toBe(note.annotationId);expect(roots[0].replies[0].contents).toBe('pending');expect(roots[0].replies[0].pendingReply).toBe(true)
 expect(projectPageComments(raw,page,1,ops,true)[0].replyAnnotationId).toBeUndefined();expect(projectPageComments(raw,page,1,ops,true)[0].replies).toHaveLength(0)
})
