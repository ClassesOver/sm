import { expect,it } from 'vitest'
import { stagePdfLocalReply, stagePendingPdfReply, validatePdfReplies } from './pdf-replies'
import { stagePendingPdfNote } from './pdf-notes'
import { projectPageComments } from './pdf-comments'
import { pdfPageState } from './pdf-operations'
import { NativeDraft, type NativeOperation } from './native-draft'
const id='a'.repeat(32),page={pageId:'p',index:0,rotation:0,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:0,y:0,width:300,height:400},notes:[],notesReadSafe:true},pages=[page,{...page,pageId:'q',index:1}]
const root={kind:'addTextAnnotation',pageId:'p',text:'same',rect:[30,100,50,118]}
const ref=(ops:NativeOperation[],index=0)=>({index,snapshot:JSON.stringify(ops)})
it('migrates exactly one legacy root atomically and projects duplicate-looking local threads',()=>{
 const ops=stagePdfLocalReply(pages,[root,root],ref([root,root],1),' reply ',123,()=>id)
 expect(ops[0].localId).toBeUndefined();expect(ops[1].localId).toBe(id);expect(ops[1].createdMs).toBeUndefined();expect(ops[2].contents).toBe('reply');expect(pdfPageState(pages,ops)).toHaveLength(2)
 const roots=projectPageComments([],page,1,ops,false);expect(roots[0].replies).toHaveLength(0);expect(roots[1].replies[0].pendingReply).toBe(true);expect(roots[1].readonly).toBe(false)
 const second=stagePdfLocalReply(pages,ops,ref(ops,1),'second',124,()=>{throw Error('must reuse identity')});expect(second[3].parentLocalId).toBe(id)
})
it('root edits preserve children/time; removal cascades in one undoable and restorable transaction',()=>{
 const storageMap=new Map<string,string>(),storage={getItem:(key:string)=>storageMap.get(key)??null,setItem:(key:string,value:string)=>{storageMap.set(key,value)},removeItem:(key:string)=>{storageMap.delete(key)}}
 const identity={documentId:'doc',revision:1,sourceSha256:'f'.repeat(64),scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},draft=new NativeDraft(identity,storage)
 draft.setOperations([root]);draft.setOperations(stagePdfLocalReply(pages,draft.operations,ref(draft.operations),'reply',123,()=>id));draft.undo();expect(draft.operations).toEqual([root]);draft.redo()
 const edited=stagePendingPdfNote(pages,draft.operations,ref(draft.operations),'edited root');expect(edited[1].createdMs).toBe(123);expect(edited[0].localId).toBe(id);draft.setOperations(edited)
 const restored=new NativeDraft(identity,storage);expect(restored.operations).toEqual(edited);validatePdfReplies(pages,restored.operations)
 draft.setOperations(stagePendingPdfNote(pages,draft.operations,ref(draft.operations),null));expect(draft.operations).toEqual([]);draft.undo();expect(draft.operations).toEqual(edited)
 const changed=stagePendingPdfReply(pages,edited,ref(edited,1),'edited reply');expect(changed[1].createdMs).toBe(123)
 expect(stagePendingPdfReply(pages,changed,ref(changed,1),null)[0].localId).toBe(id)
})
it('rejects stale roots, duplicate IDs, absent/foreign parents and mutation mixtures',()=>{
 const ops=stagePdfLocalReply(pages,[root],ref([root]),'reply',123,()=>id)
 expect(()=>stagePdfLocalReply(pages,ops,ref([root]),'bad')).toThrow(/草稿/)
 for(const bad of [[...ops,{...ops[0]}],[ops[1]],[ops[0],{...ops[1],pageId:'q'}],[...ops,{kind:'cropPage'}],[ops[0],{...ops[1],localId:id}],[{...ops[0],localId:'bad'},ops[1]]])expect(()=>validatePdfReplies(pages,bad)).toThrow()
})
