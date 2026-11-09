import {expect,it} from 'vitest'
import {stagePdfNote} from './pdf-notes'
import {pdfPageState} from './pdf-operations'
import {projectPageComments} from './pdf-comments'
import {NativeDraft} from './native-draft'
const root={sourceRef:'10R',annotationId:'a'.repeat(64),expectedAnnotationSha256:'1'.repeat(64),contents:'root',editable:false,removable:false,removalReason:'thread root',replyable:true}
const child={sourceRef:'11R',annotationId:'b'.repeat(64),expectedAnnotationSha256:'2'.repeat(64),parentAnnotationId:root.annotationId,contents:'same',editable:true,removable:true,removalReason:null}
const sibling={...child,sourceRef:'12R',annotationId:'c'.repeat(64),expectedAnnotationSha256:'3'.repeat(64)}
const page={pageId:'p',index:0,rotation:0,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:0,y:0,width:300,height:400},notesReadSafe:true,notes:[root,child,sibling]}
const raw=[{id:'10R',annotationType:1,subtype:'Text',contentsObj:{str:'root'}},...['11R','12R'].map(id=>({id,annotationType:1,subtype:'Text',contentsObj:{str:'same'},inReplyTo:'10R',replyType:'R'}))]
it('edits/removes exact saved leaf and projects its sibling and parent unchanged',()=>{
 const edited=stagePdfNote([page],[],page.pageId,child.annotationId,'edited','2026-11-09T09:00:00Z'),nodes=projectPageComments(raw,page,1,edited,false)
 expect(nodes[0].readonly).toBe(true);expect(nodes[0].replies.map(n=>n.contents)).toEqual(['edited','same']);expect(nodes[0].replies[0].savedReplyId).toBe(child.annotationId);expect(nodes[0].replies[0].readonly).toBe(false)
 const removed=stagePdfNote([page],edited,page.pageId,sibling.annotationId,null);expect(pdfPageState([page],removed)[0].notes?.map(n=>n.annotationId)).toEqual([root.annotationId,child.annotationId]);expect(projectPageComments(raw,page,1,removed,false)[0].replies).toHaveLength(1)
 expect(()=>pdfPageState([page],[...edited,{kind:'cropPage',pageId:'p',rect:[0,0,200,300]}])).toThrow(/分别保存/);expect(()=>pdfPageState([page],[...edited,{kind:'setPageSize',preset:'A4'}])).toThrow(/分别保存/)
 expect(()=>stagePdfNote([page],[],page.pageId,root.annotationId,'illegal')).toThrow(/thread root/)
})
it('drops mutation identities for missing/duplicate/wrong parent graphs and previews',()=>{
 expect(projectPageComments(raw,page,1,[],true)[0].replies.every(n=>n.savedReplyId===undefined&&n.readonly)).toBe(true)
 for(const annotations of [raw.slice(1),[...raw,{...raw[0]}],[raw[0],{...raw[1],inReplyTo:'12R'},raw[2]]])expect(projectPageComments(annotations,page,1,[],false).flatMap(n=>[n,...n.replies]).every(n=>n.savedReplyId===undefined)).toBe(true)
 expect(()=>stagePdfNote([{...page,notes:[child]}],[],page.pageId,child.annotationId,'new')).toThrow(/根便签/)
})
it('retains exact leaf operations across history/reload and restores source text by dropping its edit',()=>{
 const values=new Map<string,string>(),storage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value)},removeItem:(key:string)=>{values.delete(key)}}
 const identity={documentId:'thread',revision:1,sourceSha256:'f'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},draft=new NativeDraft(identity,storage)
 draft.setOperations(stagePdfNote([page],[],page.pageId,child.annotationId,'edited','2026-11-09T09:00:00Z'));const edited=draft.operations;draft.setOperations(stagePdfNote([page],draft.operations,page.pageId,child.annotationId,null));draft.undo();expect(draft.operations).toEqual(edited);draft.redo();expect(new NativeDraft(identity,storage).operations).toEqual(draft.operations)
 expect(stagePdfNote([page],edited,page.pageId,child.annotationId,'same')).toEqual([])
})
